"""Graph database targets: catalogue, connection tests and (milestone 4.4) deployment adapters.

Only kinds with a working adapter are offered for registration. Kinds that need infrastructure
that is not available (for example a reachable Neo4j server to implement and verify an adapter
against) are listed as *not available* with the reason - no integration is simulated.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import httpx2
from pyoxigraph import Store
from sqlalchemy import text
from sqlalchemy.orm import Session

GraphModel = Literal["rdf", "property-graph"]


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    required: bool = False
    secret: bool = False
    placeholder: str = ""


@dataclass(frozen=True)
class TargetKind:
    id: str
    label: str
    model: GraphModel
    builtin: bool
    registrable: bool
    available: bool
    description: str
    unavailable_reason: str = ""
    fields: tuple[ConfigField, ...] = field(default_factory=tuple)


KINDS: dict[str, TargetKind] = {
    k.id: k
    for k in (
        TargetKind(
            id="local-sql",
            label="Local SQL property graph",
            model="property-graph",
            builtin=True,
            registrable=False,
            available=True,
            description="Vertices and edges in the application database (SqlGraphStore). Always available.",
        ),
        TargetKind(
            id="oxigraph",
            label="Embedded Oxigraph (RDF quad store)",
            model="rdf",
            builtin=True,
            registrable=False,
            available=True,
            description="RDF quad store embedded in the backend (pyoxigraph, on disk). One named graph per build.",
        ),
        TargetKind(
            id="sparql-http",
            label="SPARQL 1.1 endpoint",
            model="rdf",
            builtin=False,
            registrable=True,
            available=True,
            description=(
                "Any store that implements the SPARQL 1.1 Protocol (query and update): Apache Jena Fuseki, "
                "GraphDB, Stardog, Oxigraph server, Virtuoso, Amazon Neptune (SPARQL)."
            ),
            fields=(
                ConfigField("query_url", "Query endpoint URL", required=True, placeholder="http://localhost:3030/ds/query"),
                ConfigField("update_url", "Update endpoint URL (required to deploy)", placeholder="http://localhost:3030/ds/update"),
                ConfigField("username", "User name (HTTP basic)"),
                ConfigField("secret_env", "Environment variable with the password", secret=True, placeholder="OLS_SPARQL_PASSWORD"),
            ),
        ),
        TargetKind(
            id="neo4j",
            label="Neo4j (Cypher)",
            model="property-graph",
            builtin=False,
            registrable=False,
            available=False,
            description="Labelled property graph over Bolt.",
            unavailable_reason=(
                "No adapter yet: a Neo4j adapter can only be implemented and verified against a reachable Neo4j "
                "server, which is not available in this environment. Compatibility reports are available."
            ),
        ),
        TargetKind(
            id="cosmos-gremlin",
            label="Azure Cosmos DB for Apache Gremlin",
            model="property-graph",
            builtin=False,
            registrable=False,
            available=False,
            description="Gremlin property graph (TinkerPop) with partitioning.",
            unavailable_reason=(
                "No adapter yet: requires an Azure Cosmos DB account (or the emulator) to implement and verify against. "
                "Compatibility reports are available."
            ),
        ),
    )
}

BUILTIN_TARGETS = {
    "local-sql": ("Local SQL property graph", "local-sql"),
    "oxigraph-embedded": ("Embedded Oxigraph", "oxigraph"),
}


@dataclass
class ConnectionResult:
    ok: bool
    message: str
    latency_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "latency_ms": self.latency_ms, "details": self.details}


# ---------------------------------------------------------------------------------- embedded Oxigraph

_stores: dict[str, Store] = {}
_stores_lock = Lock()


def oxigraph_store(path: Path) -> Store:
    """One Store per directory per process (RocksDB holds an exclusive lock on the directory)."""
    key = str(path.resolve())
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            path.mkdir(parents=True, exist_ok=True)
            store = _stores[key] = Store(key)
        return store


# ---------------------------------------------------------------------------------- connection tests


def _timed(fn: Any) -> ConnectionResult:
    started = time.perf_counter()
    result: ConnectionResult = fn()
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result


def check_local_sql(session: Session) -> ConnectionResult:
    def run() -> ConnectionResult:
        vertices = session.execute(text("SELECT count(*) FROM graph_vertices")).scalar_one()
        edges = session.execute(text("SELECT count(*) FROM graph_edges")).scalar_one()
        return ConnectionResult(True, f"Application database reachable: {vertices} vertices, {edges} edges stored.",
                                details={"vertices": vertices, "edges": edges})

    return _timed(run)


def check_oxigraph(path: Path) -> ConnectionResult:
    def run() -> ConnectionResult:
        store = oxigraph_store(path)
        graphs = sum(1 for _ in store.named_graphs())
        return ConnectionResult(True, f"Embedded Oxigraph store open at {path}: {len(store)} quads in {graphs} named graph(s).",
                                details={"quads": len(store), "named_graphs": graphs})

    return _timed(run)


def sparql_auth(config: dict[str, Any], secret_env: str | None) -> tuple[str, str] | None:
    username = (config.get("username") or "").strip()
    if not username:
        return None
    password = os.environ.get(secret_env or "", "") if secret_env else ""
    return username, password


def check_sparql_http(config: dict[str, Any], secret_env: str | None, timeout: float = 10.0) -> ConnectionResult:
    query_url = (config.get("query_url") or "").strip()
    if not query_url:
        return ConnectionResult(False, "The query endpoint URL is missing.")
    if secret_env and config.get("username") and secret_env not in os.environ:
        return ConnectionResult(False, f"Environment variable {secret_env} is not set on the server.")

    def run() -> ConnectionResult:
        try:
            with httpx2.Client(timeout=timeout, auth=sparql_auth(config, secret_env)) as client:
                response = client.post(
                    query_url,
                    data={"query": "ASK { ?s ?p ?o }"},
                    headers={"Accept": "application/sparql-results+json"},
                )
        except httpx2.HTTPError as error:
            return ConnectionResult(False, f"Query endpoint unreachable: {error.__class__.__name__}: {error}"[:300])
        if response.status_code >= 400:
            return ConnectionResult(False, f"Query endpoint returned HTTP {response.status_code}.")
        try:
            answer = response.json()["boolean"]
        except (ValueError, KeyError, TypeError):
            return ConnectionResult(False, "The endpoint did not return a SPARQL JSON boolean result for ASK.")
        note = " Update endpoint configured (not exercised by the test)." if config.get("update_url") else (
            " No update endpoint: the connection is query-only."
        )
        return ConnectionResult(
            True,
            f"SPARQL endpoint answered ASK ({'data present' if answer else 'empty dataset'}).{note}",
            details={"has_data": bool(answer), "updatable": bool(config.get("update_url"))},
        )

    return _timed(run)
