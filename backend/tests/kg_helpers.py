"""Shared fixtures and helpers for knowledge-graph tests (sample data from samples/supply-chain)."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import REPO_ROOT

SAMPLES = REPO_ROOT / "samples" / "supply-chain"
SME = "Dana SME"
STRUCTURED = ["suppliers.csv", "products.csv", "purchase_orders.csv", "supply_relationships.csv"]


def sample_bytes(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def upload(client: TestClient, project_id: str, name: str, content: bytes | None = None) -> dict[str, Any]:
    response = client.post(
        f"/api/projects/{project_id}/sources", files={"file": (name, content if content is not None else sample_bytes(name))}
    )
    assert response.status_code == 201, response.text
    return response.json()


def publish(client: TestClient, ontology_id: str, version: str) -> dict[str, Any]:
    response = client.post(
        f"/api/ontologies/{ontology_id}/versions", json={"published_by": SME, "version": version, "release_notes": "test"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def save_suggested_mapping(client: TestClient, project_id: str, document: dict[str, Any], version_id: str) -> dict[str, Any]:
    suggestion = client.get(
        f"/api/sources/{document['id']}/mapping-suggestion", params={"ontology_version_id": version_id}
    ).json()
    assert suggestion["spec"] is not None, suggestion
    response = client.post(
        f"/api/projects/{project_id}/kg/mappings",
        json={
            "document_id": document["id"],
            "ontology_version_id": version_id,
            "name": f"{Path(document['filename']).stem} mapping",
            "spec": suggestion["spec"],
            "updated_by": SME,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def setup_kg(client: TestClient, files: list[str] | None = None) -> dict[str, Any]:
    """Seeded project with v1.0.0 published, sample sources uploaded and mappings saved."""
    project = client.get("/api/projects").json()[0]
    ontology = client.get(f"/api/projects/{project['id']}/ontologies").json()[0]
    version = publish(client, ontology["id"], "1.0.0")
    documents: dict[str, dict[str, Any]] = {}
    mappings: dict[str, dict[str, Any]] = {}
    for name in files or STRUCTURED:
        documents[name] = upload(client, project["id"], name)
        if name.endswith(".csv"):
            mappings[name] = save_suggested_mapping(client, project["id"], documents[name], version["id"])
    return {
        "client": client,
        "project": project,
        "ontology": ontology,
        "version": version,
        "documents": documents,
        "mappings": mappings,
    }


def run_build(env: dict[str, Any], *, version_id: str | None = None, names: list[str] | None = None, **settings: Any) -> dict[str, Any]:
    client: TestClient = env["client"]
    names = names or list(env["documents"])
    response = client.post(
        f"/api/projects/{env['project']['id']}/kg/builds",
        json={
            "ontology_version_id": version_id or env["version"]["id"],
            "source_document_ids": [env["documents"][n]["id"] for n in names],
            "mapping_ids": [env["mappings"][n]["id"] for n in names if n in env["mappings"]],
            "requested_by": SME,
            "settings": settings,
            "start": True,
        },
    )
    assert response.status_code == 201, response.text
    build = client.get(f"/api/kg/builds/{response.json()['id']}").json()
    assert build["status"] == "completed", (build["error"], build["stages"])
    return build


def facts(client: TestClient, build_id: str, **params: Any) -> list[dict[str, Any]]:
    return client.get(f"/api/kg/builds/{build_id}/facts", params=params).json()["items"]


def find_fact(items: list[dict[str, Any]], subject: str, predicate: str, obj: str) -> dict[str, Any]:
    matches = [
        f for f in items if f["subject_label"] == subject and f["predicate_label"] == predicate and f["object_label"] == obj
    ]
    assert matches, f"No fact {subject} -[{predicate}]-> {obj}"
    return matches[0]
