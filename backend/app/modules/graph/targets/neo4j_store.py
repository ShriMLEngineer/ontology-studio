"""Neo4j and Neo4j AuraDB: connection probe and property-graph store (official ``neo4j`` driver).

Safety properties:

* the connection test only verifies connectivity/authentication and runs ``RETURN 1`` in a read
  transaction - it never writes;
* every node the application creates has the marker label ``OlsVertex`` and a ``_ols_scope``
  property (the build id); clearing and counting always filter on both, so data that was not written
  by a deployment is never matched, modified or deleted;
* labels and relationship types are escaped identifiers; every value travels as a query parameter.
"""

import hashlib
import logging
import threading
import time
from collections.abc import Sequence
from typing import Any

from neo4j import READ_ACCESS, Driver, GraphDatabase
from neo4j.exceptions import (
    AuthError,
    ConfigurationError,
    DriverError,
    Neo4jError,
    ServiceUnavailable,
    SessionExpired,
)

from app.core.net_safety import EndpointError, assert_reachable_target, check_bolt_uri
from app.modules.graph.store import GraphData, GraphEdge, GraphVertex
from app.modules.graph.targets import ConnectionResult
from app.modules.graph.targets.errors import DeploymentError
from app.modules.graph.targets.property_graph import (
    BATCH,
    PropertyTarget,
    ReadableGraphStore,
    encode_properties,
    json_list,
)

logger = logging.getLogger(__name__)

MARKER = "OlsVertex"
SCOPE = "_ols_scope"
_VERTEX_KEYS = ("_ols_scope", "_ols_id", "_ols_label", "_ols_name", "_ols_class_id", "_ols_fact_ids", "_ols_source_ids")
_EDGE_KEYS = (
    "_ols_scope", "_ols_id", "_ols_label", "_ols_predicate_id", "_ols_out_id", "_ols_in_id",
    "_ols_fact_ids", "_ols_source_ids",
)


def identifier(name: str) -> str:
    """A Cypher label / relationship type, escaped with backticks."""
    if not name or any(ord(ch) < 32 for ch in name):
        raise DeploymentError("The ontology produced an empty or invalid label for this graph.")
    return "`" + name.replace("`", "``") + "`"


def describe_error(error: Exception, database: str = "") -> str:
    """A provider-specific message without driver internals, addresses or credentials."""
    code = getattr(error, "code", "") or ""
    if isinstance(error, AuthError) or "Unauthorized" in code or "AuthenticationRateLimit" in code:
        return "Neo4j rejected the configured credentials."
    if "DatabaseNotFound" in code:
        return f"The database '{database}' was not found on the Neo4j server."
    if "Forbidden" in code or "AuthorizationFailed" in code:
        return "The Neo4j user is not permitted to perform this operation."
    if isinstance(error, ServiceUnavailable | SessionExpired):
        return "Could not connect to the Neo4j server (unreachable, TLS failure or service unavailable)."
    if isinstance(error, ConfigurationError):
        return "The Neo4j connection settings are invalid."
    return f"Neo4j reported an error ({code or error.__class__.__name__})."


# ---------------------------------------------------------------------------------- driver handling


def _settings(target: PropertyTarget) -> dict[str, Any]:
    config = target.config
    secret = target.secret
    if not secret:
        raise DeploymentError(f"Environment variable {target.secret_env or '(not configured)'} is not set on the server.")
    return {
        "uri": str(config.get("uri") or ""),
        "database": str(config.get("database") or "neo4j"),
        "username": str(config.get("username") or "neo4j"),
        "password": secret,
        "timeout": float(config.get("timeout_seconds") or 15),
    }


def _new_driver(target: PropertyTarget, settings: dict[str, Any]) -> Driver:
    try:
        _, host, port = check_bolt_uri(settings["uri"], field="Bolt URI", allow_private=target.allow_private)
        assert_reachable_target(host, port, allow_private=target.allow_private)
    except EndpointError as error:
        raise DeploymentError(str(error)) from error
    timeout = settings["timeout"]
    try:
        return GraphDatabase.driver(
            settings["uri"],
            auth=(settings["username"], settings["password"]),
            connection_timeout=timeout,
            connection_acquisition_timeout=timeout,
            max_transaction_retry_time=timeout,
            user_agent="OntologyLifecycleStudio",
        )
    except (DriverError, Neo4jError, ValueError) as error:
        raise DeploymentError(describe_error(error, settings["database"])) from error


_drivers: dict[tuple[str, str, str, float], Driver] = {}
_drivers_lock = threading.Lock()


def acquire_driver(target: PropertyTarget) -> tuple[Driver, str]:
    """A pooled driver per (uri, user, credential, timeout); the credential only contributes a hash to the key."""
    settings = _settings(target)
    digest = hashlib.sha256(settings["password"].encode()).hexdigest()
    key = (settings["uri"], settings["username"], digest, settings["timeout"])
    with _drivers_lock:
        driver = _drivers.get(key)
        if driver is None:
            driver = _drivers[key] = _new_driver(target, settings)
    return driver, settings["database"]


def close_drivers() -> None:
    with _drivers_lock:
        drivers = list(_drivers.values())
        _drivers.clear()
    for driver in drivers:
        try:
            driver.close()
        except (DriverError, Neo4jError):  # pragma: no cover - best effort on shutdown
            logger.debug("Closing a Neo4j driver failed", exc_info=True)


# ---------------------------------------------------------------------------------- connection probe


def check_neo4j(config: dict[str, Any], secret_env: str | None, *, allow_private: bool = True) -> ConnectionResult:
    """Official driver connectivity verification plus a read-only ``RETURN 1`` in the configured database."""
    started = time.perf_counter()

    def finish(ok: bool, message: str, details: dict[str, Any] | None = None) -> ConnectionResult:
        return ConnectionResult(ok, message, int((time.perf_counter() - started) * 1000), details or {})

    target = PropertyTarget("neo4j", config, secret_env, allow_private)
    try:
        settings = _settings(target)
        driver = _new_driver(target, settings)
    except DeploymentError as error:
        return finish(False, str(error))
    database = settings["database"]
    try:
        with driver:
            driver.verify_connectivity()
            info = driver.get_server_info()
            with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
                session.execute_read(lambda tx: list(tx.run("RETURN 1 AS ok")))
    except (DriverError, Neo4jError) as error:
        return finish(False, describe_error(error, database))
    agent = str(getattr(info, "agent", "") or "Neo4j")
    return finish(
        True,
        f"Connected to {agent}; database '{database}' answered a read-only query.",
        {"server": agent, "database": database},
    )


# ---------------------------------------------------------------------------------- store


def _vertex_from(node: Any) -> GraphVertex:
    props = dict(node)
    system = {key: props.pop(key, None) for key in _VERTEX_KEYS}
    labels = [label for label in getattr(node, "labels", ()) if label != MARKER]
    return GraphVertex(
        id=str(system["_ols_id"]),
        label=str(system["_ols_label"] or (labels[0] if labels else "")),
        name=str(system["_ols_name"] or ""),
        class_id=str(system["_ols_class_id"] or ""),
        properties=props,
        fact_ids=list(system["_ols_fact_ids"] or []),
        source_ids=list(system["_ols_source_ids"] or []),
    )


def _edge_from(rel: Any) -> GraphEdge:
    props = dict(rel)
    system = {key: props.pop(key, None) for key in _EDGE_KEYS}
    return GraphEdge(
        id=str(system["_ols_id"]),
        label=str(system["_ols_label"] or getattr(rel, "type", "")),
        predicate_id=str(system["_ols_predicate_id"] or ""),
        out_id=str(system["_ols_out_id"]),
        in_id=str(system["_ols_in_id"]),
        properties=props,
        fact_ids=list(system["_ols_fact_ids"] or []),
        source_ids=list(system["_ols_source_ids"] or []),
    )


def _vertex_row(scope: str, vertex: GraphVertex) -> dict[str, Any]:
    props = encode_properties(vertex.properties)
    props.update({
        "_ols_scope": scope, "_ols_id": vertex.id, "_ols_label": vertex.label, "_ols_name": vertex.name,
        "_ols_class_id": vertex.class_id, "_ols_fact_ids": json_list(vertex.fact_ids),
        "_ols_source_ids": json_list(vertex.source_ids),
    })
    return props


def _edge_row(scope: str, edge: GraphEdge) -> dict[str, Any]:
    props = encode_properties(edge.properties)
    props.update({
        "_ols_scope": scope, "_ols_id": edge.id, "_ols_label": edge.label, "_ols_predicate_id": edge.predicate_id,
        "_ols_out_id": edge.out_id, "_ols_in_id": edge.in_id, "_ols_fact_ids": json_list(edge.fact_ids),
        "_ols_source_ids": json_list(edge.source_ids),
    })
    return props


def _chunks(items: Sequence[Any], size: int = BATCH) -> list[Sequence[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class Neo4jGraphStore(ReadableGraphStore):
    name = "neo4j"

    def __init__(self, driver: Driver, database: str) -> None:
        self.driver = driver
        self.database = database

    @classmethod
    def connect(cls, target: PropertyTarget) -> "Neo4jGraphStore":
        driver, database = acquire_driver(target)
        return cls(driver, database)

    def close(self) -> None:  # the driver is pooled; see close_drivers()
        return None

    # ------------------------------------------------------------------ execution helpers

    def _read(self, query: str, params: dict[str, Any] | None = None) -> list[Any]:
        try:
            with self.driver.session(database=self.database, default_access_mode=READ_ACCESS) as session:
                return session.execute_read(lambda tx: list(tx.run(query, params or {})))
        except (DriverError, Neo4jError) as error:
            raise DeploymentError(describe_error(error, self.database)) from error

    def _write(self, query: str, params: dict[str, Any] | None = None) -> list[Any]:
        try:
            with self.driver.session(database=self.database) as session:
                return session.execute_write(lambda tx: list(tx.run(query, params or {})))
        except (DriverError, Neo4jError) as error:
            raise DeploymentError(describe_error(error, self.database)) from error

    # ------------------------------------------------------------------ deployment

    def _ensure_index(self) -> None:
        try:
            self._write(f"CREATE INDEX ols_vertex_scope_id IF NOT EXISTS FOR (n:{MARKER}) ON (n.{SCOPE}, n._ols_id)")
        except DeploymentError:
            logger.info("Could not create the lookup index on %s; continuing without it.", MARKER)

    def clear_scope(self, scope: str) -> None:
        while True:
            rows = self._write(
                f"MATCH (n:{MARKER} {{{SCOPE}: $scope}}) WITH n LIMIT $batch DETACH DELETE n RETURN count(*) AS removed",
                {"scope": scope, "batch": BATCH * 4},
            )
            if not rows or rows[0]["removed"] == 0:
                return

    def replace_scope(self, scope: str, vertices: Sequence[GraphVertex], edges: Sequence[GraphEdge]) -> None:
        self._ensure_index()
        self.clear_scope(scope)
        by_label: dict[str, list[dict[str, Any]]] = {}
        for vertex in vertices:
            by_label.setdefault(vertex.label, []).append(_vertex_row(scope, vertex))
        for label, rows in by_label.items():
            for chunk in _chunks(rows):
                self._write(f"UNWIND $rows AS props CREATE (n:{MARKER}:{identifier(label)}) SET n = props", {"rows": list(chunk)})
        by_type: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            by_type.setdefault(edge.label, []).append(
                {"out": edge.out_id, "in": edge.in_id, "props": _edge_row(scope, edge)}
            )
        for rel_type, rows in by_type.items():
            for chunk in _chunks(rows):
                self._write(
                    f"UNWIND $rows AS row "
                    f"MATCH (a:{MARKER} {{{SCOPE}: $scope, _ols_id: row.out}}) "
                    f"MATCH (b:{MARKER} {{{SCOPE}: $scope, _ols_id: row.in}}) "
                    f"CREATE (a)-[r:{identifier(rel_type)}]->(b) SET r = row.props",
                    {"rows": list(chunk), "scope": scope},
                )

    # ------------------------------------------------------------------ reads

    def counts(self, graph_id: str) -> tuple[int, int]:
        vertices = self._read(f"MATCH (n:{MARKER} {{{SCOPE}: $scope}}) RETURN count(n) AS c", {"scope": graph_id})
        edges = self._read(
            f"MATCH (:{MARKER} {{{SCOPE}: $scope}})-[r {{{SCOPE}: $scope}}]->(:{MARKER} {{{SCOPE}: $scope}}) "
            "RETURN count(r) AS c",
            {"scope": graph_id},
        )
        return int(vertices[0]["c"]), int(edges[0]["c"])

    def get_vertex(self, graph_id: str, vertex_id: str) -> GraphVertex | None:
        rows = self._read(
            f"MATCH (n:{MARKER} {{{SCOPE}: $scope, _ols_id: $id}}) RETURN n LIMIT 1", {"scope": graph_id, "id": vertex_id}
        )
        return _vertex_from(rows[0]["n"]) if rows else None

    def get_edge(self, graph_id: str, edge_id: str) -> GraphEdge | None:
        rows = self._read(
            f"MATCH (:{MARKER} {{{SCOPE}: $scope}})-[r {{{SCOPE}: $scope, _ols_id: $id}}]->() RETURN r LIMIT 1",
            {"scope": graph_id, "id": edge_id},
        )
        return _edge_from(rows[0]["r"]) if rows else None

    def fetch_graph(self, graph_id: str, *, limit: int) -> GraphData:
        total = self._read(f"MATCH (n:{MARKER} {{{SCOPE}: $scope}}) RETURN count(n) AS c", {"scope": graph_id})[0]["c"]
        rows = self._read(
            f"MATCH (n:{MARKER} {{{SCOPE}: $scope}}) RETURN n ORDER BY n._ols_label, n._ols_name, n._ols_id LIMIT $limit",
            {"scope": graph_id, "limit": limit},
        )
        vertices = [_vertex_from(row["n"]) for row in rows]
        edges: list[GraphEdge] = []
        if vertices:
            edge_rows = self._read(
                f"MATCH (a:{MARKER} {{{SCOPE}: $scope}})-[r {{{SCOPE}: $scope}}]->(b:{MARKER} {{{SCOPE}: $scope}}) "
                "WHERE a._ols_id IN $ids AND b._ols_id IN $ids RETURN r",
                {"scope": graph_id, "ids": [v.id for v in vertices]},
            )
            edges = sorted((_edge_from(row["r"]) for row in edge_rows), key=lambda e: e.id)
        return GraphData(vertices=vertices, edges=edges, truncated=int(total) > len(vertices))

    def search_vertices(
        self, graph_id: str, text: str, *, label: str | None = None, limit: int = 20
    ) -> list[GraphVertex]:
        rows = self._read(
            f"MATCH (n:{MARKER} {{{SCOPE}: $scope}}) "
            "WHERE ($label IS NULL OR n._ols_label = $label) "
            "AND ($text = '' OR toLower(n._ols_name) CONTAINS $text OR toLower(n._ols_id) CONTAINS $text) "
            "RETURN n ORDER BY n._ols_name LIMIT $limit",
            {"scope": graph_id, "label": label, "text": text.strip().lower(), "limit": limit},
        )
        return [_vertex_from(row["n"]) for row in rows]

    def edges_of(self, graph_id: str, vertex_id: str) -> list[GraphEdge]:
        rows = self._read(
            f"MATCH (a:{MARKER} {{{SCOPE}: $scope, _ols_id: $id}})-[r {{{SCOPE}: $scope}}]-(b:{MARKER} {{{SCOPE}: $scope}}) "
            "RETURN DISTINCT r",
            {"scope": graph_id, "id": vertex_id},
        )
        return sorted((_edge_from(row["r"]) for row in rows), key=lambda e: (e.label, e.id))
