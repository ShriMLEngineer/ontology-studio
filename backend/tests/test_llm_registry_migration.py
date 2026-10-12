import json
from pathlib import Path

from sqlalchemy import create_engine, text

from app.db.migrations import upgrade_database


def test_multi_provider_migration_preserves_registrations_and_splits_project_defaults(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'llm-migration.db').as_posix()}"
    upgrade_database(url, "0008")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects (id, name, business_domain, description, default_llm_config_id, "
                "default_graph_connection_id, created_at, updated_at) "
                "VALUES ('project-1', 'Legacy', '', '', 'llm-1', NULL, '2026-10-01', '2026-10-01')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO llm_configurations (id, name, provider, base_url, model, api_key_env, "
                "structured_output, temperature, timeout_seconds, max_output_tokens, description, "
                "last_test, updated_by, created_at, updated_at) "
                "VALUES ('llm-1', 'Legacy Ollama', 'openai-compatible', 'http://localhost:11434/v1', "
                "'qwen2.5:7b', NULL, 'json_schema', 0, 600, 4096, '', NULL, '', '2026-10-01', '2026-10-01')"
            )
        )
    upgrade_database(url)
    with engine.connect() as connection:
        llm = connection.execute(
            text("SELECT provider, provider_config, enabled FROM llm_configurations WHERE id='llm-1'")
        ).one()
        project = connection.execute(
            text(
                "SELECT default_llm_config_id, default_discovery_llm_config_id, default_kg_llm_config_id "
                "FROM projects WHERE id='project-1'"
            )
        ).one()
    assert llm == ("openai-compatible", "{}", 1)
    assert project == ("llm-1", "llm-1", "llm-1")
    engine.dispose()


def test_migration_recovers_from_an_interrupted_draft_of_itself(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'llm-partial.db').as_posix()}"
    upgrade_database(url, "0008")
    engine = create_engine(url)
    with engine.begin() as connection:
        # State left by a draft migration that failed part-way (SQLite DDL is not transactional).
        for ddl in (
            "ALTER TABLE llm_configurations ADD COLUMN deployment_name VARCHAR(200)",
            "ALTER TABLE llm_configurations ADD COLUMN deployment_type VARCHAR(40)",
            "ALTER TABLE llm_configurations ADD COLUMN auth_method VARCHAR(20) NOT NULL DEFAULT 'api_key'",
            "ALTER TABLE llm_configurations ADD COLUMN inference_params JSON NOT NULL DEFAULT '{}'",
            "ALTER TABLE llm_configurations ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
            "ALTER TABLE projects ADD COLUMN default_discovery_llm_config_id VARCHAR(36)",
            "ALTER TABLE projects ADD COLUMN default_kg_llm_config_id VARCHAR(36)",
            "CREATE TABLE _alembic_tmp_llm_configurations (id VARCHAR(36) NOT NULL)",
        ):
            connection.execute(text(ddl))
        connection.execute(
            text(
                "INSERT INTO projects (id, name, business_domain, description, default_llm_config_id, "
                "default_graph_connection_id, default_kg_llm_config_id, created_at, updated_at) "
                "VALUES ('project-1', 'Legacy', '', '', 'llm-1', NULL, 'llm-2', '2026-10-01', '2026-10-01')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO llm_configurations (id, name, provider, base_url, model, api_key_env, "
                "structured_output, temperature, timeout_seconds, max_output_tokens, description, "
                "last_test, updated_by, created_at, updated_at, deployment_type, auth_method, "
                "inference_params, is_active) "
                "VALUES ('llm-1', 'Draft Azure', 'azure-foundry', 'https://r.services.ai.azure.com', "
                "'gpt', 'AZURE_KEY', 'json_schema', 0, 600, 4096, '', NULL, '', '2026-10-01', '2026-10-01', "
                "'azure-openai', 'api_key', '{\"top_p\": 0.5}', 0)"
            )
        )

    upgrade_database(url)

    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(llm_configurations)"))}
        llm = connection.execute(text("SELECT provider_config, enabled FROM llm_configurations")).one()
        project = connection.execute(
            text("SELECT default_discovery_llm_config_id, default_kg_llm_config_id FROM projects")
        ).one()
    assert "_alembic_tmp_llm_configurations" not in tables
    assert {"provider_config", "enabled"} <= columns
    assert columns.isdisjoint({"deployment_name", "deployment_type", "auth_method", "inference_params", "is_active"})
    assert json.loads(llm[0]) == {
        "deployment_type": "azure-openai",
        "auth_method": "api_key",
        "inference_parameters": {"top_p": 0.5},
    }
    assert llm[1] == 0
    # Existing purpose-specific values are kept; only unset ones are backfilled from the legacy default.
    assert project == ("llm-1", "llm-2")
    engine.dispose()