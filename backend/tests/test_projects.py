from fastapi.testclient import TestClient

from tests.conftest import ONTOLOGY_PAYLOAD, error_code


def test_health_reports_database_ok(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_create_list_and_get_project(client: TestClient) -> None:
    assert client.get("/api/projects").json() == []

    response = client.post(
        "/api/projects",
        json={"name": "  Retail  ", "description": "Retail domain", "business_domain": "Retail"},
    )
    assert response.status_code == 201
    project = response.json()
    assert project["name"] == "Retail"
    assert project["ontology_count"] == 0
    assert project["created_at"].endswith("Z")

    listed = client.get("/api/projects").json()
    assert [p["id"] for p in listed] == [project["id"]]
    assert client.get(f"/api/projects/{project['id']}").json()["business_domain"] == "Retail"


def test_create_project_with_initial_ontology(client: TestClient) -> None:
    project = client.post(
        "/api/projects", json={"name": "Health", "initial_ontology": ONTOLOGY_PAYLOAD}
    ).json()
    assert project["ontology_count"] == 1
    ontologies = client.get(f"/api/projects/{project['id']}/ontologies").json()
    assert ontologies[0]["name"] == "Test Ontology"
    assert ontologies[0]["draft_revision"] == 1
    assert ontologies[0]["stats"] == {
        "class_count": 0,
        "object_property_count": 0,
        "datatype_property_count": 0,
    }


def test_project_names_are_unique_case_insensitively(client: TestClient) -> None:
    client.post("/api/projects", json={"name": "Finance"})
    response = client.post("/api/projects", json={"name": "FINANCE"})
    assert response.status_code == 409
    assert error_code(response) == "PROJECT_NAME_TAKEN"
    assert "message" in response.json()["error"]


def test_update_project(client: TestClient) -> None:
    project = client.post("/api/projects", json={"name": "Energy"}).json()
    response = client.patch(
        f"/api/projects/{project['id']}", json={"description": "Grid assets"}
    )
    assert response.status_code == 200
    assert response.json()["description"] == "Grid assets"


def test_unknown_project_returns_404_envelope(client: TestClient) -> None:
    response = client.get("/api/projects/does-not-exist")
    assert response.status_code == 404
    assert error_code(response) == "PROJECT_NOT_FOUND"


def test_request_validation_uses_error_envelope(client: TestClient) -> None:
    response = client.post("/api/projects", json={"name": "   "})
    assert response.status_code == 422
    assert error_code(response) == "REQUEST_VALIDATION_FAILED"
    assert response.json()["error"]["details"]["errors"]


def test_project_activity_is_recorded(client: TestClient) -> None:
    project = client.post(
        "/api/projects", json={"name": "Logistics", "initial_ontology": ONTOLOGY_PAYLOAD}
    ).json()
    events = client.get(f"/api/projects/{project['id']}/activity").json()
    assert {e["event_type"] for e in events} == {"project.created", "ontology.created"}
