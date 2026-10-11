from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import error_code, start_run

SME = "Dana SME"


def _proposals(studio: dict[str, Any]) -> dict[str, dict[str, Any]]:
    client: TestClient = studio["client"]
    start_run(studio)
    return {p["title"]: p for p in client.get(f"/api/ontologies/{studio['ontology']['id']}/proposals").json()}


def _decide(client: TestClient, proposal_id: str, decision: str, comment: str = "") -> Any:
    return client.post(
        f"/api/proposals/{proposal_id}/decision", json={"decision": decision, "actor": SME, "comment": comment}
    )


def test_review_workflow_persists_decisions_and_comments(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    proposals = _proposals(studio)
    certificate = proposals["Add class 'Certificate of Insurance'"]

    comment = client.post(f"/api/proposals/{certificate['id']}/comments", json={"actor": SME, "body": "Check with legal."})
    assert comment.status_code == 201

    missing_comment = _decide(client, certificate["id"], "reject")
    assert missing_comment.status_code == 422 and error_code(missing_comment) == "COMMENT_REQUIRED"

    refinement = _decide(client, certificate["id"], "request_refinement", "Name it 'Insurance Certificate'.")
    assert refinement.json()["status"] == "needs_refinement"

    edited = client.patch(
        f"/api/proposals/{certificate['id']}",
        json={
            "actor": SME,
            "comment": "Renamed per legal",
            "new_element": {**refinement.json()["new_element"], "label": "Insurance Certificate", "local_name": "InsuranceCertificate"},
        },
    ).json()
    assert edited["status"] == "pending" and edited["edited"] is True
    assert edited["title"] == "Add class 'Insurance Certificate'"
    assert edited["llm_output"]["label"] == "Certificate of Insurance", "original LLM output is preserved"

    approved = _decide(client, certificate["id"], "approve", "Looks right.").json()
    assert approved["status"] == "approved"
    assert [e["event_type"] for e in approved["events"]] == [
        "created", "commented", "refinement_requested", "edited", "approved",
    ]
    assert all(e["actor"] == SME for e in approved["events"][1:])

    invalid = _decide(client, certificate["id"], "approve")
    assert invalid.status_code == 409 and error_code(invalid) == "INVALID_PROPOSAL_TRANSITION"

    rejected = _decide(client, proposals["Resolve conflict on relationship 'supplies'"]["id"], "reject", "Out of scope.")
    assert rejected.json()["status"] == "rejected"
    reopened = _decide(client, rejected.json()["id"], "reopen", "Reconsider later.")
    assert reopened.json()["status"] == "pending"

    stats = client.get(f"/api/ontologies/{studio['ontology']['id']}/proposals/stats").json()
    assert stats["by_status"]["approved"] == 1 and stats["approved_not_applied"] == 1


def test_apply_approved_updates_draft_in_dependency_order(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    ontology_id = studio["ontology"]["id"]
    start_revision = studio["ontology"]["draft_revision"]
    proposals = _proposals(studio)
    titles = [
        "Add relationship 'held at'",
        "Add attribute 'lot number'",
        "Add class 'Inventory Lot'",
        "Add alias 'Haulier' to class 'Carrier'",
        "Modify class 'Shipment'",
        "Reuse existing class 'Supplier'",
    ]
    for title in titles:
        response = _decide(client, proposals[title]["id"], "approve")
        assert response.status_code == 200, (title, response.text)

    result = client.post(f"/api/ontologies/{ontology_id}/proposals/apply", json={"actor": SME}).json()
    assert result["failed"] == []
    assert len(result["applied"]) == 6
    assert result["revision_incremented"] is True and result["draft_revision"] == start_revision + 1
    assert result["changes"]["classes"] == {"added": 1, "updated": 2, "removed": 0}
    assert result["changes"]["object_properties"]["added"] == 1
    assert result["changes"]["datatype_properties"]["added"] == 1

    draft = client.get(f"/api/ontologies/{ontology_id}/draft").json()
    lot = next(c for c in draft["classes"] if c["label"] == "Inventory Lot")
    held_at = next(p for p in draft["object_properties"] if p["label"] == "held at")
    assert held_at["domain_id"] == lot["id"] and held_at["range_id"] == "cls-warehouse"
    assert "Haulier" in next(c for c in draft["classes"] if c["id"] == "cls-carrier")["aliases"]
    assert "receiving facility" in next(c for c in draft["classes"] if c["id"] == "cls-shipment")["description"]
    assert lot["id"] in draft["layout"]["positions"]

    lot_id = proposals["Add class 'Inventory Lot'"]["id"]
    applied = client.get(f"/api/proposals/{lot_id}").json()
    assert applied["status"] == "applied" and applied["applied_draft_revision"] == start_revision + 1
    assert applied["events"][-1]["event_type"] == "applied"

    report = client.post(f"/api/ontologies/{ontology_id}/validations").json()
    assert report["is_valid"] is True

    activity = client.get(f"/api/projects/{studio['project']['id']}/activity?limit=3").json()
    assert any(e["event_type"] == "ontology.proposals_applied" for e in activity)

    nothing = client.post(f"/api/ontologies/{ontology_id}/proposals/apply", json={"actor": SME})
    assert nothing.status_code == 422 and error_code(nothing) == "NOTHING_TO_APPLY"


def test_dependent_proposal_cannot_apply_without_its_dependency(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    proposals = _proposals(studio)
    _decide(client, proposals["Add class 'Inventory Lot'"]["id"], "reject", "Not now.")
    held_at_id = proposals["Add relationship 'held at'"]["id"]
    detail = client.get(f"/api/proposals/{held_at_id}").json()
    assert detail["impact"]["applicable"] is False and "rejected" in detail["impact"]["reason"]
    blocked = _decide(client, detail["id"], "approve")
    assert blocked.status_code == 422 and error_code(blocked) == "PROPOSAL_NOT_APPLICABLE"


def test_approval_is_blocked_when_it_would_introduce_validation_errors(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    proposals = _proposals(studio)
    certificate = proposals["Add class 'Certificate of Insurance'"]
    detail = client.get(f"/api/proposals/{certificate['id']}").json()
    client.patch(
        f"/api/proposals/{certificate['id']}",
        json={"actor": SME, "new_element": {**detail["new_element"], "local_name": "Bad Name!"}},
    )
    blocked = _decide(client, certificate["id"], "approve")
    assert blocked.status_code == 422 and error_code(blocked) == "PROPOSAL_INTRODUCES_ERRORS"
    assert blocked.json()["error"]["details"]["issues"][0]["code"] == "LOCAL_NAME_INVALID"


def test_drift_since_proposal_creation_is_detected_at_apply_time(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    ontology_id = studio["ontology"]["id"]
    proposals = _proposals(studio)
    modify = proposals["Modify class 'Shipment'"]
    alias = proposals["Add alias 'Haulier' to class 'Carrier'"]
    _decide(client, modify["id"], "approve")
    _decide(client, alias["id"], "approve")

    client.patch(f"/api/ontologies/{ontology_id}/classes/cls-shipment", json={"description": "Changed by someone else."})

    result = client.post(f"/api/ontologies/{ontology_id}/proposals/apply", json={"actor": SME}).json()
    assert [p["id"] for p in result["applied"]] == [alias["id"]]
    assert result["failed"][0]["proposal_id"] == modify["id"]
    assert "changed in the draft since this proposal was created" in result["failed"][0]["reason"]
    still_approved = client.get(f"/api/proposals/{modify['id']}").json()
    assert still_approved["status"] == "approved" and still_approved["apply_error"]
    assert still_approved["events"][-1]["event_type"] == "apply_failed"


def test_edit_can_convert_add_into_alias_and_validates_targets(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    proposals = _proposals(studio)
    certificate = proposals["Add class 'Certificate of Insurance'"]

    missing_target = client.patch(f"/api/proposals/{certificate['id']}", json={"actor": SME, "proposal_type": "alias"})
    assert missing_target.status_code == 422 and error_code(missing_target) == "PROPOSAL_TARGET_REQUIRED"

    converted = client.patch(
        f"/api/proposals/{certificate['id']}",
        json={"actor": SME, "proposal_type": "alias", "target_element_id": "cls-supplier", "alias": "Insured Supplier"},
    ).json()
    assert converted["proposal_type"] == "alias" and converted["new_element"] is None
    assert converted["changes"]["aliases"]["after"][-1] == "Insured Supplier"
    assert converted["title"] == "Add alias 'Insured Supplier' to class 'Supplier'"


def test_applied_and_unknown_proposals(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    assert client.get("/api/proposals/nope").status_code == 404
    proposals = _proposals(studio)
    reuse = proposals["Reuse existing class 'Supplier'"]
    _decide(client, reuse["id"], "approve")
    result = client.post(f"/api/ontologies/{studio['ontology']['id']}/proposals/apply", json={"actor": SME}).json()
    assert result["revision_incremented"] is False, "reuse confirms coverage without changing the draft"
    locked = client.patch(f"/api/proposals/{reuse['id']}", json={"actor": SME, "rationale": "x"})
    assert locked.status_code == 409 and error_code(locked) == "PROPOSAL_NOT_EDITABLE"
