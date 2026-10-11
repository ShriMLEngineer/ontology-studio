from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_settings(db_path: Path, *, seed: bool = False, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": f"sqlite:///{db_path.as_posix()}",
        "seed_demo_data": seed,
        "auto_migrate": True,
        "cors_origins": [],
        "log_level": "WARNING",
        "artifact_dir": db_path.parent / "artifacts",
        # Never let a developer's .env point tests at a real LLM.
        "llm_base_url": None,
        "llm_model": None,
        "llm_api_key": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(db_path))) as test_client:
        yield test_client


@pytest.fixture
def seeded_client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(db_path, seed=True))) as test_client:
        yield test_client


@pytest.fixture
def restart_client(db_path: Path) -> Callable[[], TestClient]:
    """Build a brand-new application instance against the same database file."""

    def _factory() -> TestClient:
        return TestClient(create_app(make_settings(db_path)))

    return _factory


ONTOLOGY_PAYLOAD = {
    "name": "Test Ontology",
    "namespace": "https://example.com/test#",
    "prefix": "t",
    "description": "Ontology used by tests",
}


@pytest.fixture
def ontology(client: TestClient) -> dict[str, Any]:
    """An empty ontology inside a fresh project."""
    project = client.post(
        "/api/projects", json={"name": "Test Project", "initial_ontology": ONTOLOGY_PAYLOAD}
    ).json()
    return client.get(f"/api/projects/{project['id']}/ontologies").json()[0]


def add_class(client: TestClient, ontology_id: str, label: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/ontologies/{ontology_id}/classes",
        json={"label": label, "description": f"{label} definition", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def error_code(response: Any) -> str:
    return response.json()["error"]["code"]


@pytest.fixture
def studio(db_path: Path) -> Iterator[dict[str, Any]]:
    """Seeded app with an uploaded source document and a scripted (test-double) LLM provider."""
    from tests.fakes import DISCOVERY_FINDINGS, SOURCE_TEXT, ScriptedLLMProvider

    with TestClient(create_app(make_settings(db_path, seed=True))) as client:
        project = client.get("/api/projects").json()[0]
        ontology = client.get(f"/api/projects/{project['id']}/ontologies").json()[0]
        document = client.post(
            f"/api/projects/{project['id']}/sources", files={"file": ("handbook.md", SOURCE_TEXT.encode())}
        ).json()
        provider = ScriptedLLMProvider([{"findings": DISCOVERY_FINDINGS}])
        client.app.state.llm_provider = provider  # type: ignore[attr-defined]
        yield {"client": client, "project": project, "ontology": ontology, "document": document, "provider": provider}


def start_run(studio: dict[str, Any], **body: Any) -> Any:
    client: TestClient = studio["client"]
    return client.post(
        f"/api/ontologies/{studio['ontology']['id']}/discovery-runs",
        json={"document_ids": [studio["document"]["id"]], "requested_by": "Dana SME", **body},
    )
