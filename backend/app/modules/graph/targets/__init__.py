"""Graph database targets: provider catalogue, connection tests and deployment adapters.

The catalogue (:mod:`app.modules.graph.targets.catalog`) describes every provider; this package
re-exports it and holds the shared connection-test helpers. Connection tests are read-only and run
on the backend: they verify connectivity and authentication, not write permission or deployment
readiness. Nothing is simulated - an unreachable target yields a failed result.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

import httpx2
from pyoxigraph import Store
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.net_safety import EndpointError, assert_url_reachable_target
from app.core.secrets import get_secret, secret_is_set
from app.modules.graph.targets.catalog import (
    BUILTIN_TARGETS,
    KINDS,
    ConfigField,
    GraphModel,
    TargetKind,
    effective_auth_type,
    sparql_endpoints,
)

__all__ = [
    "BUILTIN_TARGETS",
    "KINDS",
    "ConfigField",
    "ConnectionResult",
    "GraphModel",
    "TargetKind",
    "check_local_sql",
    "check_oxigraph",
    "check_sparql",
    "check_sparql_http",
    "oxigraph_store",
    "resolve_auth",
    "sparql_auth",
]


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


# ---------------------------------------------------------------------------------- SPARQL


def resolve_auth(config: dict[str, Any], secret_env: str | None) -> tuple[tuple[str, str] | None, dict[str, str]]:
    """HTTP authentication of a SPARQL registration: (basic-auth tuple, extra headers). The credential
    value is read from the server environment at call time and exists only in memory."""
    auth_type = effective_auth_type(config)
    secret = get_secret(secret_env)
    if auth_type == "basic":
        return (str(config.get("username") or "").strip(), secret or ""), {}
    if auth_type == "bearer" and secret:
        return None, {"Authorization": f"Bearer {secret}"}
    if auth_type == "gdb-token" and secret:
        return None, {"Authorization": f"GDB {secret}"}
    return None, {}


def sparql_auth(config: dict[str, Any], secret_env: str | None) -> tuple[str, str] | None:
    return resolve_auth(config, secret_env)[0]


def credential_problem(config: dict[str, Any], secret_env: str | None) -> str | None:
    auth_type = effective_auth_type(config)
    if auth_type == "none":
        return None
    if auth_type == "basic" and not secret_env:
        return None  # legacy registrations may use a user name with an empty password
    if not secret_env or not secret_is_set(secret_env):
        return f"Environment variable {secret_env or '(not configured)'} is not set on the server."
    return None


def check_sparql(
    kind_id: str,
    config: dict[str, Any],
    secret_env: str | None,
    *,
    allow_private: bool = True,
    timeout: float = 10.0,
) -> ConnectionResult:
    """Read-only SPARQL ``ASK`` against the query endpoint (GraphDB, Fuseki and any SPARQL 1.1 endpoint)."""
    query_url, update_url = sparql_endpoints(kind_id, config)
    if not query_url:
        return ConnectionResult(False, "The query endpoint URL is missing.")
    problem = credential_problem(config, secret_env)
    if problem:
        return ConnectionResult(False, problem)

    def run() -> ConnectionResult:
        try:
            assert_url_reachable_target(query_url, allow_private=allow_private)
            auth, headers = resolve_auth(config, secret_env)
            with httpx2.Client(timeout=timeout, auth=auth, headers=headers) as client:
                response = client.post(
                    query_url,
                    data={"query": "ASK { ?s ?p ?o }"},
                    headers={"Accept": "application/sparql-results+json"},
                )
        except EndpointError as error:
            return ConnectionResult(False, str(error))
        except httpx2.TimeoutException:
            return ConnectionResult(False, f"The query endpoint did not respond within {timeout:.0f} seconds.")
        except httpx2.HTTPError as error:
            return ConnectionResult(False, f"Query endpoint unreachable ({error.__class__.__name__}).")
        if response.status_code in (401, 403):
            return ConnectionResult(False, f"The query endpoint rejected the credentials (HTTP {response.status_code}).")
        if response.status_code == 404:
            return ConnectionResult(False, "The query endpoint was not found (HTTP 404). Check the URL and repository.")
        if response.status_code >= 400:
            return ConnectionResult(False, f"Query endpoint returned HTTP {response.status_code}.")
        try:
            answer = response.json()["boolean"]
        except (ValueError, KeyError, TypeError):
            return ConnectionResult(False, "The endpoint did not return a SPARQL JSON boolean result for ASK.")
        note = " Update endpoint configured (not exercised by the test)." if update_url else (
            " No update endpoint: the connection is query-only."
        )
        return ConnectionResult(
            True,
            f"SPARQL endpoint answered ASK ({'data present' if answer else 'empty dataset'}).{note}",
            details={"has_data": bool(answer), "updatable": bool(update_url)},
        )

    return _timed(run)


def check_sparql_http(config: dict[str, Any], secret_env: str | None, timeout: float = 10.0) -> ConnectionResult:
    return check_sparql("sparql-http", config, secret_env, timeout=timeout)
