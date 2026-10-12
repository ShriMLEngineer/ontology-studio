"""Read-only SPARQL for the deployment query console (Phase 4.4).

Queries are parsed with rdflib before they reach a store: only SELECT, ASK, CONSTRUCT and DESCRIBE
are accepted (every SPARQL Update form is rejected by the query grammar) and federated ``SERVICE``
calls are refused. Results of every target are normalized to one shape.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel
from rdflib import BNode, Graph, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.parserutils import CompValue

from app.core.errors import BusinessRuleError

QueryForm = Literal["select", "ask", "construct", "describe"]
MAX_ROWS = 1000
_FORMS: dict[str, QueryForm] = {
    "SelectQuery": "select",
    "AskQuery": "ask",
    "ConstructQuery": "construct",
    "DescribeQuery": "describe",
}


class SparqlTerm(BaseModel):
    type: Literal["uri", "literal", "bnode", "triple"]
    value: str
    datatype: str | None = None
    lang: str | None = None


class SparqlResult(BaseModel):
    form: QueryForm
    variables: list[str]
    rows: list[dict[str, SparqlTerm | None]]
    boolean: bool | None = None
    total: int
    truncated: bool
    elapsed_ms: int = 0
    target: str = ""
    default_graph: str = ""


def _contains(node: Any, name: str) -> bool:
    if isinstance(node, CompValue):
        return node.name == name or any(_contains(v, name) for v in node.values())
    if isinstance(node, (list, tuple, set)):
        return any(_contains(v, name) for v in node)
    return False


def check_read_only(query: str) -> QueryForm:
    """Return the query form, or raise ``SPARQL_QUERY_REJECTED`` for updates, SERVICE and syntax errors."""
    text = query.strip()
    if not text:
        raise BusinessRuleError("Enter a SPARQL query.", code="SPARQL_QUERY_REJECTED")
    try:
        prepared = prepareQuery(text)
    except Exception as error:  # noqa: BLE001 - pyparsing and rdflib raise several exception types
        message = str(error).splitlines()[0][:300]
        raise BusinessRuleError(
            f"Only read-only SPARQL 1.1 queries (SELECT, ASK, CONSTRUCT, DESCRIBE) are accepted: {message}",
            code="SPARQL_QUERY_REJECTED",
        ) from error
    form = _FORMS.get(prepared.algebra.name)
    if form is None:
        raise BusinessRuleError(f"Unsupported query form {prepared.algebra.name}.", code="SPARQL_QUERY_REJECTED")
    if _contains(prepared.algebra, "ServiceGraphPattern"):
        raise BusinessRuleError("Federated queries (SERVICE) are not allowed.", code="SPARQL_QUERY_REJECTED")
    return form


def _json_term(value: dict[str, Any] | None) -> SparqlTerm | None:
    if value is None:
        return None
    kind = value.get("type")
    if kind == "typed-literal":  # SPARQL 1.0 JSON variant
        kind = "literal"
    if kind not in ("uri", "literal", "bnode", "triple"):
        kind = "literal"
    raw = value.get("value")
    return SparqlTerm(
        type=kind,
        value=raw if isinstance(raw, str) else json.dumps(raw),
        datatype=value.get("datatype"),
        lang=value.get("xml:lang"),
    )


def parse_json_results(payload: bytes | str, form: QueryForm) -> SparqlResult:
    """Parse SPARQL 1.1 Query Results JSON (SELECT/ASK)."""
    try:
        data = json.loads(payload)
    except ValueError as error:
        raise BusinessRuleError("The store did not return SPARQL JSON results.", code="SPARQL_RESULT_INVALID") from error
    if "boolean" in data:
        return SparqlResult(form=form, variables=[], rows=[], boolean=bool(data["boolean"]), total=1, truncated=False)
    variables = list(data.get("head", {}).get("vars", []))
    bindings = data.get("results", {}).get("bindings", [])
    rows = [{var: _json_term(row.get(var)) for var in variables} for row in bindings[:MAX_ROWS]]
    return SparqlResult(form=form, variables=variables, rows=rows, total=len(bindings), truncated=len(bindings) > MAX_ROWS)


def _rdf_term(node: Any) -> SparqlTerm:
    if isinstance(node, URIRef):
        return SparqlTerm(type="uri", value=str(node))
    if isinstance(node, BNode):
        return SparqlTerm(type="bnode", value=str(node))
    if isinstance(node, RdfLiteral):
        return SparqlTerm(type="literal", value=str(node), datatype=str(node.datatype) if node.datatype else None,
                          lang=node.language)
    return SparqlTerm(type="literal", value=str(node))


def triples_result(graph: Graph, form: QueryForm) -> SparqlResult:
    triples = sorted(graph, key=lambda t: (str(t[0]), str(t[1]), str(t[2])))
    rows = [
        {"subject": _rdf_term(s), "predicate": _rdf_term(p), "object": _rdf_term(o)} for s, p, o in triples[:MAX_ROWS]
    ]
    return SparqlResult(
        form=form, variables=["subject", "predicate", "object"], rows=rows, total=len(triples), truncated=len(triples) > MAX_ROWS
    )
