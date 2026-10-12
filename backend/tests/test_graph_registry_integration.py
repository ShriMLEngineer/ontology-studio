"""Registered graph databases end to end: connection tests, KG deployment routing, adapter-independent
exploration, historical isolation, credential redaction and migration 0010."""

import json
import subprocess
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import AuthError
from sqlalchemy import create_engine, text

from app.db.migrations import upgrade_database
from app.modules.graph.memory_store import MemoryGraphStore
from app.modules.graph.store import GraphEdge, GraphVertex
from app.modules.graph.targets import adapters
from app.modules.graph.targets.errors import DeploymentError
from app.modules.graph.targets.property_graph import PropertyTarget, ReadableGraphStore
from app.modules.kg import deployments
from app.modules.kg.models import KgBuild
from tests.conftest import error_code
from tests.kg_helpers import run_build, setup_kg
from tests.test_external_stores import FakeDriver, ScriptedGremlin, neo4j_driver  # noqa: F401
from tests.test_graph_deployments import (
    _deploy,
    _deployments,
    _graph,
    _shape,
    sparql_server,  # noqa: F401
)

SECRET = "graph-secret-value-1234"
URL = "/api/settings/graph-connections"
NEO4J_A = {"uri": "neo4j+s://a.databases.neo4j.io", "database": "neo4j", "username": "neo4j"}
NEO4J_B = {"uri": "neo4j+s://b.databases.neo4j.io", "database": "neo4j", "username": "neo4j"}


def _register(client: TestClient, name: str, kind: str, config: dict[str, Any], secret_env: str | None = None) -> dict[str, Any]:
    response = client.post(URL, json={"name": name, "kind": kind, "config": config, "secret_env": secret_env})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _test(client: TestClient, connection_id: str) -> dict[str, Any]:
    response = client.post(f"{URL}/{connection_id}/test")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------------- SPARQL-family connection tests


class _Recorder(BaseHTTPRequestHandler):
    requests: ClassVar[list[tuple[str, str | None]]] = []
    required_auth: ClassVar[str | None] = None

    def log_message(self, *_: Any) -> None:
        return None

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        auth = self.headers.get("Authorization")
        type(self).requests.append((self.path, auth))
        required = type(self).required_auth
        if required is not None and auth != required:
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({"head": {}, "boolean": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/sparql-results+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def recorder() -> Iterator[tuple[str, type[_Recorder]]]:
    _Recorder.requests = []
    _Recorder.required_auth = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", _Recorder
    server.shutdown()


def test_graphdb_connection_test_uses_the_derived_endpoint_and_is_read_only(
    client: TestClient, recorder: tuple[str, type[_Recorder]]
) -> None:
    base, handler = recorder
    row = _register(client, "GraphDB", "graphdb", {"server_url": base, "repository_id": "kg"})
    tested = _test(client, row["id"])
    assert tested["status"] == "connected" and tested["last_test"]["ok"] is True
    assert "Update endpoint configured" in tested["last_test"]["message"]
    assert handler.requests == [("/repositories/kg", None)], "one ASK against {server}/repositories/{id}; nothing else"
    assert tested["capabilities"]["connected"] and tested["capabilities"]["deployment_ready"]
    assert tested["capabilities"]["deployment_verified"] is False, "connected is not the same as verified"
    assert tested["last_test"]["tested_at"] and tested["last_test"]["latency_ms"] >= 0


@pytest.mark.parametrize(
    "kind,config,auth_type,header",
    [
        ("fuseki", "FUSEKI", "bearer", "Bearer TOKEN"),
        ("graphdb", "GRAPHDB", "gdb-token", "GDB TOKEN"),
        ("sparql-http", "GENERIC", "bearer", "Bearer TOKEN"),
    ],
)
def test_sparql_authentication_schemes_and_credential_failures(
    client: TestClient, recorder: tuple[str, type[_Recorder]], monkeypatch: pytest.MonkeyPatch,
    kind: str, config: str, auth_type: str, header: str,
) -> None:
    base, handler = recorder
    endpoints = {
        "FUSEKI": {"query_url": f"{base}/ds/query", "update_url": f"{base}/ds/update"},
        "GRAPHDB": {"server_url": base, "repository_id": "kg"},
        "GENERIC": {"query_url": f"{base}/sparql"},
    }[config]
    handler.required_auth = header
    row = _register(client, f"{kind} auth", kind, {**endpoints, "auth_type": auth_type}, "GRAPH_TOKEN")

    unset = _test(client, row["id"])
    assert unset["status"] == "failed" and "GRAPH_TOKEN is not set" in unset["last_test"]["message"]
    assert handler.requests == [], "no request is sent without the credential"

    monkeypatch.setenv("GRAPH_TOKEN", "WRONG")
    rejected = _test(client, row["id"])
    assert rejected["status"] == "failed" and "rejected the credentials" in rejected["last_test"]["message"]
    assert "WRONG" not in json.dumps(rejected)

    monkeypatch.setenv("GRAPH_TOKEN", "TOKEN")
    accepted = _test(client, row["id"])
    assert accepted["status"] == "connected" and handler.requests[-1][1] == header


def test_basic_authentication_and_unreachable_and_missing_endpoints(
    client: TestClient, recorder: tuple[str, type[_Recorder]], monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64

    base, handler = recorder
    handler.required_auth = "Basic " + base64.b64encode(b"reader:pw").decode()
    monkeypatch.setenv("FUSEKI_PW", "pw")
    row = _register(client, "Basic", "fuseki", {"query_url": f"{base}/q", "auth_type": "basic", "username": "reader"}, "FUSEKI_PW")
    assert _test(client, row["id"])["status"] == "connected"

    down = _register(client, "Down", "fuseki", {"query_url": "http://127.0.0.1:9/q"})
    failed = _test(client, down["id"])
    assert failed["status"] == "failed" and "unreachable" in failed["last_test"]["message"]
    assert failed["capabilities"]["connected"] is False and failed["capabilities"]["deployment_ready"] is False
    handler.required_auth = None
    gone = _register(client, "Wrong repository", "graphdb", {"server_url": base, "repository_id": "kg"})
    assert _test(client, gone["id"])["status"] == "connected"


def test_connection_test_refuses_names_resolving_to_metadata_addresses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import net_safety

    monkeypatch.setattr(net_safety, "resolve_host", lambda host, port: [(2, 1, 6, "", ("169.254.169.254", port))])
    row = _register(client, "Looks fine", "fuseki", {"query_url": "https://innocent.example.com/ds/query"})
    result = _test(client, row["id"])
    assert result["status"] == "failed" and "resolves to an address" in result["last_test"]["message"]


# ---------------------------------------------------------------------------------- Neo4j and Cosmos tests through the API


def test_neo4j_test_through_the_api_updates_status_and_resets_when_the_connection_changes(
    client: TestClient, neo4j_driver: dict[str, Any], monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    monkeypatch.setenv("NEO4J_PASSWORD", SECRET)
    row = _register(client, "Aura", "neo4j", NEO4J_A, "NEO4J_PASSWORD")
    ok = _test(client, row["id"])
    assert ok["status"] == "connected" and "Neo4j/5.27-fake" in ok["last_test"]["message"]
    assert ok["capabilities"]["deployment_ready"] is True and SECRET not in json.dumps(ok)

    edited = client.put(
        f"{URL}/{row['id']}", json={"name": "Aura", "kind": "neo4j", "config": NEO4J_B, "secret_env": "NEO4J_PASSWORD"}
    ).json()
    assert edited["status"] == "not_tested" and edited["capabilities"]["deployment_ready"] is False

    neo4j_driver["driver"].verify_error = AuthError(f"bad {SECRET}")
    bad = _test(client, row["id"])
    assert bad["status"] == "failed" and "rejected the configured credentials" in bad["last_test"]["message"]
    assert SECRET not in json.dumps(bad)


def test_cosmos_test_through_the_api(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.graph.targets import gremlin_store

    scripted = ScriptedGremlin(lambda q, b: [{"id": "x"}])
    monkeypatch.setattr(gremlin_store, "_create_client", lambda settings: scripted)
    monkeypatch.setenv("COSMOS_KEY", SECRET)
    row = _register(
        client, "Cosmos", "cosmos-gremlin",
        {"endpoint": "acct", "database": "db", "graph": "g", "partition_key_path": "/pk"}, "COSMOS_KEY",
    )
    assert row["config"]["endpoint"] == "acct.gremlin.cosmos.azure.com" and row["config"]["port"] == "443"
    tested = _test(client, row["id"])
    assert tested["status"] == "connected" and [q for q, _ in scripted.calls] == ["g.V().limit(1)"]
    assert tested["capabilities"]["live_tested"] is False, "the registry states Cosmos was never run against a live account"


# ---------------------------------------------------------------------------------- KG deployment routing


class FakeServer:
    """An in-memory external property-graph database shared by every store the adapters create."""

    def __init__(self) -> None:
        self.scopes: dict[str, MemoryGraphStore] = {}
        self.targets: list[PropertyTarget] = []
        self.unreachable = False
        self.reject_with: str | None = None


class FakeStore(ReadableGraphStore):
    name = "fake-neo4j"

    def __init__(self, server: FakeServer) -> None:
        self.server = server

    def _check(self) -> None:
        if self.server.unreachable:
            raise DeploymentError("Could not connect to the fake server.")

    def _mem(self, scope: str) -> MemoryGraphStore:
        self._check()
        return self.server.scopes.get(scope) or MemoryGraphStore("fake", scope, [], [])

    def replace_scope(self, scope: str, vertices: Any, edges: Any) -> None:
        self._check()
        if self.server.reject_with:
            raise DeploymentError(self.server.reject_with)
        self.server.scopes[scope] = MemoryGraphStore("fake", scope, vertices, edges)

    def clear_scope(self, scope: str) -> None:
        self.server.scopes.pop(scope, None)

    def counts(self, graph_id: str) -> tuple[int, int]:
        mem = self._mem(graph_id)
        return len(mem.vertices), len(mem.edges)

    def get_vertex(self, graph_id: str, vertex_id: str) -> GraphVertex | None:
        return self._mem(graph_id).get_vertex(graph_id, vertex_id)

    def get_edge(self, graph_id: str, edge_id: str) -> GraphEdge | None:
        return self._mem(graph_id).get_edge(graph_id, edge_id)

    def edges_of(self, graph_id: str, vertex_id: str) -> list[GraphEdge]:
        return self._mem(graph_id).edges_of(graph_id, vertex_id)

    def fetch_graph(self, graph_id: str, *, limit: int) -> Any:
        return self._mem(graph_id).fetch_graph(graph_id, limit=limit)

    def search_vertices(self, graph_id: str, text: str, *, label: str | None = None, limit: int = 20) -> list[GraphVertex]:
        return self._mem(graph_id).search_vertices(graph_id, text, label=label, limit=limit)


@pytest.fixture
def graph_server(monkeypatch: pytest.MonkeyPatch) -> FakeServer:
    server = FakeServer()

    def factory(target: PropertyTarget) -> FakeStore:
        server.targets.append(target)
        if server.unreachable:
            raise DeploymentError("Could not connect to the fake server.")
        return FakeStore(server)

    monkeypatch.setattr(adapters, "property_graph_store", factory)
    monkeypatch.setattr(deployments, "property_graph_store", factory)
    monkeypatch.setenv("NEO4J_PASSWORD", SECRET)
    return server


def test_build_deploys_to_a_registered_property_graph_and_the_explorer_reads_that_target(
    seeded_client: TestClient, graph_server: FakeServer
) -> None:
    env = setup_kg(seeded_client)
    connection = _register(seeded_client, "Aura", "neo4j", NEO4J_A, "NEO4J_PASSWORD")
    build = run_build(env)
    canonical = _graph(seeded_client, build["id"])
    extraction_before = json.dumps(build["stats"], sort_keys=True, default=str)

    deployment = _deploy(seeded_client, build["id"], connection["id"])
    assert deployment.status_code == 201, deployment.text
    row = deployment.json()
    assert row["status"] == "completed" and row["data_model"] == "property-graph" and row["target_kind"] == "neo4j"
    assert row["stats"]["expected"] == row["stats"]["verified"] and row["graphs"]["graph_id"] == build["id"]
    assert row["graphs"]["database"] == "neo4j" and row["capability_profile"] == "neo4j/2"
    assert row["compatibility"]["capability_profile_verified"] is True and row["explorable"] and not row["queryable"]
    assert build["id"] in graph_server.scopes, "the target holds the build's scope"
    assert json.dumps(_deployments(seeded_client, build["id"])[-1]["stats"], sort_keys=True)  # recorded

    # adapter-independent exploration: same graph, read through the external store
    assert _shape(_graph(seeded_client, build["id"], row["id"])) == _shape(canonical)
    first = canonical["nodes"][0]["id"]
    assert _shape(_graph(seeded_client, build["id"])) == _shape(canonical)
    neighbours = seeded_client.get(
        f"/api/kg/builds/{build['id']}/graph/nodes/{first}/neighborhood", params={"deployment_id": row["id"]}
    )
    local = seeded_client.get(f"/api/kg/builds/{build['id']}/graph/nodes/{first}/neighborhood")
    assert neighbours.status_code == 200 and _shape(neighbours.json()) == _shape(local.json())
    found = seeded_client.get(
        f"/api/kg/builds/{build['id']}/graph/search", params={"q": canonical["nodes"][0]["name"][:3], "deployment_id": row["id"]}
    )
    assert found.status_code == 200 and found.json()
    detail = seeded_client.get(
        f"/api/kg/builds/{build['id']}/graph/elements/{first}", params={"deployment_id": row["id"]}
    )
    assert detail.status_code == 200 and detail.json()["facts"], "provenance resolves through the external target"

    # the explorer reads what the target holds - it never silently falls back to the local store
    vertex = graph_server.scopes[build["id"]].vertices.pop(first)
    reduced = _graph(seeded_client, build["id"], row["id"])
    assert first not in {n["id"] for n in reduced["nodes"]} and first in {n["id"] for n in canonical["nodes"]}
    graph_server.scopes[build["id"]].vertices[first] = vertex

    # the connection now reports verified deployment support
    after = seeded_client.get(f"{URL}/{connection['id']}").json()
    assert after["deployment_count"] == 1 and after["capabilities"]["deployment_verified"] is True
    assert after["capabilities"]["last_deployment_at"]
    assert json.dumps(build["stats"], sort_keys=True, default=str) == extraction_before, "no re-extraction took place"


def test_one_completed_build_deploys_to_several_targets_without_reextraction(
    seeded_client: TestClient, graph_server: FakeServer, sparql_server: tuple[str, subprocess.Popen[bytes]]  # noqa: F811
) -> None:
    base, _ = sparql_server
    env = setup_kg(seeded_client)
    build = run_build(env)
    llm_calls_before = len(seeded_client.get(f"/api/kg/builds/{build['id']}/logs").json())
    neo4j = _register(seeded_client, "Aura", "neo4j", NEO4J_A, "NEO4J_PASSWORD")
    graphdb = _register(
        seeded_client, "GraphDB (Oxigraph server)", "graphdb",
        {"server_url": base, "repository_id": "kg", "query_url": f"{base}/query", "update_url": f"{base}/update"},
    )
    fuseki = _register(seeded_client, "Fuseki (Oxigraph server)", "fuseki", {"query_url": f"{base}/query", "update_url": f"{base}/update"})
    generic = _register(seeded_client, "Generic", "sparql-http", {"query_url": f"{base}/query", "update_url": f"{base}/update"})
    local_copy = _register(seeded_client, "Local copy", "local-sql", {})
    assert _test(seeded_client, graphdb["id"])["status"] == "connected", "tested against a live SPARQL 1.1 server"

    rows = {}
    for connection in (neo4j, graphdb, fuseki, generic, local_copy):
        response = _deploy(seeded_client, build["id"], connection["id"])
        assert response.status_code == 201, response.text
        rows[connection["name"]] = response.json()
        assert rows[connection["name"]]["status"] == "completed", rows[connection["name"]]["error"]
    assert {r["target_kind"] for r in rows.values()} == {"neo4j", "graphdb", "fuseki", "sparql-http", "local-sql"}
    assert rows["Aura"]["data_model"] == "property-graph" and rows["Fuseki (Oxigraph server)"]["data_model"] == "rdf"

    canonical = _shape(_graph(seeded_client, build["id"]))
    for row in rows.values():
        assert _shape(_graph(seeded_client, build["id"], row["id"])) == canonical, row["target_kind"]
    assert len(seeded_client.get(f"/api/kg/builds/{build['id']}/logs").json()) == llm_calls_before, "no extraction reran"
    counted = seeded_client.post(
        f"/api/kg/deployments/{rows['GraphDB (Oxigraph server)']['id']}/query",
        json={"query": "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a ?c }"},
    ).json()
    assert int(counted["rows"][0]["n"]["value"]) == build["stats"]["graph"]["nodes"]
    refused = seeded_client.post(
        f"/api/kg/deployments/{rows['Aura']['id']}/query", json={"query": "ASK { ?s ?p ?o }"}
    )
    assert refused.status_code == 422 and error_code(refused) == "QUERY_NOT_SUPPORTED", "no universal query language"
    verified = {c["name"]: c["capabilities"]["deployment_verified"] for c in seeded_client.get(URL).json() if not c["builtin"]}
    assert all(verified.values())


def test_build_auto_deploys_to_the_selected_registered_target(seeded_client: TestClient, graph_server: FakeServer) -> None:
    env = setup_kg(seeded_client)
    connection = _register(seeded_client, "Aura", "neo4j", NEO4J_A, "NEO4J_PASSWORD")
    build = run_build(env, graph_connection_id=connection["id"])
    rows = {r["target_id"]: r for r in _deployments(seeded_client, build["id"])}
    assert rows[connection["id"]]["status"] == "completed" and rows[connection["id"]]["origin"] == "build"
    logs = seeded_client.get(f"/api/kg/builds/{build['id']}/logs").json()
    assert any("Deployed to Aura (neo4j)" in log["message"] and "vertices" in log["message"] for log in logs)
    with seeded_client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        snapshot = session.get(KgBuild, build["id"]).config_snapshot
    assert snapshot["graph_target"]["provider"] == "neo4j", "the build records the target it used"
    assert snapshot["graph_target"]["secret_env"] == "NEO4J_PASSWORD"
    assert SECRET not in json.dumps(snapshot) and SECRET not in json.dumps(build)


def test_unreachable_database_fails_only_the_deployment_never_falls_back_silently(
    seeded_client: TestClient, graph_server: FakeServer
) -> None:
    env = setup_kg(seeded_client)
    connection = _register(seeded_client, "Aura", "neo4j", NEO4J_A, "NEO4J_PASSWORD")
    build = run_build(env)
    ok = _deploy(seeded_client, build["id"], connection["id"]).json()
    assert ok["status"] == "completed"

    graph_server.unreachable = True
    unreadable = seeded_client.get(f"/api/kg/builds/{build['id']}/graph", params={"deployment_id": ok["id"]})
    assert unreadable.status_code == 409 and error_code(unreadable) == "GRAPH_TARGET_UNREACHABLE"
    failed = _deploy(seeded_client, build["id"], connection["id"]).json()
    assert failed["status"] == "failed" and "Could not connect" in failed["error"] and failed["explorable"] is False
    not_readable = seeded_client.get(f"/api/kg/builds/{build['id']}/graph", params={"deployment_id": failed["id"]})
    assert not_readable.status_code == 409 and error_code(not_readable) == "DEPLOYMENT_NOT_READABLE"
    assert _graph(seeded_client, build["id"])["total_nodes"] == build["stats"]["graph"]["nodes"], "the canonical graph is intact"
    after = seeded_client.get(f"{URL}/{connection['id']}").json()
    assert after["deployment_count"] == 2 and after["capabilities"]["deployment_verified"] is True


def test_failed_deployment_errors_never_persist_the_credential(seeded_client: TestClient, graph_server: FakeServer) -> None:
    env = setup_kg(seeded_client)
    connection = _register(seeded_client, "Aura", "neo4j", NEO4J_A, "NEO4J_PASSWORD")
    build = run_build(env)
    graph_server.reject_with = f"Neo4j said: invalid credentials {SECRET} for user"
    failed = _deploy(seeded_client, build["id"], connection["id"]).json()
    assert failed["status"] == "failed" and "***" in failed["error"] and SECRET not in failed["error"]
    assert SECRET not in json.dumps(_deployments(seeded_client, build["id"]))


def test_disabled_registrations_cannot_receive_new_deployments_but_history_stays_readable(
    seeded_client: TestClient, graph_server: FakeServer
) -> None:
    env = setup_kg(seeded_client)
    connection = _register(seeded_client, "Aura", "neo4j", NEO4J_A, "NEO4J_PASSWORD")
    build = run_build(env)
    done = _deploy(seeded_client, build["id"], connection["id"]).json()
    assert seeded_client.post(f"{URL}/{connection['id']}/activation", json={"enabled": False}).status_code == 200
    refused = _deploy(seeded_client, build["id"], connection["id"])
    assert refused.status_code == 422 and error_code(refused) == "GRAPH_CONNECTION_DISABLED"
    assert _graph(seeded_client, build["id"], done["id"])["nodes"], "history of a disabled target stays readable"
    selecting = seeded_client.post(
        f"/api/projects/{build['project_id']}/kg/builds",
        json={"ontology_version_id": build["ontology_version_id"], "sources": [], "settings": {"graph_connection_id": connection["id"]}},
    )
    assert selecting.status_code in (404, 405, 409, 422), "a disabled target is not selectable for a build"


def test_editing_or_deleting_a_registration_never_redirects_historical_deployments(
    seeded_client: TestClient, graph_server: FakeServer
) -> None:
    env = setup_kg(seeded_client)
    connection = _register(seeded_client, "Aura", "neo4j", NEO4J_A, "NEO4J_PASSWORD")
    build = run_build(env)
    old = _deploy(seeded_client, build["id"], connection["id"]).json()
    assert seeded_client.get(f"{URL}/{connection['id']}").json()["config"]["uri"] == NEO4J_A["uri"]

    body = {"name": "Aura", "kind": "neo4j", "config": NEO4J_B, "secret_env": "NEO4J_PASSWORD"}
    assert seeded_client.put(f"{URL}/{connection['id']}", json=body).status_code == 200
    graph_server.targets.clear()
    _graph(seeded_client, build["id"], old["id"])
    assert graph_server.targets[-1].config["uri"] == NEO4J_A["uri"], "reads use the settings the deployment was written with"
    new = _deploy(seeded_client, build["id"], connection["id"]).json()
    assert graph_server.targets[-1].config["uri"] == NEO4J_B["uri"], "new deployments use the edited registration"
    assert new["id"] != old["id"]
    listed = {r["id"]: r for r in _deployments(seeded_client, build["id"])}
    assert listed[new["id"]]["target_name"] == "Aura" and listed[old["id"]]["target_name"] == "Aura"
    assert listed[old["id"]]["status"] == "superseded" and listed[new["id"]]["status"] == "completed"

    assert seeded_client.delete(f"{URL}/{connection['id']}").status_code == 204
    graph_server.targets.clear()
    assert _graph(seeded_client, build["id"], new["id"])["nodes"], "history survives deleting the registration"


def test_local_sql_remains_the_canonical_graph_and_needs_no_external_database(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env)
    rows = _deployments(seeded_client, build["id"])
    assert [r["target_kind"] for r in rows] == ["local-sql"] and rows[0]["status"] == "completed"
    assert _graph(seeded_client, build["id"])["total_nodes"] == build["stats"]["graph"]["nodes"]
    again = _deploy(seeded_client, build["id"], "local-sql")
    assert again.status_code == 201 and again.json()["status"] == "completed"
    assert again.json()["graphs"] == {"graph_id": build["id"]}


# ---------------------------------------------------------------------------------- migration 0010


def _deployment_insert(deployment_id: str, target_id: str) -> str:
    return (
        "INSERT INTO kg_graph_deployments (id, build_id, project_id, target_id, target_name, target_kind, data_model, "
        "mapping_profile, capability_profile, graphs, status, stats, origin, requested_by, created_at) VALUES "
        f"('{deployment_id}', 'build-x', 'project-x', '{target_id}', 'T', 'sparql-http', 'rdf', 'rdf-default/1', "
        "'sparql-http/1', '{}', 'completed', '{}', 'manual', '', '2026-10-01')"
    )


def test_migration_0010_preserves_registrations_and_snapshots_historical_targets(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'graph-migration.db').as_posix()}"
    upgrade_database(url, "0009")
    engine = create_engine(url)
    config = json.dumps({"query_url": "http://localhost:3030/ds/query", "update_url": "http://localhost:3030/ds/update"})
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO graph_connections (id, name, kind, config, secret_env, description, last_test, updated_by, "
            "created_at, updated_at) VALUES ('g1', 'Legacy SPARQL', 'sparql-http', :config, 'OLS_SPARQL_PASSWORD', "
            "'legacy', NULL, '', '2026-10-01', '2026-10-01')"
        ), {"config": config})
        connection.execute(text(_deployment_insert("d1", "g1")))
        connection.execute(text(_deployment_insert("d2", "local-sql")))
    upgrade_database(url)
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT kind, config, secret_env, data_model, enabled, is_default FROM graph_connections WHERE id='g1'"
        )).one()
        snapshots = dict(connection.execute(text("SELECT id, target_snapshot FROM kg_graph_deployments")).all())
        history = connection.execute(text("SELECT target_name, status FROM kg_graph_deployments WHERE id='d1'")).one()
    assert row[0] == "sparql-http" and json.loads(row[1]) == json.loads(config) and row[2] == "OLS_SPARQL_PASSWORD"
    assert row[3:] == ("rdf", 1, 0), "legacy registrations are RDF, enabled and not the default"
    recorded = json.loads(snapshots["d1"])
    assert recorded["provider"] == "sparql-http" and recorded["config"]["query_url"].endswith("/ds/query")
    assert recorded["secret_env"] == "OLS_SPARQL_PASSWORD", "only the variable name is recorded"
    assert set(recorded) == {"provider", "config", "secret_env", "origin"} and set(recorded["config"]) == {"query_url", "update_url"}
    assert snapshots["d2"] is None, "built-in targets need no snapshot"
    assert history == ("T", "completed"), "historical deployments are untouched"
    engine.dispose()


def test_migration_0010_recovers_from_an_interrupted_attempt(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'graph-partial.db').as_posix()}"
    upgrade_database(url, "0009")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE graph_connections ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 1"))
        connection.execute(text("CREATE TABLE _alembic_tmp_graph_connections (id VARCHAR(36))"))
    upgrade_database(url)
    with engine.connect() as connection:
        columns = {r[1] for r in connection.execute(text("PRAGMA table_info(graph_connections)"))}
        tables = {r[0] for r in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"data_model", "enabled", "is_default"} <= columns and "_alembic_tmp_graph_connections" not in tables
    engine.dispose()
