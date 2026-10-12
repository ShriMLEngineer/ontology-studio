"""Deployment adapters per graph target kind (Phase 4.4).

Every adapter deploys a build's projection, *verifies* the deployment by counting what the target
actually holds afterwards, reads the graph back for the explorer and (RDF targets) runs read-only
SPARQL. Nothing is simulated: a target that cannot be reached or rejects a write produces a
:class:`DeploymentError` that is recorded on the deployment.
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx2
from pyoxigraph import BlankNode, NamedNode, QueryBoolean, QuerySolutions, RdfFormat
from pyoxigraph import Literal as OxLiteral
from rdflib import BNode, Graph

from app.core.errors import BusinessRuleError, UnavailableError
from app.modules.graph.projection import PropertyGraphProjection, RdfProjection
from app.modules.graph.sparql import (
    MAX_ROWS,
    QueryForm,
    SparqlResult,
    SparqlTerm,
    parse_json_results,
    triples_result,
)
from app.modules.graph.store import GraphStore
from app.modules.graph.targets import oxigraph_store, sparql_auth

INSERT_CHUNK = 2000
_IRI_FORBIDDEN = re.compile(r'[\s<>"{}|^`\\]')


class DeploymentError(RuntimeError):
    """A target rejected or failed a deployment; the message is shown to the user."""


@dataclass(frozen=True)
class TargetSpec:
    id: str
    name: str
    kind: str
    config: dict[str, Any] = field(default_factory=dict)
    secret_env: str | None = None


@dataclass
class DeployResult:
    graphs: dict[str, str]
    expected: dict[str, int]
    verified: dict[str, int]

    @property
    def ok(self) -> bool:
        return self.expected == self.verified


def _checked_iri(iri: str) -> str:
    if not iri.startswith(("http://", "https://", "urn:")) or _IRI_FORBIDDEN.search(iri):
        raise DeploymentError(f"'{iri}' is not a valid graph IRI.")
    return iri


def _nt(graph: Graph) -> str:
    return graph.serialize(format="nt", encoding="utf-8").decode("utf-8")


# ---------------------------------------------------------------------------------- property graph


class LocalSqlAdapter:
    """The application's canonical property-graph store (``graph_id`` = build id)."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def deploy_property_graph(self, build_id: str, projection: PropertyGraphProjection) -> DeployResult:
        self.store.upsert_vertices(build_id, projection.vertices)
        self.store.upsert_edges(build_id, projection.edges)
        vertices, edges = self.store.counts(build_id)
        return DeployResult(
            graphs={"graph_id": build_id},
            expected={"vertices": len(projection.vertices), "edges": len(projection.edges)},
            verified={"vertices": vertices, "edges": edges},
        )


# ---------------------------------------------------------------------------------- RDF


class RdfTargetAdapter(Protocol):
    def deploy_rdf(self, rdf: RdfProjection, *, include_ontology: bool) -> DeployResult: ...

    def fetch(self, graph_iri: str) -> Graph: ...

    def run_query(self, query: str, form: QueryForm, default_graph: str, named_graphs: list[str]) -> SparqlResult: ...


def _deploy(adapter: Any, rdf: RdfProjection, include_ontology: bool) -> DeployResult:
    parts = [("data", rdf.data_graph, rdf.data), ("provenance", rdf.provenance_graph, rdf.provenance)]
    if include_ontology:
        parts.append(("ontology", rdf.ontology_graph, rdf.ontology))
    graphs: dict[str, str] = {}
    expected: dict[str, int] = {}
    for role, iri, graph in parts:
        adapter.replace_graph(_checked_iri(iri), graph)
        graphs[role], expected[role] = iri, len(graph)
    verified = {role: adapter.count(iri) for role, iri in graphs.items()}
    return DeployResult(graphs, expected, verified)


def _ox_term(term: Any) -> SparqlTerm | None:
    if term is None:
        return None
    if isinstance(term, NamedNode):
        return SparqlTerm(type="uri", value=term.value)
    if isinstance(term, BlankNode):
        return SparqlTerm(type="bnode", value=term.value)
    if isinstance(term, OxLiteral):
        return SparqlTerm(type="literal", value=term.value, datatype=term.datatype.value, lang=term.language)
    return SparqlTerm(type="triple", value=str(term))


class OxigraphAdapter:
    """Embedded Oxigraph quad store; each build occupies its own named graphs."""

    def __init__(self, path: Path) -> None:
        self.store = oxigraph_store(path)

    def replace_graph(self, iri: str, graph: Graph) -> None:
        node = NamedNode(iri)
        try:
            self.store.remove_graph(node)
            self.store.load(_nt(graph).encode("utf-8"), format=RdfFormat.N_TRIPLES, to_graph=node)
        except (OSError, SyntaxError, ValueError) as error:
            raise DeploymentError(f"Oxigraph rejected graph <{iri}>: {error}") from error

    def count(self, iri: str) -> int:
        return sum(1 for _ in self.store.quads_for_pattern(None, None, None, NamedNode(iri)))

    def deploy_rdf(self, rdf: RdfProjection, *, include_ontology: bool) -> DeployResult:
        return _deploy(self, rdf, include_ontology)

    def fetch(self, graph_iri: str) -> Graph:
        payload = self.store.dump(format=RdfFormat.N_TRIPLES, from_graph=NamedNode(graph_iri)) or b""
        return Graph(bind_namespaces="none").parse(data=payload.decode("utf-8"), format="nt")

    def run_query(self, query: str, form: QueryForm, default_graph: str, named_graphs: list[str]) -> SparqlResult:
        try:
            result = self.store.query(
                query, default_graph=[NamedNode(default_graph)], named_graphs=[NamedNode(g) for g in named_graphs]
            )
        except (SyntaxError, OSError, ValueError) as error:
            raise BusinessRuleError(f"Oxigraph could not evaluate the query: {error}", code="SPARQL_QUERY_FAILED") from error
        if isinstance(result, QueryBoolean):
            return SparqlResult(form=form, variables=[], rows=[], boolean=bool(result), total=1, truncated=False)
        rows: list[dict[str, SparqlTerm | None]] = []
        truncated = False
        if isinstance(result, QuerySolutions):
            variables = [v.value for v in result.variables]
            for solution in result:  # lazy: evaluation stops after MAX_ROWS
                if len(rows) == MAX_ROWS:
                    truncated = True
                    break
                rows.append({name: _ox_term(solution[var]) for name, var in zip(variables, result.variables)})
            return SparqlResult(form=form, variables=variables, rows=rows, total=len(rows), truncated=truncated)
        for triple in result:
            if len(rows) == MAX_ROWS:
                truncated = True
                break
            rows.append({"subject": _ox_term(triple.subject), "predicate": _ox_term(triple.predicate),
                         "object": _ox_term(triple.object)})
        return SparqlResult(form=form, variables=["subject", "predicate", "object"], rows=rows, total=len(rows),
                            truncated=truncated)


class SparqlHttpAdapter:
    """Any SPARQL 1.1 Protocol endpoint: CLEAR + INSERT DATA over the update endpoint, queries over the query endpoint."""

    def __init__(self, config: dict[str, Any], secret_env: str | None, timeout: float = 60.0) -> None:
        self.query_url = (config.get("query_url") or "").strip()
        self.update_url = (config.get("update_url") or "").strip()
        self.auth = sparql_auth(config, secret_env)
        self.timeout = timeout
        if not self.query_url:
            raise DeploymentError("The connection has no query endpoint URL.")

    def _client(self) -> httpx2.Client:
        return httpx2.Client(timeout=self.timeout, auth=self.auth)

    def _post(self, url: str, data: dict[str, Any], accept: str) -> httpx2.Response:
        try:
            with self._client() as client:
                return client.post(url, data=data, headers={"Accept": accept})
        except httpx2.HTTPError as error:
            raise DeploymentError(f"SPARQL endpoint unreachable: {error.__class__.__name__}: {error}"[:400]) from error

    def _update(self, text: str) -> None:
        response = self._post(self.update_url, {"update": text}, "*/*")
        if response.status_code >= 400:
            raise DeploymentError(f"Update endpoint returned HTTP {response.status_code}: {response.text[:300]}")

    def replace_graph(self, iri: str, graph: Graph) -> None:
        if not self.update_url:
            raise DeploymentError("This SPARQL connection is query-only: register an update endpoint URL to deploy.")
        lines = [line for line in _nt(graph).splitlines() if line.strip()]
        # Blank-node labels are scoped to one request, so graphs with blank nodes are sent whole.
        has_blank_nodes = any(isinstance(term, BNode) for triple in graph for term in triple)
        size = max(len(lines), 1) if has_blank_nodes else INSERT_CHUNK
        chunks = [lines[i : i + size] for i in range(0, len(lines), size)] or [[]]
        for index, chunk in enumerate(chunks):
            operations = [f"CLEAR SILENT GRAPH <{iri}>"] if index == 0 else []
            if chunk:
                operations.append("INSERT DATA { GRAPH <" + iri + "> {\n" + "\n".join(chunk) + "\n} }")
            self._update(" ;\n".join(operations))

    def count(self, iri: str) -> int:
        result = self._select(f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{iri}> {{ ?s ?p ?o }} }}")
        try:
            return int(result["results"]["bindings"][0]["n"]["value"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise DeploymentError("The endpoint returned an unexpected COUNT result.") from error

    def _select(self, query: str) -> dict[str, Any]:
        response = self._post(self.query_url, {"query": query}, "application/sparql-results+json")
        if response.status_code >= 400:
            raise DeploymentError(f"Query endpoint returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            return response.json()
        except ValueError as error:
            raise DeploymentError("The query endpoint did not return SPARQL JSON results.") from error

    def deploy_rdf(self, rdf: RdfProjection, *, include_ontology: bool) -> DeployResult:
        return _deploy(self, rdf, include_ontology)

    def fetch(self, graph_iri: str) -> Graph:
        response = self._post(
            self.query_url,
            {"query": f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{_checked_iri(graph_iri)}> {{ ?s ?p ?o }} }}"},
            "application/n-triples, text/turtle;q=0.9",
        )
        if response.status_code >= 400:
            raise DeploymentError(f"Query endpoint returned HTTP {response.status_code}: {response.text[:300]}")
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        rdf_format = "turtle" if content_type in ("text/turtle", "application/x-turtle") else "nt"
        return Graph(bind_namespaces="none").parse(data=response.text, format=rdf_format)

    def run_query(self, query: str, form: QueryForm, default_graph: str, named_graphs: list[str]) -> SparqlResult:
        triples = form in ("construct", "describe")
        try:
            response = self._post(
                self.query_url,
                {"query": query, "default-graph-uri": default_graph, "named-graph-uri": named_graphs},
                "application/n-triples, text/turtle;q=0.9" if triples else "application/sparql-results+json",
            )
        except DeploymentError as error:
            raise UnavailableError(str(error), code="GRAPH_TARGET_UNREACHABLE") from error
        if response.status_code >= 400:
            raise BusinessRuleError(
                f"The SPARQL endpoint returned HTTP {response.status_code}: {response.text[:300]}", code="SPARQL_QUERY_FAILED"
            )
        if not triples:
            return parse_json_results(response.content, form)
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        graph = Graph(bind_namespaces="none").parse(
            data=response.text, format="turtle" if content_type in ("text/turtle", "application/x-turtle") else "nt"
        )
        return triples_result(graph, form)


def rdf_adapter(spec: TargetSpec, oxigraph_dir: Path) -> OxigraphAdapter | SparqlHttpAdapter:
    if spec.kind == "oxigraph":
        # The built-in store always lives at the configured server path; stored paths are not trusted.
        return OxigraphAdapter(oxigraph_dir)
    if spec.kind == "sparql-http":
        return SparqlHttpAdapter(spec.config, spec.secret_env)
    raise BusinessRuleError(f"'{spec.name}' ({spec.kind}) is not an RDF target.", code="GRAPH_TARGET_NOT_RDF")


def timed(fn: Any) -> tuple[Any, int]:
    started = time.perf_counter()
    value = fn()
    return value, int((time.perf_counter() - started) * 1000)
