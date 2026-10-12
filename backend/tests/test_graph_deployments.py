"""Phase 4.4/4.5: graph projections, deployments, compatibility reports and the SPARQL console.

Every deployment test writes to a real store: the embedded Oxigraph (pyoxigraph) or an Oxigraph
SPARQL 1.1 server started as a subprocess (``oxigraph serve``; skipped if the binary is missing).
"""

import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from alembic import command
from fastapi.testclient import TestClient
from rdflib.compare import isomorphic

from app.db.migrations import alembic_config, upgrade_database
from app.main import create_app
from app.modules.graph import compatibility
from app.modules.graph.capabilities import MAPPING_PROFILES, PROFILES
from app.modules.graph.memory_store import MemoryGraphStore
from app.modules.graph.projection import project_rdf
from app.modules.graph.sparql import check_read_only
from app.modules.kg.deployments import load_projection
from app.modules.kg.models import KgBuild
from tests.conftest import error_code, make_settings
from tests.kg_helpers import SME, run_build, setup_kg

OXIGRAPH = "oxigraph-embedded"


def _deployments(client: TestClient, build_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/kg/builds/{build_id}/deployments")
    assert response.status_code == 200, response.text
    return response.json()


def _deploy(client: TestClient, build_id: str, target_id: str, **body: Any) -> Any:
    return client.post(f"/api/kg/builds/{build_id}/deployments", json={"target_id": target_id, "requested_by": SME, **body})


def _graph(client: TestClient, build_id: str, deployment_id: str | None = None) -> dict[str, Any]:
    params = {"limit": 5000, **({"deployment_id": deployment_id} if deployment_id else {})}
    response = client.get(f"/api/kg/builds/{build_id}/graph", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _shape(graph: dict[str, Any]) -> tuple[Any, ...]:
    nodes = sorted(
        (n["id"], n["label"], n["name"], n["class_id"], n["identifier"], tuple(sorted(n["source_ids"])), n["fact_count"])
        for n in graph["nodes"]
    )
    edges = sorted(
        (e["id"], e["source"], e["target"], e["predicate_id"], tuple(sorted(e["source_ids"])), e["fact_count"])
        for e in graph["edges"]
    )
    return nodes, edges, graph["total_nodes"], graph["total_edges"]


def _query(client: TestClient, deployment_id: str, query: str) -> Any:
    return client.post(f"/api/kg/deployments/{deployment_id}/query", json={"query": query})


# ---------------------------------------------------------------------------------- builds deploy


def test_build_records_canonical_graph_and_deploys_to_selected_oxigraph(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env, graph_connection_id=OXIGRAPH)
    rows = _deployments(seeded_client, build["id"])
    by_kind = {r["target_kind"]: r for r in rows}
    assert set(by_kind) == {"local-sql", "oxigraph"}

    canonical = by_kind["local-sql"]
    assert canonical["status"] == "completed" and canonical["origin"] == "build"
    assert canonical["stats"]["expected"] == canonical["stats"]["verified"]
    assert canonical["stats"]["verified"] == {"vertices": build["stats"]["graph"]["nodes"], "edges": build["stats"]["graph"]["edges"]}
    assert canonical["queryable"] is False and canonical["explorable"] is True

    rdf = by_kind["oxigraph"]
    assert rdf["status"] == "completed", rdf["error"]
    assert rdf["mapping_profile"] == "rdf-default/1" and rdf["capability_profile"] == "oxigraph/1"
    assert set(rdf["graphs"]) == {"data", "provenance", "ontology"}
    assert rdf["graphs"]["data"].endswith(f"build/{build['id']}")
    assert rdf["stats"]["expected"] == rdf["stats"]["verified"] and rdf["stats"]["triples"] > 0
    assert rdf["data_namespace"] == build["stats"]["shacl"]["data_namespace"]
    assert rdf["compatibility"]["has_semantic_loss"] is False

    stage = next(s for s in build["stages"] if s["key"] == "graph_persistence")
    assert "Deployed to Embedded Oxigraph" in stage["summary"]
    assert [d["status"] for d in build["stats"]["graph"]["deployments"]] == ["completed", "completed"]


def test_explorer_reads_back_from_oxigraph_with_parity(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env, graph_connection_id=OXIGRAPH)
    deployment = next(r for r in _deployments(seeded_client, build["id"]) if r["target_kind"] == "oxigraph")

    canonical, deployed = _graph(seeded_client, build["id"]), _graph(seeded_client, build["id"], deployment["id"])
    assert deployed["deployment_id"] == deployment["id"] and deployed["graph_store"] == "oxigraph"
    assert deployed["read_warnings"] == []
    assert _shape(deployed) == _shape(canonical)
    assert [c["count"] for c in deployed["classes"]] == [c["count"] for c in canonical["classes"]]
    canonical_props = {n["id"]: {p["key"] for p in n["properties"]} for n in canonical["nodes"]}
    assert {n["id"]: {p["key"] for p in n["properties"]} for n in deployed["nodes"]} == canonical_props

    node = canonical["nodes"][0]
    for path in (f"graph/elements/{node['id']}", f"graph/nodes/{node['id']}/neighborhood"):
        a = seeded_client.get(f"/api/kg/builds/{build['id']}/{path}").json()
        b = seeded_client.get(f"/api/kg/builds/{build['id']}/{path}", params={"deployment_id": deployment["id"]}).json()
        if "facts" in a:  # provenance is restored in canonical order
            assert [f["id"] for f in b["facts"]] == [f["id"] for f in a["facts"]]
            assert sorted(e["id"] for e in b["relationships"]) == sorted(e["id"] for e in a["relationships"])
            assert b["deployment_id"] == deployment["id"]
        else:
            assert _shape(b)[:2] == _shape(a)[:2]
    edge = canonical["edges"][0]
    a = seeded_client.get(f"/api/kg/builds/{build['id']}/graph/elements/{edge['id']}").json()
    b = seeded_client.get(
        f"/api/kg/builds/{build['id']}/graph/elements/{edge['id']}", params={"deployment_id": deployment["id"]}
    ).json()
    assert b["kind"] == "edge" and [f["id"] for f in b["facts"]] == [f["id"] for f in a["facts"]]
    term = node["name"][:3].lower()
    search = [n["id"] for n in seeded_client.get(f"/api/kg/builds/{build['id']}/graph/search", params={"q": term}).json()]
    remote = seeded_client.get(
        f"/api/kg/builds/{build['id']}/graph/search", params={"q": term, "deployment_id": deployment["id"]}
    ).json()
    assert [n["id"] for n in remote] == search and search


def test_redeploy_is_idempotent_and_supersedes(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env, graph_connection_id=OXIGRAPH)
    first = next(r for r in _deployments(seeded_client, build["id"]) if r["target_kind"] == "oxigraph")
    second = _deploy(seeded_client, build["id"], OXIGRAPH)
    assert second.status_code == 201, second.text
    again = second.json()
    assert again["status"] == "completed" and again["origin"] == "manual" and again["requested_by"] == SME
    assert again["stats"]["verified"] == first["stats"]["verified"], "re-deployment replaces the build's graphs"
    statuses = {r["id"]: r["status"] for r in _deployments(seeded_client, build["id"])}
    assert statuses[first["id"]] == "superseded" and statuses[again["id"]] == "completed"
    old = seeded_client.get(f"/api/kg/builds/{build['id']}/graph", params={"deployment_id": first["id"]})
    assert old.status_code == 409 and error_code(old) == "DEPLOYMENT_NOT_READABLE"


def test_rdf_projection_is_deterministic(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env)
    session_factory = seeded_client.app.state.session_factory  # type: ignore[attr-defined]
    with session_factory() as session:
        row = session.get(KgBuild, build["id"])
        assert row is not None
        snapshot, first = load_projection(session, row)
        _, second = load_projection(session, row)
    namespace = build["stats"]["shacl"]["data_namespace"]
    a, b = project_rdf(first, snapshot, namespace, build["id"]), project_rdf(second, snapshot, namespace, build["id"])
    assert set(a.data) == set(b.data) and set(a.provenance) == set(b.provenance)
    assert isomorphic(a.ontology, b.ontology)
    assert len(a.data) > 0 and len(first.vertices) == build["stats"]["graph"]["nodes"]


# ---------------------------------------------------------------------------------- SPARQL console


def test_sparql_console_is_read_only_and_scoped_to_the_build(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env, graph_connection_id=OXIGRAPH)
    rows = {r["target_kind"]: r for r in _deployments(seeded_client, build["id"])}
    deployment = rows["oxigraph"]

    counted = _query(seeded_client, deployment["id"], "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a ?c }")
    assert counted.status_code == 200, counted.text
    result = counted.json()
    assert result["form"] == "select" and result["default_graph"] == deployment["graphs"]["data"]
    assert int(result["rows"][0]["n"]["value"]) == build["stats"]["graph"]["nodes"]

    ask = _query(seeded_client, deployment["id"], "ASK { ?s ?p ?o }").json()
    assert ask["form"] == "ask" and ask["boolean"] is True
    construct = _query(seeded_client, deployment["id"], "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 5").json()
    assert construct["variables"] == ["subject", "predicate", "object"] and len(construct["rows"]) == 5
    provenance = _query(
        seeded_client,
        deployment["id"],
        "PREFIX ols: <urn:ols:vocab#> SELECT (COUNT(?r) AS ?n) WHERE { GRAPH ?g { ?r a ols:Relationship } }",
    ).json()
    assert int(provenance["rows"][0]["n"]["value"]) == build["stats"]["graph"]["edges"]

    for rejected in (
        "INSERT DATA { <urn:a> <urn:b> <urn:c> }",
        "DROP ALL",
        "SELECT * WHERE { SERVICE <http://example.org/sparql> { ?s ?p ?o } }",
        "SELECT * WHERE { ?s ?p }",
    ):
        response = _query(seeded_client, deployment["id"], rejected)
        assert response.status_code == 422 and error_code(response) == "SPARQL_QUERY_REJECTED", rejected
    local = _query(seeded_client, rows["local-sql"]["id"], "ASK { ?s ?p ?o }")
    assert local.status_code == 422 and error_code(local) == "QUERY_NOT_SUPPORTED"


def test_read_only_check_classifies_query_forms() -> None:
    assert check_read_only("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1") == "select"
    assert check_read_only("ASK { ?s ?p ?o }") == "ask"
    assert check_read_only("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }") == "construct"
    assert check_read_only("DESCRIBE <urn:x>") == "describe"
    for update in ("DELETE WHERE { ?s ?p ?o }", "LOAD <http://x>", "CLEAR ALL", "  "):
        with pytest.raises(Exception, match="."):
            check_read_only(update)


# ---------------------------------------------------------------------------------- compatibility


def test_compatibility_reports_per_target_and_mapping(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env)
    url = f"/api/kg/builds/{build['id']}/compatibility"

    local = seeded_client.get(url, params={"target_id": "local-sql"}).json()
    rows = {r["feature"]: r for r in local["report"]["rows"]}
    assert local["adapter_available"] and local["report"]["capability_profile_verified"]
    assert rows["Typed attribute values"]["outcome"] == "transformed"
    assert rows["Class hierarchy (rdfs:subClassOf)"]["outcome"] == "partial"
    assert rows["Class membership"]["affected"] == build["stats"]["graph"]["nodes"]

    rdf = seeded_client.get(url, params={"target_id": OXIGRAPH}).json()["report"]
    rdf_rows = {r["feature"]: r for r in rdf["rows"]}
    assert rdf_rows["Class hierarchy (rdfs:subClassOf)"]["outcome"] == "native"
    assert rdf_rows["Lexical form of typed values"]["outcome"] == "transformed"
    assert rdf["has_semantic_loss"] is False and rdf["mapping_profile"] == "rdf-default/1"

    data_only = seeded_client.get(url, params={"target_id": OXIGRAPH, "mapping_profile": "rdf-data-only/1"}).json()
    assert {r["feature"]: r for r in data_only["report"]["rows"]}["Class hierarchy (rdfs:subClassOf)"]["outcome"] == "partial"
    deployed = _deploy(seeded_client, build["id"], OXIGRAPH, mapping_profile="rdf-data-only/1").json()
    assert deployed["status"] == "completed" and set(deployed["graphs"]) == {"data", "provenance"}

    neo4j = seeded_client.get(url, params={"kind": "neo4j"}).json()
    assert neo4j["adapter_available"] is True and neo4j["report"]["capability_profile_verified"] is True, (
        "the Neo4j adapter was verified against a live Neo4j AuraDB instance"
    )
    cosmos = seeded_client.get(url, params={"kind": "cosmos-gremlin"}).json()
    assert cosmos["adapter_available"] is True and cosmos["report"]["capability_profile_verified"] is False, (
        "Cosmos DB has an adapter but was never run against a live account, and the report says so"
    )

    wrong = seeded_client.get(url, params={"target_id": OXIGRAPH, "mapping_profile": "lpg-default/1"})
    assert wrong.status_code == 422 and error_code(wrong) == "MAPPING_PROFILE_INCOMPATIBLE"
    assert _deploy(seeded_client, build["id"], "neo4j").status_code == 404, "a provider id is not a registered target"

    catalogue = seeded_client.get("/api/kg/graph-capabilities").json()
    assert {p["target_kind"] for p in catalogue["profiles"]} == set(PROFILES)
    assert {m["id"] for m in catalogue["mapping_profiles"]} == set(MAPPING_PROFILES)
    assert all(p["adapter_available"] for p in catalogue["profiles"])


def test_semantic_loss_requires_acknowledgement(seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env)
    real = compatibility.data_features

    def with_language_tags(projection: Any) -> dict[str, int]:
        return {**real(projection), "language_tagged_values": 3}

    monkeypatch.setattr(compatibility, "data_features", with_language_tags)
    report = seeded_client.get(f"/api/kg/builds/{build['id']}/compatibility", params={"target_id": "local-sql"}).json()
    assert report["report"]["has_semantic_loss"] is True
    loss = next(r for r in report["report"]["rows"] if r["outcome"] == "semantic_loss")
    assert loss["feature"] == "Language-tagged values" and loss["affected"] == 3

    refused = _deploy(seeded_client, build["id"], "local-sql")
    assert refused.status_code == 422 and error_code(refused) == "SEMANTIC_LOSS_NOT_ACKNOWLEDGED"
    accepted = _deploy(seeded_client, build["id"], "local-sql", acknowledge_semantic_loss=True)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["acknowledged_loss_by"] == SME and accepted.json()["status"] == "completed"


def test_deploying_requires_a_completed_build(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    created = seeded_client.post(
        f"/api/projects/{env['project']['id']}/kg/builds",
        json={
            "ontology_version_id": env["version"]["id"],
            "source_document_ids": [d["id"] for d in env["documents"].values()],
            "mapping_ids": [m["id"] for m in env["mappings"].values()],
            "requested_by": SME,
            "start": False,
        },
    ).json()
    response = _deploy(seeded_client, created["id"], OXIGRAPH)
    assert response.status_code == 409 and error_code(response) == "KG_BUILD_NOT_COMPLETED"


# ---------------------------------------------------------------------------------- SPARQL 1.1 endpoint


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _oxigraph_binary() -> str | None:
    local = Path(sys.executable).parent / ("oxigraph.exe" if sys.platform == "win32" else "oxigraph")
    return str(local) if local.exists() else shutil.which("oxigraph")


@pytest.fixture
def sparql_server(tmp_path: Path) -> Iterator[tuple[str, subprocess.Popen[bytes]]]:
    binary = _oxigraph_binary()
    if binary is None:
        pytest.skip("The oxigraph server binary is not installed (pip install oxigraph).")
    port = _free_port()
    process = subprocess.Popen(
        [binary, "serve", "--location", str(tmp_path / "server-store"), "--bind", f"127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while True:
        try:
            if httpx2.get(f"{base}/query", params={"query": "ASK {}"}, timeout=1).status_code < 500:
                break
        except httpx2.HTTPError:
            pass
        if time.monotonic() > deadline or process.poll() is not None:
            process.kill()
            pytest.fail("oxigraph serve did not start")
        time.sleep(0.2)
    yield base, process
    process.kill()
    process.wait(timeout=10)


def test_sparql_http_endpoint_deploy_read_back_query_and_outage(
    seeded_client: TestClient, sparql_server: tuple[str, subprocess.Popen[bytes]]
) -> None:
    base, process = sparql_server
    env = setup_kg(seeded_client)
    connection = seeded_client.post(
        "/api/settings/graph-connections",
        json={"name": "Oxigraph server", "kind": "sparql-http", "config": {"query_url": f"{base}/query", "update_url": f"{base}/update"}},
    ).json()
    assert seeded_client.post(f"/api/settings/graph-connections/{connection['id']}/test").json()["last_test"]["ok"] is True

    build = run_build(env, graph_connection_id=connection["id"])
    deployment = next(r for r in _deployments(seeded_client, build["id"]) if r["target_kind"] == "sparql-http")
    assert deployment["status"] == "completed", deployment["error"]
    assert deployment["stats"]["expected"] == deployment["stats"]["verified"]
    assert deployment["target_name"] == "Oxigraph server" and deployment["queryable"]

    # The server really holds the graphs: ask it directly, outside the application.
    direct = httpx2.post(
        f"{base}/query",
        data={"query": f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{deployment['graphs']['data']}> {{ ?s ?p ?o }} }}"},
        headers={"Accept": "application/sparql-results+json"},
    ).json()
    assert int(direct["results"]["bindings"][0]["n"]["value"]) == deployment["stats"]["verified"]["data"]

    assert _shape(_graph(seeded_client, build["id"], deployment["id"])) == _shape(_graph(seeded_client, build["id"]))
    counted = _query(seeded_client, deployment["id"], "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a ?c }").json()
    assert int(counted["rows"][0]["n"]["value"]) == build["stats"]["graph"]["nodes"]

    process.kill()
    process.wait(timeout=10)
    down = _query(seeded_client, deployment["id"], "ASK { ?s ?p ?o }")
    assert down.status_code == 503 and error_code(down) == "GRAPH_TARGET_UNREACHABLE"
    failed = _deploy(seeded_client, build["id"], connection["id"])
    assert failed.status_code == 201 and failed.json()["status"] == "failed"
    assert "unreachable" in failed.json()["error"]


def test_failing_target_never_fails_the_build(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    query_only = seeded_client.post(
        "/api/settings/graph-connections",
        json={"name": "Read only", "kind": "sparql-http", "config": {"query_url": "http://127.0.0.1:9/query"}},
    ).json()
    build = run_build(env, graph_connection_id=query_only["id"])
    rows = {r["target_kind"]: r for r in _deployments(seeded_client, build["id"])}
    assert rows["local-sql"]["status"] == "completed"
    assert rows["sparql-http"]["status"] == "failed" and "query-only" in rows["sparql-http"]["error"]
    logs = seeded_client.get(f"/api/kg/builds/{build['id']}/logs").json()
    assert any(log["level"] == "warning" and "Deployment to Read only failed" in log["message"] for log in logs)
    assert _graph(seeded_client, build["id"])["total_nodes"] == build["stats"]["graph"]["nodes"]


# ---------------------------------------------------------------------------------- migration & read model


def test_migration_records_legacy_local_graphs(db_path: Path) -> None:
    settings = make_settings(db_path, seed=True)
    with TestClient(create_app(settings)) as client:
        build = run_build(setup_kg(client))
        nodes, edges = build["stats"]["graph"]["nodes"], build["stats"]["graph"]["edges"]
    command.downgrade(alembic_config(settings.database_url), "0006")  # as if the build predates Phase 4.4
    upgrade_database(settings.database_url)
    with TestClient(create_app(settings)) as client:
        rows = _deployments(client, build["id"])
        assert len(rows) == 1
        legacy = rows[0]
        assert legacy["origin"] == "legacy" and legacy["status"] == "completed" and legacy["target_kind"] == "local-sql"
        assert legacy["stats"]["verified"] == {"vertices": nodes, "edges": edges}
        assert legacy["compatibility"] is None and legacy["explorable"]
        assert _graph(client, build["id"], legacy["id"])["total_nodes"] == nodes
        # Legacy builds can be deployed to RDF targets afterwards.
        deployed = _deploy(client, build["id"], OXIGRAPH).json()
        assert deployed["status"] == "completed" and deployed["data_namespace"] == build["stats"]["shacl"]["data_namespace"]


def test_memory_store_rejects_writes_and_scopes_reads() -> None:
    store = MemoryGraphStore("x", "g1", [], [])
    with pytest.raises(RuntimeError):
        store.upsert_vertices("g1", [])
    assert store.counts("other") == (0, 0) and store.fetch_graph("other", limit=5).vertices == []
