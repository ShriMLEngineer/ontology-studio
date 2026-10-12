"""Live Neo4j (for example AuraDB) integration: a real KG build is deployed, read back and cleaned up.

Skipped unless ``OLS_LIVE_NEO4J_URI`` is set. Variables:

* ``OLS_LIVE_NEO4J_URI``       e.g. neo4j+s://xxxxxxxx.databases.neo4j.io
* ``OLS_LIVE_NEO4J_PASSWORD``  the password (read from the environment; never stored by the application)
* ``OLS_LIVE_NEO4J_USERNAME``  default ``neo4j``
* ``OLS_LIVE_NEO4J_DATABASE``  default ``neo4j``

The test only ever touches the build's own scope (nodes labelled ``OlsVertex`` whose ``_ols_scope`` is the
build id) and verifies that every other node and relationship in the database is unchanged.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from neo4j import GraphDatabase

from app.modules.graph.targets import neo4j_store
from tests.kg_helpers import run_build, setup_kg
from tests.test_graph_deployments import _deploy, _graph, _shape

URI = os.environ.get("OLS_LIVE_NEO4J_URI", "")
USERNAME = os.environ.get("OLS_LIVE_NEO4J_USERNAME", "neo4j")
DATABASE = os.environ.get("OLS_LIVE_NEO4J_DATABASE", "neo4j")

pytestmark = pytest.mark.skipif(not URI, reason="OLS_LIVE_NEO4J_URI is not set; live Neo4j verification skipped.")


@pytest.fixture
def raw_session() -> Iterator[object]:
    password = os.environ["OLS_LIVE_NEO4J_PASSWORD"]
    with GraphDatabase.driver(URI, auth=(USERNAME, password)) as driver, driver.session(database=DATABASE) as session:
        yield session
    neo4j_store.close_drivers()


def _totals(session: object) -> tuple[int, int]:
    nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]  # type: ignore[attr-defined]
    relationships = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]  # type: ignore[attr-defined]
    return int(nodes), int(relationships)


def test_live_neo4j_connection_deployment_readback_and_scoped_cleanup(seeded_client: TestClient, raw_session: object) -> None:
    before = _totals(raw_session)
    env = setup_kg(seeded_client)
    build = run_build(env)
    created = seeded_client.post(
        "/api/settings/graph-connections",
        json={
            "name": "Live Aura", "kind": "neo4j", "secret_env": "OLS_LIVE_NEO4J_PASSWORD",
            "config": {"uri": URI, "database": DATABASE, "username": USERNAME, "timeout_seconds": 30},
        },
    )
    assert created.status_code == 201, created.text
    connection = created.json()
    scope = build["id"]
    try:
        tested = seeded_client.post(f"/api/settings/graph-connections/{connection['id']}/test").json()
        assert tested["status"] == "connected", tested["last_test"]
        assert before == _totals(raw_session), "the connection test changed nothing"

        response = _deploy(seeded_client, build["id"], connection["id"])
        assert response.status_code == 201, response.text
        deployment = response.json()
        assert deployment["status"] == "completed", deployment["error"]
        assert deployment["stats"]["expected"] == deployment["stats"]["verified"]

        # what the database holds, asked directly with the driver (outside the application)
        nodes = raw_session.run(  # type: ignore[attr-defined]
            "MATCH (n:OlsVertex {_ols_scope: $s}) RETURN count(n) AS c", s=scope
        ).single()["c"]
        relationships = raw_session.run(  # type: ignore[attr-defined]
            "MATCH (:OlsVertex {_ols_scope: $s})-[r {_ols_scope: $s}]->() RETURN count(r) AS c", s=scope
        ).single()["c"]
        assert nodes == build["stats"]["graph"]["nodes"] and relationships == build["stats"]["graph"]["edges"]
        assert _totals(raw_session) == (before[0] + nodes, before[1] + relationships)

        # adapter-independent exploration through the live target
        assert _shape(_graph(seeded_client, build["id"], deployment["id"])) == _shape(_graph(seeded_client, build["id"]))

        again = _deploy(seeded_client, build["id"], connection["id"]).json()
        assert again["status"] == "completed" and _totals(raw_session) == (before[0] + nodes, before[1] + relationships), (
            "redeploying replaces the scope instead of duplicating it"
        )
    finally:
        raw_session.run(  # type: ignore[attr-defined]
            "MATCH (n:OlsVertex {_ols_scope: $s}) DETACH DELETE n", s=scope
        ).consume()
    assert _totals(raw_session) == before, "cleanup removed only the test scope; all other data is unchanged"
