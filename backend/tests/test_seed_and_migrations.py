from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.core.config import Settings
from app.db.models import Base
from app.main import create_app


def test_seed_creates_valid_supply_chain_ontology(seeded_client: TestClient) -> None:
    projects = seeded_client.get("/api/projects").json()
    assert [p["name"] for p in projects] == ["Supply Chain"]
    ontology = seeded_client.get(f"/api/projects/{projects[0]['id']}/ontologies").json()[0]
    assert ontology["stats"]["class_count"] >= 10
    assert ontology["stats"]["object_property_count"] >= 10

    report = seeded_client.post(f"/api/ontologies/{ontology['id']}/validations").json()
    assert report["is_valid"] is True
    assert report["error_count"] == 0 and report["warning_count"] == 0

    draft = seeded_client.get(f"/api/ontologies/{ontology['id']}/draft").json()
    assert set(draft["layout"]["positions"]) == {c["id"] for c in draft["classes"]}


def test_seed_is_idempotent_and_never_overwrites_user_changes(seeded_client: TestClient) -> None:
    project = seeded_client.get("/api/projects").json()[0]
    seeded_client.patch(f"/api/projects/{project['id']}", json={"description": "Mine"})

    settings: Settings = seeded_client.app.state.settings  # type: ignore[attr-defined]
    with TestClient(create_app(settings)) as restarted:
        projects = restarted.get("/api/projects").json()
    assert len(projects) == 1
    assert projects[0]["description"] == "Mine"


def test_migrations_match_models(seeded_client: TestClient) -> None:
    url = seeded_client.app.state.settings.database_url  # type: ignore[attr-defined]
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            assert {
                "projects",
                "ontologies",
                "ontology_classes",
                "ontology_object_properties",
                "ontology_datatype_properties",
                "ontology_diagram_layouts",
                "ontology_validation_runs",
                "activity_events",
                "alembic_version",
            } <= tables
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
            assert diff == [], f"Models and migrations have drifted: {diff}"
    finally:
        engine.dispose()
