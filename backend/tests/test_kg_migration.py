"""Migration 0003 safety and interrupted-build recovery."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.db.migrations import upgrade_database
from app.main import create_app
from tests.conftest import make_settings
from tests.kg_helpers import SME, setup_kg


def test_upgrade_to_0003_preserves_existing_proposals_and_evidence(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    upgrade_database(url, "0002")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (id, name, business_domain, description, created_at, updated_at) "
                                "VALUES ('p', 'P', '', '', '2026-01-01', '2026-01-01')"))
        connection.execute(text("INSERT INTO ontologies (id, project_id, name, namespace, prefix, description, draft_revision, "
                                "created_at, updated_at) VALUES ('o', 'p', 'O', 'https://e.com/o#', 'o', '', 1, "
                                "'2026-01-01', '2026-01-01')"))
        connection.execute(text(
            "INSERT INTO change_proposals (id, ontology_id, proposal_type, element_kind, status, title, term, rationale, "
            "changes, alignment, depends_on, edited, created_at, updated_at) VALUES ('cp', 'o', 'add', 'class', "
            "'pending', 'Add class', 'x', '', '{}', '{}', '[]', 0, '2026-01-01', '2026-01-01')"
        ))
        connection.execute(text(
            "INSERT INTO proposal_evidence (id, proposal_id, document_name, quote, context, verified, created_at) "
            "VALUES ('ev', 'cp', 'd', 'q', '', 1, '2026-01-01')"
        ))
        connection.execute(text(
            "INSERT INTO proposal_events (id, proposal_id, event_type, actor, comment, details, created_at) "
            "VALUES ('pe', 'cp', 'created', 'AI', '', '{}', '2026-01-01')"
        ))
    upgrade_database(url, "0003")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT origin, kg_build_id FROM change_proposals")).one() == ("discovery", None)
        assert connection.execute(text("SELECT count(*) FROM proposal_evidence")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM proposal_events")).scalar() == 1
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"kg_builds", "kg_candidate_facts", "kg_ontology_gaps", "graph_vertices", "graph_edges"} <= tables
    engine.dispose()


def test_interrupted_builds_are_marked_failed_on_restart(db_path: Path) -> None:
    with TestClient(create_app(make_settings(db_path, seed=True))) as client:
        env = setup_kg(client, ["suppliers.csv"])
        build = client.post(
            f"/api/projects/{env['project']['id']}/kg/builds",
            json={
                "ontology_version_id": env["version"]["id"],
                "source_document_ids": [env["documents"]["suppliers.csv"]["id"]],
                "mapping_ids": [env["mappings"]["suppliers.csv"]["id"]],
                "requested_by": SME,
            },
        ).json()
        engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        with engine.begin() as connection:
            connection.execute(text("UPDATE kg_builds SET status='running' WHERE id=:id"), {"id": build["id"]})
        engine.dispose()
    with TestClient(create_app(make_settings(db_path))) as client:
        reloaded = client.get(f"/api/kg/builds/{build['id']}").json()
    assert reloaded["status"] == "failed"
    assert reloaded["error"] == "Interrupted: the server stopped before the build finished."
    assert {s["status"] for s in reloaded["stages"]} == {"skipped"}
