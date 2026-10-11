from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.sources.chunking import chunk_text
from tests.conftest import error_code, make_settings
from tests.pdf_fixture import make_pdf

POLICY = (
    "Supplier onboarding policy.\n\n"
    "Every vendor must hold a valid certificate of insurance before the first purchase order is issued.\n\n"
    "Quality inspections are recorded for each inbound batch at the receiving dock."
)


def _project(client: TestClient) -> dict[str, Any]:
    return client.post("/api/projects", json={"name": "Docs"}).json()


def _upload(client: TestClient, project_id: str, name: str, content: bytes) -> Any:
    return client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": (name, content)},
        data={"uploaded_by": "Dana SME"},
    )


def test_chunks_respect_size_and_offsets() -> None:
    text = ("Sentence number one is here. " * 40 + "\n\n") * 6
    chunks = chunk_text(text, 500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 500
        assert text[chunk.start : chunk.end] == chunk.text
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_upload_text_document(client: TestClient) -> None:
    project = _project(client)
    response = _upload(client, project["id"], "policy.md", POLICY.encode())
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["media_type"] == "text/markdown"
    assert document["uploaded_by"] == "Dana SME"
    assert document["chunk_count"] >= 1 and document["page_count"] is None

    detail = client.get(f"/api/sources/{document['id']}").json()
    assert "certificate of insurance" in detail["chunks"][0]["text"]
    assert [d["id"] for d in client.get(f"/api/projects/{project['id']}/sources").json()] == [document["id"]]

    events = client.get(f"/api/projects/{project['id']}/activity").json()
    assert events[0]["event_type"] == "source.uploaded"


def test_upload_pdf_tracks_pages(client: TestClient) -> None:
    project = _project(client)
    pdf = make_pdf(["Carriers collect pallets from the warehouse.", "Each pallet carries a license plate number."])
    response = _upload(client, project["id"], "logistics.pdf", pdf)
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["media_type"] == "application/pdf"
    assert document["page_count"] == 2
    detail = client.get(f"/api/sources/{document['id']}").json()
    assert "license plate number" in " ".join(c["text"] for c in detail["chunks"])
    assert detail["chunks"][0]["page"] == 1


def test_duplicate_and_invalid_uploads_are_rejected(client: TestClient) -> None:
    project = _project(client)
    assert _upload(client, project["id"], "a.txt", POLICY.encode()).status_code == 201

    duplicate = _upload(client, project["id"], "copy.txt", POLICY.encode())
    assert duplicate.status_code == 409 and error_code(duplicate) == "DOCUMENT_ALREADY_UPLOADED"

    unsupported = _upload(client, project["id"], "image.png", b"\x89PNG")
    assert unsupported.status_code == 415 and error_code(unsupported) == "UNSUPPORTED_DOCUMENT_TYPE"

    empty = _upload(client, project["id"], "empty.txt", b"   \n ")
    assert empty.status_code == 422 and error_code(empty) == "DOCUMENT_PARSE_FAILED"

    broken = _upload(client, project["id"], "broken.pdf", b"%PDF-1.4 not really")
    assert broken.status_code == 422 and error_code(broken) == "DOCUMENT_PARSE_FAILED"


def test_upload_size_limit(db_path: Path) -> None:
    with TestClient(create_app(make_settings(db_path, source_max_upload_bytes=50))) as client:
        project = _project(client)
        response = _upload(client, project["id"], "big.txt", b"x" * 51)
    assert response.status_code == 413 and error_code(response) == "DOCUMENT_TOO_LARGE"


def test_delete_document(client: TestClient) -> None:
    project = _project(client)
    document = _upload(client, project["id"], "a.txt", POLICY.encode()).json()
    assert client.delete(f"/api/sources/{document['id']}").status_code == 204
    assert client.get(f"/api/sources/{document['id']}").status_code == 404
