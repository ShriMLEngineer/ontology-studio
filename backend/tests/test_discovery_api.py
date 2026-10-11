from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.llm.provider import LLMOutputError, LLMTransportError
from tests.conftest import error_code, make_settings, start_run
from tests.fakes import ScriptedLLMProvider


def test_discovery_requires_a_configured_llm(client: TestClient) -> None:
    project = client.post("/api/projects", json={"name": "P", "initial_ontology": {
        "name": "O", "namespace": "https://example.com/o#", "prefix": "o", "description": ""}}).json()
    ontology = client.get(f"/api/projects/{project['id']}/ontologies").json()[0]
    response = client.post(f"/api/ontologies/{ontology['id']}/discovery-runs", json={"document_ids": ["x"]})
    assert response.status_code == 503
    assert error_code(response) == "LLM_NOT_CONFIGURED"


def test_discovery_run_produces_grounded_aligned_proposals(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    response = start_run(studio, instructions="Focus on inventory and compliance.")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"

    run = client.get(f"/api/discovery-runs/{response.json()['id']}").json()
    assert run["status"] == "completed", run["error"]
    assert run["baseline_label"] == f"draft revision {studio['ontology']['draft_revision']}"
    assert run["documents"] == [{"id": studio["document"]["id"], "filename": "handbook.md"}]
    assert run["progress"]["completed_batches"] == run["progress"]["total_batches"] == 1
    assert run["usage"] == {"prompt_tokens": 120, "completion_tokens": 60}
    assert run["stats"]["findings"] == 10
    assert run["stats"]["by_type"] == {"add": 4, "reuse": 1, "alias": 1, "modify": 1, "conflict": 1}
    reasons = {d["term"]: d["reason"] for d in run["discarded"]}
    assert "could not be located" in reasons["customs broker"]
    assert "does not exist in the baseline" in reasons["pallet"]

    prompt = studio["provider"].calls[0]
    assert "[cls-supplier] Supplier" in prompt["user"] and "SME FOCUS" in prompt["user"]
    assert '<chunk id="C1" document="handbook.md">' in prompt["user"]

    proposals = client.get(f"/api/ontologies/{studio['ontology']['id']}/proposals").json()
    assert len(proposals) == 8 and {p["status"] for p in proposals} == {"pending"}
    titles = {p["title"] for p in proposals}
    assert "Reuse existing class 'Supplier'" in titles
    assert "Add alias 'Haulier' to class 'Carrier'" in titles
    assert "Resolve conflict on relationship 'supplies'" in titles

    held_at = next(p for p in proposals if p["title"] == "Add relationship 'held at'")
    detail = client.get(f"/api/proposals/{held_at['id']}").json()
    lot = next(p for p in proposals if p["title"] == "Add class 'Inventory Lot'")
    assert detail["depends_on"] == [lot["id"]]
    assert detail["new_element"]["range_id"] == "cls-warehouse"
    assert detail["evidence"][0]["verified"] is True
    assert detail["evidence"][0]["quote"] == "Inventory lots are held at a warehouse"
    assert detail["evidence"][0]["document_name"] == "handbook.md"
    assert detail["llm_output"]["domain"] == "Inventory Lot"
    assert detail["events"][0]["event_type"] == "created" and detail["events"][0]["actor"] == "AI discovery"
    assert detail["impact"]["applicable"] is True, "dependencies are applied first when assessing impact"

    stats = client.get(f"/api/ontologies/{studio['ontology']['id']}/proposals/stats").json()
    assert stats["total"] == 8 and stats["awaiting_review"] == 8

    draft = client.get(f"/api/ontologies/{studio['ontology']['id']}/draft").json()
    assert draft["draft_revision"] == studio["ontology"]["draft_revision"], "discovery never changes the draft"


def test_transport_failure_marks_run_failed_without_proposals(studio: dict[str, Any]) -> None:
    studio["client"].app.state.llm_provider = ScriptedLLMProvider([LLMTransportError("connection refused")])
    run = start_run(studio).json()
    run = studio["client"].get(f"/api/discovery-runs/{run['id']}").json()
    assert run["status"] == "failed" and "connection refused" in run["error"]
    assert studio["client"].get(f"/api/ontologies/{studio['ontology']['id']}/proposals").json() == []


def test_invalid_output_for_every_batch_fails_the_run(studio: dict[str, Any]) -> None:
    studio["client"].app.state.llm_provider = ScriptedLLMProvider([LLMOutputError("bad json")])
    run = start_run(studio).json()
    run = studio["client"].get(f"/api/discovery-runs/{run['id']}").json()
    assert run["status"] == "failed" and "invalid output" in run["error"]


def test_documents_must_belong_to_the_project(studio: dict[str, Any]) -> None:
    response = studio["client"].post(
        f"/api/ontologies/{studio['ontology']['id']}/discovery-runs", json={"document_ids": ["not-a-document"]}
    )
    assert response.status_code == 422 and error_code(response) == "SOURCE_NOT_IN_PROJECT"


def test_only_one_active_run_per_ontology(studio: dict[str, Any]) -> None:
    from app.modules.discovery.models import DiscoveryRun

    session_factory = studio["client"].app.state.session_factory
    with session_factory() as session:
        session.add(
            DiscoveryRun(
                ontology_id=studio["ontology"]["id"], baseline_kind="draft", baseline_label="draft", document_ids=[],
                status="running", provider="p", model="m", prompt_version="v",
            )
        )
        session.commit()
    response = start_run(studio)
    assert response.status_code == 409 and error_code(response) == "DISCOVERY_RUN_IN_PROGRESS"


def test_interrupted_runs_are_marked_failed_on_startup(db_path: Path) -> None:
    from app.modules.discovery.models import DiscoveryRun

    with TestClient(create_app(make_settings(db_path, seed=True))) as client:
        ontology_id = client.get(f"/api/projects/{client.get('/api/projects').json()[0]['id']}/ontologies").json()[0]["id"]
        with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
            session.add(DiscoveryRun(
                id="stale", ontology_id=ontology_id, baseline_kind="draft", baseline_label="draft",
                document_ids=[], status="running", provider="p", model="m", prompt_version="v",
            ))
            session.commit()
    with TestClient(create_app(make_settings(db_path))) as client:
        run = client.get("/api/discovery-runs/stale").json()
    assert run["status"] == "failed" and "Interrupted" in run["error"]
