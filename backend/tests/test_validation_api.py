from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import add_class, error_code


def test_latest_validation_before_any_run_is_404(client: TestClient, ontology: dict[str, Any]) -> None:
    response = client.get(f"/api/ontologies/{ontology['id']}/validations/latest")
    assert response.status_code == 404
    assert error_code(response) == "VALIDATION_NOT_FOUND"
    assert client.get(f"/api/ontologies/{ontology['id']}/validations").json() == []


def test_validation_history_is_newest_first(client: TestClient, ontology: dict[str, Any]) -> None:
    oid = ontology["id"]
    first = client.post(f"/api/ontologies/{oid}/validations").json()
    add_class(client, oid, "Supplier")
    second = client.post(f"/api/ontologies/{oid}/validations").json()
    history = client.get(f"/api/ontologies/{oid}/validations?limit=5").json()
    assert [r["id"] for r in history] == [second["id"], first["id"]]
    assert history[1]["is_current"] is False
    assert len(client.get(f"/api/ontologies/{oid}/validations?limit=1").json()) == 1


def test_validation_run_is_persisted_and_tracks_currency(
    client: TestClient, ontology: dict[str, Any]
) -> None:
    oid = ontology["id"]
    add_class(client, oid, "Supplier")

    run = client.post(f"/api/ontologies/{oid}/validations")
    assert run.status_code == 201
    report = run.json()
    assert report["is_valid"] is True
    assert report["is_current"] is True
    assert report["info_count"] == 1 and report["issues"][0]["code"] == "ORPHAN_CLASS"

    latest = client.get(f"/api/ontologies/{oid}/validations/latest").json()
    assert latest["id"] == report["id"]

    add_class(client, oid, "Product")
    stale = client.get(f"/api/ontologies/{oid}/validations/latest").json()
    assert stale["is_current"] is False
    assert stale["current_draft_revision"] == report["draft_revision"] + 1


def test_validation_reports_structural_errors_from_saved_draft(
    client: TestClient, ontology: dict[str, Any]
) -> None:
    oid = ontology["id"]
    draft = client.get(f"/api/ontologies/{oid}/draft").json()
    body = {
        "base_revision": draft["draft_revision"],
        "metadata": {"name": "Broken", "namespace": "https://example.com/broken", "prefix": "b"},
        "classes": [
            {"id": "c1", "local_name": "Order", "label": "Order", "description": "x"},
            {"id": "c2", "local_name": "Order", "label": "Order", "description": "x"},
        ],
        "object_properties": [
            {"id": "r1", "local_name": "placedBy", "label": "placed by", "domain_id": "c1", "range_id": "ghost"}
        ],
        "datatype_properties": [],
    }
    assert client.put(f"/api/ontologies/{oid}/draft", json=body).status_code == 200

    report = client.post(f"/api/ontologies/{oid}/validations").json()
    assert report["is_valid"] is False
    codes = {i["code"] for i in report["issues"] if i["severity"] == "error"}
    assert {"NAMESPACE_MISSING_SEPARATOR", "DUPLICATE_LOCAL_NAME", "PROPERTY_RANGE_UNKNOWN"} <= codes
    assert report["error_count"] == sum(1 for i in report["issues"] if i["severity"] == "error")

    project_id = ontology["project_id"]
    latest_event = client.get(f"/api/projects/{project_id}/activity?limit=1").json()[0]
    assert latest_event["event_type"] == "ontology.validated"
    assert "failed" in latest_event["summary"]
