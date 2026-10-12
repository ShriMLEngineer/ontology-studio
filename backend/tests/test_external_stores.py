"""Neo4j and Cosmos DB Gremlin adapters against scripted drivers.

The fakes record exactly what the adapters send, so these tests prove the safety properties that matter
independently of a live server: read-only probes, scope-confined writes and deletes, values only as
parameters/bindings, sanitised errors and the documented Cosmos client settings.
"""

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Self

import pytest
from gremlin_python.driver.protocol import GremlinServerError
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

from app.modules.graph.store import GraphEdge, GraphVertex
from app.modules.graph.targets import gremlin_store, neo4j_store
from app.modules.graph.targets.errors import DeploymentError
from app.modules.graph.targets.gremlin_store import (
    CosmosGremlinStore,
    check_cosmos,
    literal,
)
from app.modules.graph.targets.neo4j_store import (
    Neo4jGraphStore,
    check_neo4j,
    identifier,
)
from app.modules.graph.targets.property_graph import (
    PropertyTarget,
    encode_properties,
    encode_value,
)

SECRET = "super-secret-credential-value"
NEO4J_CONFIG = {"uri": "neo4j+s://abc.databases.neo4j.io", "database": "kg", "username": "neo4j", "timeout_seconds": "7"}
COSMOS_CONFIG = {
    "endpoint": "my-account.gremlin.cosmos.azure.com", "port": "443", "database": "graphdb", "graph": "knowledge",
    "partition_key_path": "/pk", "timeout_seconds": "30",
}


def _vertices() -> list[GraphVertex]:
    return [
        GraphVertex(id="v1", label="Supplier", name="Acme", class_id="c1",
                    properties={"name": ["Acme"], "id": ["EXT-1"], "pk": ["x"], "tags": ["a", "b"]},
                    fact_ids=["f1"], source_ids=["d1"]),
        GraphVertex(id="v2", label="Odd`Label'; drop()", name="PO", class_id="c2", properties={}, fact_ids=["f2"]),
    ]


def _edges() -> list[GraphEdge]:
    return [GraphEdge(id="e1", label="PLACED`BY", predicate_id="p1", out_id="v2", in_id="v1",
                      properties={"predicate_label": "placed by"}, fact_ids=["f2"], source_ids=["d1"])]


# ---------------------------------------------------------------------------------- value encoding


def test_property_encoding_is_storable_and_collision_free() -> None:
    assert encode_value([1, 2.5]) == [1.0, 2.5], "numeric lists become homogeneous"
    assert encode_value([1, "a", True]) == ["1", "a", "true"], "other mixed lists become strings"
    assert encode_value({"a": [1]}) == '{"a": [1]}' and encode_value(2**70) == str(2**70)
    assert encode_value(float("nan")) == "nan"
    encoded = encode_properties({"name": ["x"], "_ols_id": "evil", "gone": None, "id": 1}, reserved={"id"})
    assert encoded == {"name": ["x"], "attr__ols_id": "evil", "attr_id": 1}, "system names can never be overwritten"


def test_identifiers_are_escaped_not_interpolated() -> None:
    assert identifier("Supplier") == "`Supplier`"
    assert identifier("a`b") == "`a``b`"
    with pytest.raises(DeploymentError):
        identifier("")
    assert literal("Odd'Label; drop()") == "'Odd_Label__drop__'"
    assert literal("") == "'x'"


# ---------------------------------------------------------------------------------- Neo4j (scripted driver)


class FakeTx:
    def __init__(self, driver: "FakeDriver") -> None:
        self.driver = driver

    def run(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.driver.log.append((query, dict(params or {}), self.driver.mode))
        return self.driver.responder(query, params or {})


class FakeSession:
    def __init__(self, driver: "FakeDriver", database: str, access: Any) -> None:
        self.driver, self.database, self.access = driver, database, access

    def __enter__(self) -> Self:
        self.driver.sessions.append((self.database, self.access))
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def _run(self, mode: str, fn: Callable[[FakeTx], Any]) -> Any:
        self.driver.mode = mode
        return fn(FakeTx(self.driver))

    def execute_read(self, fn: Callable[[FakeTx], Any]) -> Any:
        return self._run("read", fn)

    def execute_write(self, fn: Callable[[FakeTx], Any]) -> Any:
        return self._run("write", fn)


class FakeDriver:
    def __init__(self, responder: Callable[[str, dict[str, Any]], list[Any]] | None = None) -> None:
        self.log: list[tuple[str, dict[str, Any], str]] = []
        self.sessions: list[tuple[str, Any]] = []
        self.mode = ""
        self.verified = 0
        self.closed = False
        self.responder = responder or (lambda q, p: [{"removed": 0, "c": 0, "ok": 1}])
        self.verify_error: Exception | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True

    def verify_connectivity(self) -> None:
        self.verified += 1
        if self.verify_error:
            raise self.verify_error

    def get_server_info(self) -> Any:
        return SimpleNamespace(agent="Neo4j/5.27-fake")

    def session(self, database: str, default_access_mode: Any = None) -> FakeSession:
        return FakeSession(self, database, default_access_mode)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def neo4j_driver(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    created: dict[str, Any] = {"driver": FakeDriver(), "calls": []}

    def factory(uri: str, **options: Any) -> FakeDriver:
        created["calls"].append((uri, options))
        return created["driver"]  # type: ignore[no-any-return]

    monkeypatch.setattr(neo4j_store.GraphDatabase, "driver", factory)
    monkeypatch.setenv("NEO4J_PASSWORD", SECRET)
    neo4j_store.close_drivers()
    yield created
    neo4j_store.close_drivers()


def test_neo4j_probe_verifies_connectivity_and_only_reads(neo4j_driver: dict[str, Any]) -> None:
    result = check_neo4j(NEO4J_CONFIG, "NEO4J_PASSWORD")
    assert result.ok and "Neo4j/5.27-fake" in result.message and "'kg'" in result.message
    driver: FakeDriver = neo4j_driver["driver"]
    assert driver.verified == 1, "the official driver connectivity verification is used"
    assert [(q, m) for q, _, m in driver.log] == [("RETURN 1 AS ok", "read")]
    (uri, options), = neo4j_driver["calls"]
    assert uri == NEO4J_CONFIG["uri"] and options["auth"] == ("neo4j", SECRET) and options["connection_timeout"] == 7.0
    assert driver.sessions[0][0] == "kg"
    assert SECRET not in json.dumps(result.as_dict())


@pytest.mark.parametrize(
    "error,expected",
    [
        (AuthError(f"The client is unauthorized due to authentication failure {SECRET}"), "rejected the configured credentials"),
        (ServiceUnavailable(f"Unable to retrieve routing information for {SECRET}"), "Could not connect to the Neo4j server"),
    ],
)
def test_neo4j_failures_are_provider_specific_and_never_leak_secrets(
    neo4j_driver: dict[str, Any], error: Exception, expected: str
) -> None:
    neo4j_driver["driver"].verify_error = error
    result = check_neo4j(NEO4J_CONFIG, "NEO4J_PASSWORD")
    assert not result.ok and expected in result.message and SECRET not in result.message


def test_neo4j_unknown_database_and_missing_credentials_and_unsafe_hosts(
    neo4j_driver: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_database(query: str, params: dict[str, Any]) -> list[Any]:
        raise Neo4jError._hydrate_neo4j(code="Neo.ClientError.Database.DatabaseNotFound", message=f"x {SECRET}")

    neo4j_driver["driver"].responder = missing_database
    result = check_neo4j(NEO4J_CONFIG, "NEO4J_PASSWORD")
    assert not result.ok and "database 'kg' was not found" in result.message and SECRET not in result.message

    monkeypatch.delenv("NEO4J_PASSWORD")
    unset = check_neo4j(NEO4J_CONFIG, "NEO4J_PASSWORD")
    assert not unset.ok and "NEO4J_PASSWORD is not set" in unset.message

    monkeypatch.setenv("NEO4J_PASSWORD", SECRET)
    blocked = check_neo4j({**NEO4J_CONFIG, "uri": "neo4j+s://169.254.169.254"}, "NEO4J_PASSWORD")
    assert not blocked.ok and "not allowed" in blocked.message
    private = check_neo4j({**NEO4J_CONFIG, "uri": "bolt://localhost:7687"}, "NEO4J_PASSWORD", allow_private=False)
    assert not private.ok and "private and loopback" in private.message


def test_neo4j_store_writes_and_deletes_are_confined_to_the_build_scope(neo4j_driver: dict[str, Any]) -> None:
    store = Neo4jGraphStore.connect(PropertyTarget("neo4j", NEO4J_CONFIG, "NEO4J_PASSWORD"))
    store.replace_scope("build-1", _vertices(), _edges())
    log = neo4j_driver["driver"].log
    queries = [q for q, _, _ in log]
    deletes = [q for q in queries if "DELETE" in q]
    assert deletes and all("OlsVertex" in q and "_ols_scope: $scope" in q for q in deletes), (
        "a delete can only match nodes created by deployments, in this build's scope"
    )
    assert all(p.get("scope") == "build-1" for q, p, _ in log if "DELETE" in q)
    assert not any("MATCH (n)" in q.replace("MATCH (n:", "") for q in queries), "no unscoped match exists"
    joined = "\n".join(queries)
    assert "`Odd``Label'; drop()`" in joined and "`PLACED``BY`" in joined, "labels are escaped identifiers"
    for value in ("Acme", "EXT-1", "v1", "f1"):
        assert value not in joined, "data values never appear in query text"
    creates = [(q, p) for q, p, _ in log if "CREATE (n:" in q]
    rows = [row for _, p in creates for row in p["rows"]]
    props = next(r for r in rows if r["_ols_id"] == "v1")
    assert props["_ols_scope"] == "build-1" and props["name"] == ["Acme"]
    assert props["pk"] == ["x"], "pk is only reserved on Cosmos DB; Neo4j keeps the attribute's own name"
    assert props["_ols_fact_ids"] == ["f1"] and props["id"] == ["EXT-1"], "attributes named id keep their own key"
    edge_query = next(q for q, _, _ in log if "CREATE (a)-[r:" in q)
    assert edge_query.count("_ols_scope: $scope") == 2, "both endpoints are matched inside the scope"
    assert {m for _, _, m in log} <= {"read", "write"}


def test_neo4j_driver_is_pooled_and_credentials_are_hashed_in_the_key(neo4j_driver: dict[str, Any]) -> None:
    target = PropertyTarget("neo4j", NEO4J_CONFIG, "NEO4J_PASSWORD")
    Neo4jGraphStore.connect(target)
    Neo4jGraphStore.connect(target)
    assert len(neo4j_driver["calls"]) == 1, "one driver per connection settings"
    assert SECRET not in "".join(repr(k) for k in neo4j_store._drivers)
    neo4j_store.close_drivers()
    assert neo4j_driver["driver"].closed and not neo4j_store._drivers


# ---------------------------------------------------------------------------------- Cosmos DB Gremlin (scripted client)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> "_Result":
        return self

    def result(self) -> list[Any]:
        return self.rows


class ScriptedGremlin:
    def __init__(self, responder: Callable[[str, dict[str, Any]], list[Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responder = responder or (lambda q, b: [])
        self.closed = False

    def submit(self, query: str, bindings: dict[str, Any] | None = None) -> _Result:
        self.calls.append((query, dict(bindings or {})))
        return _Result(self.responder(query, bindings or {}))

    def submit_async(self, query: str, bindings: dict[str, Any] | None = None) -> Any:
        self.calls.append((query, dict(bindings or {})))
        rows = self.responder(query, bindings or {})
        return SimpleNamespace(result=lambda: _Result(rows))

    def close(self) -> None:
        self.closed = True


def _server_error(code: int, **attributes: Any) -> GremlinServerError:
    return GremlinServerError({"code": code, "message": f"server said {SECRET}", "attributes": attributes})


def test_cosmos_client_is_constructed_with_the_documented_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, url: str, traversal_source: str, **options: Any) -> None:
            captured.update(url=url, traversal_source=traversal_source, **options)

    from gremlin_python.driver import client as gremlin_client
    from gremlin_python.driver import serializer

    monkeypatch.setattr(gremlin_client, "Client", RecordingClient)
    monkeypatch.setenv("COSMOS_KEY", SECRET)
    settings = gremlin_store._Settings(PropertyTarget("cosmos-gremlin", COSMOS_CONFIG, "COSMOS_KEY"))
    gremlin_store._create_client(settings)
    assert captured["url"] == "wss://my-account.gremlin.cosmos.azure.com:443/" and captured["traversal_source"] == "g"
    assert captured["username"] == "/dbs/graphdb/colls/knowledge" and captured["password"] == SECRET
    assert isinstance(captured["message_serializer"], serializer.GraphSONSerializersV2d0), "Cosmos requires GraphSON 2"
    assert captured["read_timeout"] == 30.0 and settings.partition_key == "pk"
    emulator = gremlin_store._Settings(
        PropertyTarget("cosmos-gremlin", {**COSMOS_CONFIG, "endpoint": "ws://localhost", "port": "8901"}, "COSMOS_KEY")
    )
    assert emulator.url == "ws://localhost:8901/"


def test_cosmos_probe_is_a_single_read_only_traversal(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ScriptedGremlin(lambda q, b: [{"id": "v"}])
    monkeypatch.setattr(gremlin_store, "_create_client", lambda settings: client)
    monkeypatch.setenv("COSMOS_KEY", SECRET)
    result = check_cosmos(COSMOS_CONFIG, "COSMOS_KEY")
    assert result.ok and "graphdb/knowledge" in result.message
    assert [q for q, _ in client.calls] == ["g.V().limit(1)"] and client.closed


@pytest.mark.parametrize(
    "error,expected",
    [
        (_server_error(401), "rejected the account key"),
        (_server_error(404), "database or graph was not found"),
        (_server_error(429), "throttled"),
        (_server_error(503), "temporarily unavailable"),
        (OSError(f"connection refused {SECRET}"), "Could not connect"),
    ],
)
def test_cosmos_failures_are_provider_specific_and_redacted(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str
) -> None:
    def fail(query: str, bindings: dict[str, Any]) -> list[Any]:
        raise error

    monkeypatch.setattr(gremlin_store, "_create_client", lambda settings: ScriptedGremlin(fail))
    monkeypatch.setenv("COSMOS_KEY", SECRET)
    result = check_cosmos(COSMOS_CONFIG, "COSMOS_KEY")
    assert not result.ok and expected in result.message and SECRET not in result.message
    monkeypatch.delenv("COSMOS_KEY")
    assert "COSMOS_KEY is not set" in check_cosmos(COSMOS_CONFIG, "COSMOS_KEY").message


@pytest.mark.parametrize("partition_key", ["pk", "graphScope"])
def test_cosmos_store_addresses_partitions_and_never_interpolates_data(partition_key: str) -> None:
    client = ScriptedGremlin()
    store = CosmosGremlinStore(client, partition_key)
    vertices = _vertices()
    for vertex in vertices:
        vertex.properties[partition_key] = ["ontology-attribute-not-the-build-id"]
    store.replace_scope("build-1", vertices, _edges())
    queries = [q for q, _ in client.calls]
    assert queries[0].startswith(f"g.V().has('{partition_key}', s_pk).limit(100).drop()"), "clearing is partition-scoped and batched"
    vertex_calls = [(q, b) for q, b in client.calls if q.startswith("g.addV")]
    edge_calls = [(q, b) for q, b in client.calls if ".addE(" in q]
    assert len(vertex_calls) == 2 and len(edge_calls) == 1
    for query, bindings in vertex_calls:
        assert query.count(f".property('{partition_key}',") == 1
        assert f".property('{partition_key}', v_pk)" in query
        assert bindings["v_pk"] == "build-1", "every vertex carries the build id as its partition-key value"
    odd_query = next(q for q, b in vertex_calls if b["v_id"] == "v2")
    assert odd_query.startswith("g.addV('Odd_Label___drop__')"), "labels are reduced to identifier characters"
    first_query, first_bindings = next((q, b) for q, b in vertex_calls if b["v_id"] == "v1")
    assert first_bindings["v_pk"] == "build-1" and first_bindings["s_name"] == "Acme"
    assert first_query.count(".property('id', v_id)") == 1, "an attribute named id cannot replace the vertex id"
    assert f"attr_{partition_key}" in first_query, "an ontology attribute cannot overwrite the partition key"
    for value in ("Acme", "EXT-1", "build-1"):
        assert all(value not in q for q in queries), "values travel as bindings only"
    assert json.loads(first_bindings["s_props"])["name"] == ["Acme"], "multi-valued attributes are kept exactly"
    edge_query, edge_bindings = edge_calls[0]
    assert edge_query.startswith("g.V([e_pk, e_out]).addE('PLACED_BY').to(g.V([e_pk, e_in]))")
    assert edge_bindings["e_pk"] == "build-1" and edge_bindings["e_out"] == "v2" and edge_bindings["e_in"] == "v1"
    assert max(len(q) for q in queries) < 64 * 1024, "scripts stay below the 64 KB Cosmos limit"


def test_cosmos_graph_scope_configuration_reaches_writes_and_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.graph.targets.catalog import normalize_config

    config, secret_env = normalize_config(
        "cosmos-gremlin", {**COSMOS_CONFIG, "partition_key_path": "/graphScope"}, "COSMOS_KEY",
        allow_private=True,
    )
    monkeypatch.setenv("COSMOS_KEY", SECRET)
    client = ScriptedGremlin(lambda query, bindings: [0] if ".count()" in query else [])
    monkeypatch.setattr(gremlin_store, "_create_client", lambda settings: client)
    gremlin_store.close_clients()
    try:
        store = CosmosGremlinStore.connect(PropertyTarget("cosmos-gremlin", config, secret_env))
        assert store.pk == "graphScope"
        for scope in ("build-1", "build-2"):
            client.calls.clear()
            store.replace_scope(scope, _vertices(), _edges())
            assert store.counts(scope) == (0, 0)
            assert store.get_vertex(scope, "v1") is None
            vertex_calls = [(q, b) for q, b in client.calls if q.startswith("g.addV")]
            assert len(vertex_calls) == len(_vertices())
            assert all(".property('graphScope', v_pk)" in q and b["v_pk"] == scope for q, b in vertex_calls)
            for query, bindings in client.calls:
                if "s_pk" in bindings:
                    assert ".has('graphScope', s_pk)" in query and bindings["s_pk"] == scope
                if "e_pk" in bindings:
                    assert "g.V([e_pk, e_out])" in query and "g.V([e_pk, e_in])" in query
                    assert bindings["e_pk"] == scope
                if query == "g.V([v_pk, v_id])":
                    assert bindings == {"v_pk": scope, "v_id": "v1"}
    finally:
        gremlin_store.close_clients()


def test_cosmos_throttling_is_retried_with_the_service_hint() -> None:
    attempts: list[int] = []
    delays: list[float] = []

    def flaky(query: str, bindings: dict[str, Any]) -> list[Any]:
        attempts.append(1)
        if len(attempts) < 3:
            raise _server_error(429, **{"x-ms-retry-after-ms": "30"})
        return [5]

    store = CosmosGremlinStore(ScriptedGremlin(flaky), "pk", sleep=delays.append)
    assert store._run("g.V().count()") == [5]
    assert len(attempts) == 3 and delays == [0.03, 0.03]
    always = CosmosGremlinStore(ScriptedGremlin(lambda q, b: (_ for _ in ()).throw(_server_error(429))), "pk", sleep=lambda s: None)
    with pytest.raises(DeploymentError, match="throttled") as caught:
        always._run("g.V().count()")
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("partition_key", ["pk", "graphScope"])
def test_cosmos_reads_decode_documented_element_shapes(partition_key: str) -> None:
    vertex_doc = {
        "id": "v1", "label": "Supplier", "type": "vertex",
        "properties": {
            partition_key: [{"id": "a", "value": "build-1"}],
            "_ols_name": [{"id": "b", "value": "Acme"}],
            "_ols_class_id": [{"id": "c", "value": "c1"}],
            "_ols_props": [{"id": "d", "value": json.dumps({"name": ["Acme"], "tags": ["a", "b"]})}],
            "_ols_facts": [{"id": "e", "value": '["f1","f2"]'}],
            "_ols_sources": [{"id": "f", "value": '["d1"]'}],
        },
    }
    edge_doc = {
        "id": "guid", "label": "PLACED_BY", "type": "edge", "outV": "v2", "inV": "v1",
        "properties": {"_ols_id": "e1", "_ols_predicate_id": "p1", "_ols_props": '{"predicate_label": "placed by"}',
                       "_ols_facts": '["f2"]', "_ols_sources": '["d1"]'},
    }

    def respond(query: str, bindings: dict[str, Any]) -> list[Any]:
        if "count()" in query:
            return [1] if "outE" in query else [2]
        if query.startswith("g.V([v_pk, v_id]).bothE"):
            return [edge_doc, edge_doc]
        if query.startswith("g.V([v_pk, v_id])"):
            return [vertex_doc] if bindings["v_id"] == "v1" else []
        if "outE()" in query:
            return [edge_doc]
        return [vertex_doc, {**vertex_doc, "id": "v2", "properties": {**vertex_doc["properties"], "_ols_name": [{"id": "x", "value": "PO"}]}}]

    client = ScriptedGremlin(respond)
    store = CosmosGremlinStore(client, partition_key)
    vertex = store.get_vertex("build-1", "v1")
    assert vertex is not None and vertex.name == "Acme" and vertex.label == "Supplier"
    assert vertex.properties == {"name": ["Acme"], "tags": ["a", "b"]} and vertex.fact_ids == ["f1", "f2"]
    assert store.get_vertex("build-1", "missing") is None
    edges = store.edges_of("build-1", "v1")
    assert [e.id for e in edges] == ["e1"], "an edge returned from both ends is one edge"
    assert edges[0].out_id == "v2" and edges[0].in_id == "v1" and edges[0].properties == {"predicate_label": "placed by"}
    graph = store.fetch_graph("build-1", limit=10)
    assert [v.name for v in graph.vertices] == ["Acme", "PO"] and [e.id for e in graph.edges] == ["e1"] and not graph.truncated
    assert store.counts("build-1") == (2, 1)
    assert [v.id for v in store.search_vertices("build-1", "po")] == ["v2"]
    assert store.provenance("build-1", "v1") == ["f1", "f2"]
    assert store.get_edge("build-1", "e1") is not None
    for query, bindings in client.calls:
        if "s_pk" in bindings:
            assert f".has('{partition_key}', s_pk)" in query and bindings["s_pk"] == "build-1"
        if "v_pk" in bindings:
            assert query.startswith("g.V([v_pk, v_id])") and bindings["v_pk"] == "build-1"
    with pytest.raises(DeploymentError, match="unexpected vertex shape"):
        CosmosGremlinStore(ScriptedGremlin(lambda q, b: ["not-a-document"]), "pk").get_vertex("s", "v")
