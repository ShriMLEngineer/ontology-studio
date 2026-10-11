from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_settings(db_path: Path, *, seed: bool = False) -> Settings:
    return Settings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        seed_demo_data=seed,
        auto_migrate=True,
        cors_origins=[],
        log_level="WARNING",
    )


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
