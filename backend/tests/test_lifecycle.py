"""Project Lifecycle Navigator: iterations and stage statuses derived from real records."""

from datetime import datetime
from pathlib import Path
from typing import Any

from alembic import command
from fastapi.testclient import TestClient

from app.db.migrations import alembic_config, upgrade_database
from app.main import create_app
from tests.conftest import ONTOLOGY_PAYLOAD, add_class, error_code, make_settings
from tests.kg_helpers import SME, publish, run_build, setup_kg, upload

STAGE_KEYS = ["sources", "discovery", "review", "validation", "publication", "mapping", "kg_build", "deployment", "evaluation"]


def _lifecycle(client: TestClient, project_id: str, iteration_id: str | None = None) -> dict[str, Any]:
    response = client.get(f"/api/projects/{project_id}/lifecycle", params={"iteration_id": iteration_id} if iteration_id else {})
    assert response.status_code == 200, response.text
    return response.json()


def _status(lifecycle: dict[str, Any]) -> dict[str, str]:
    return {s["key"]: s["status"] for s in lifecycle["iteration"]["stages"]}


def _stage(lifecycle: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in lifecycle["iteration"]["stages"] if s["key"] == key)


def _start(client: TestClient, project_id: str, stage: str, **body: Any) -> Any:
    return client.post(f"/api/projects/{project_id}/iterations", json={"start_stage": stage, "created_by": SME, **body})


def test_new_project_starts_iteration_one_with_everything_pending(client: TestClient) -> None:
    project = client.post("/api/projects", json={"name": "Fresh", "initial_ontology": ONTOLOGY_PAYLOAD}).json()
    lifecycle = _lifecycle(client, project["id"])
    assert [s["key"] for s in lifecycle["stages"]] == STAGE_KEYS
    assert len(lifecycle["iterations"]) == 1
    iteration = lifecycle["iteration"]
    assert iteration["number"] == 1 and iteration["status"] == "active" and iteration["start_stage"] == "sources"
    assert iteration["frozen"] is False
    status = _status(lifecycle)
    assert status["discovery"] == "blocked", "no LLM is configured in tests"
    assert "No LLM" in _stage(lifecycle, "discovery")["summary"]
    assert {k for k, v in status.items() if v != "pending"} == {"discovery"}
    assert "Waits for publication" in _stage(lifecycle, "kg_build")["summary"]
    options = {o["stage"]: o for o in lifecycle["start_options"]}
    assert options["sources"]["allowed"] and options["validation"]["allowed"]
    assert not options["kg_build"]["allowed"] and "No published ontology version" in options["kg_build"]["reason"]
    refused = _start(client, project["id"], "kg_build")
    assert refused.status_code == 422 and error_code(refused) == "ITERATION_START_UNAVAILABLE"


def test_statuses_follow_the_real_records_through_a_kg_iteration(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    project_id = env["project"]["id"]
    lifecycle = _lifecycle(seeded_client, project_id)
    status = _status(lifecycle)
    assert status["sources"] == "completed" and "4 source(s) added" in _stage(lifecycle, "sources")["summary"]
    assert status["publication"] == "completed" and "v1.0.0" in _stage(lifecycle, "publication")["summary"]
    assert status["mapping"] == "completed"
    assert status["kg_build"] == "pending" and "Ready to build with v1.0.0" in _stage(lifecycle, "kg_build")["summary"]
    assert status["deployment"] == "pending" and status["evaluation"] == "pending"

    build = run_build(env)
    lifecycle = _lifecycle(seeded_client, project_id)
    status = _status(lifecycle)
    assert status["kg_build"] == "completed"
    summary = _stage(lifecycle, "kg_build")["summary"]
    nodes = build["stats"]["graph"]["nodes"]
    assert f"Build #{build['number']}" in summary and f"{nodes} nodes" in summary
    assert _stage(lifecycle, "kg_build")["link"] == {"area": "knowledge-graph", "tab": "pipeline", "build_id": build["id"]}
    assert status["deployment"] == "completed" and "Local SQL property graph" in _stage(lifecycle, "deployment")["summary"]
    assert status["evaluation"] in ("completed", "in_progress", "pending")

    # A new source makes the build (and what is derived from it) outdated.
    upload(seeded_client, project_id, "extra.csv", b"id,name\n1,x\n")
    lifecycle = _lifecycle(seeded_client, project_id)
    status = _status(lifecycle)
    assert status["kg_build"] == "outdated" and "1 source(s) uploaded after build" in _stage(lifecycle, "kg_build")["summary"]
    assert status["deployment"] == "outdated"
    assert status["mapping"] == "in_progress", "the new structured source has no mapping"

    # Changing the draft makes the publication outdated; a new version outdates mappings and the build.
    add_class(seeded_client, env["ontology"]["id"], "Distribution Hub")
    lifecycle = _lifecycle(seeded_client, project_id)
    assert _status(lifecycle)["publication"] == "outdated"
    publish(seeded_client, env["ontology"]["id"], "1.1.0")
    lifecycle = _lifecycle(seeded_client, project_id)
    status = _status(lifecycle)
    assert status["publication"] == "completed"
    assert "built with v1.0.0; v1.1.0 is published" in _stage(lifecycle, "kg_build")["summary"]


def test_new_iteration_from_an_intermediate_stage_reuses_outputs_and_freezes_history(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    project_id = env["project"]["id"]
    first_build = run_build(env)
    before = _lifecycle(seeded_client, project_id)
    first = before["iteration"]
    option = next(o for o in before["start_options"] if o["stage"] == "kg_build")
    assert option["allowed"] and any(r.startswith("Publication: published v1.0.0") for r in option["reuses"])

    started = _start(seeded_client, project_id, "kg_build", name="Rebuild with new data", goal="Refresh the graph")
    assert started.status_code == 201, started.text
    lifecycle = started.json()
    iteration = lifecycle["iteration"]
    assert iteration["number"] == 2 and iteration["status"] == "active" and iteration["base_iteration_number"] == 1
    assert iteration["name"] == "Rebuild with new data" and iteration["start_stage"] == "kg_build"
    status = _status(lifecycle)
    for key in ("sources", "validation", "publication", "mapping"):
        assert status[key] == "reused", (key, status)
        reused = _stage(lifecycle, key)["reused"]
        assert reused and reused["from_iteration"] == 1
    assert _stage(lifecycle, "publication")["reused"]["refs"]["version"] == "1.0.0"
    assert status["kg_build"] == "pending" and status["deployment"] == "pending" and status["evaluation"] == "pending"

    # The first iteration is closed and frozen exactly as it ended.
    summaries = {i["number"]: i for i in lifecycle["iterations"]}
    assert summaries[1]["status"] == "closed" and summaries[1]["closed_at"]
    frozen = _lifecycle(seeded_client, project_id, first["id"])
    assert frozen["iteration"]["frozen"] is True
    assert _status(frozen) == _status(before)

    second_build = run_build(env)
    lifecycle = _lifecycle(seeded_client, project_id)
    status = _status(lifecycle)
    assert status["kg_build"] == "completed" and f"Build #{second_build['number']}" in _stage(lifecycle, "kg_build")["summary"]
    assert status["deployment"] == "completed"
    assert _status(_lifecycle(seeded_client, project_id, first["id"])) == _status(before), "history does not change"
    assert f"Build #{first_build['number']}" in _stage(frozen, "kg_build")["summary"]

    activity = seeded_client.get(f"/api/projects/{project_id}/activity").json()
    assert any(e["event_type"] == "iteration.started" and "iteration #2 at KG build" in e["summary"] for e in activity)


def test_mappings_are_current_again_once_a_build_rechecks_them_against_the_new_version(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    project_id = env["project"]["id"]
    run_build(env)
    add_class(seeded_client, env["ontology"]["id"], "Distribution Hub")
    newer = publish(seeded_client, env["ontology"]["id"], "1.1.0")
    lifecycle = _lifecycle(seeded_client, project_id)
    assert _stage(lifecycle, "mapping")["status"] == "outdated"
    assert "older version than v1.1.0" in _stage(lifecycle, "mapping")["summary"]
    assert _stage(lifecycle, "kg_build")["status"] == "outdated"
    run_build(env, version_id=newer["id"])
    status = _status(_lifecycle(seeded_client, project_id))
    assert status["mapping"] == "completed" and status["kg_build"] == "completed"


def test_reused_build_can_start_a_deployment_iteration(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    project_id = env["project"]["id"]
    build = run_build(env)
    lifecycle = _start(seeded_client, project_id, "deployment").json()
    status = _status(lifecycle)
    assert status["kg_build"] == "reused" and _stage(lifecycle, "kg_build")["link"]["build_id"] == build["id"]
    assert status["deployment"] == "pending", "deployments of the reused build from iteration 1 do not count"
    deployed = seeded_client.post(
        f"/api/kg/builds/{build['id']}/deployments", json={"target_id": "oxigraph-embedded", "requested_by": SME}
    ).json()
    assert deployed["status"] == "completed"
    lifecycle = _lifecycle(seeded_client, project_id)
    assert _status(lifecycle)["deployment"] == "completed"
    assert "verified in Embedded Oxigraph" in _stage(lifecycle, "deployment")["summary"]


def test_failures_and_gates_block_stages(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    project_id = env["project"]["id"]
    target = seeded_client.post(
        "/api/settings/graph-connections",
        json={"name": "Query only", "kind": "sparql-http", "config": {"query_url": "http://127.0.0.1:9/query"}},
    ).json()
    run_build(env, graph_connection_id=target["id"])
    lifecycle = _lifecycle(seeded_client, project_id)
    deployment = _stage(lifecycle, "deployment")
    assert deployment["status"] == "blocked" and "query-only" in deployment["summary"]

    ontology_id = env["ontology"]["id"]
    broken = seeded_client.patch(f"/api/ontologies/{ontology_id}", json={"namespace": "https://example.com/onto"})
    assert broken.status_code == 200, broken.text
    report = seeded_client.post(f"/api/ontologies/{ontology_id}/validations").json()
    assert report["error_count"] > 0
    lifecycle = _lifecycle(seeded_client, project_id)
    validation = _stage(lifecycle, "validation")
    assert validation["status"] == "blocked" and "must be fixed before publication" in validation["summary"]
    publication = _stage(lifecycle, "publication")
    assert publication["status"] == "outdated", "v1.0.0 exists but the draft changed"


def test_migration_creates_iteration_one_for_existing_projects(db_path: Path) -> None:
    settings = make_settings(db_path, seed=True)
    with TestClient(create_app(settings)) as client:
        project = client.get("/api/projects").json()[0]
    command.downgrade(alembic_config(settings.database_url), "0007")
    upgrade_database(settings.database_url)
    with TestClient(create_app(settings)) as client:
        lifecycle = _lifecycle(client, project["id"])
        assert [i["number"] for i in lifecycle["iterations"]] == [1]
        iteration = lifecycle["iteration"]
        assert iteration["start_stage"] == "sources" and iteration["status"] == "active"
        assert all(stage["reused"] is None for stage in iteration["stages"]), "nothing is reused in iteration 1"
        assert datetime.fromisoformat(iteration["started_at"]) == datetime.fromisoformat(project["created_at"])
        assert _status(lifecycle)["validation"] in ("completed", "pending")
