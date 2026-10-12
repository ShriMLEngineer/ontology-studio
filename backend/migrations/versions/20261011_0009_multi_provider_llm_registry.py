"""Multi-provider LLM registrations and purpose-specific project defaults.

Existing registrations retain their OpenAI-compatible behavior, and existing project defaults
are copied to both workflow-specific columns.

Revision ID: 0009
Revises: 0008
"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Columns of an unreleased draft of this migration. SQLite DDL is not transactional, so a draft
# that failed part-way can leave them (and a batch temp table) on development databases.
_DRAFT_COLUMNS = ("deployment_name", "deployment_type", "auth_method", "inference_params", "is_active")


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


def _fold_draft_columns() -> list[str]:
    """Move draft-column values into the final columns; return the draft columns safe to drop."""
    bind = op.get_bind()
    present = [name for name in _DRAFT_COLUMNS if name in _columns("llm_configurations")]
    if not present:
        return []
    llm = sa.table(
        "llm_configurations",
        sa.column("id", sa.String),
        sa.column("provider_config", sa.JSON),
        sa.column("enabled", sa.Boolean),
    )
    rows = bind.execute(sa.text(f"SELECT id, provider_config, {', '.join(present)} FROM llm_configurations")).mappings().all()
    for row in rows:
        config = _json_object(row["provider_config"])
        for key in ("deployment_type", "auth_method"):
            if row.get(key) and key not in config:
                config[key] = row[key]
        parameters = _json_object(row.get("inference_params"))
        if parameters and "inference_parameters" not in config:
            config["inference_parameters"] = parameters
        values: dict[str, object] = {"provider_config": config}
        if "is_active" in present:
            values["enabled"] = bool(row["is_active"])
        bind.execute(sa.update(llm).where(llm.c.id == row["id"]).values(**values))
    droppable = [name for name in present if name != "deployment_name"]
    # There is no equivalent of a deployment name, so a column holding data is kept, not discarded.
    if "deployment_name" in present and not any(row.get("deployment_name") for row in rows):
        droppable.append("deployment_name")
    return droppable


def upgrade() -> None:
    bind = op.get_bind()
    for table in sa.inspect(bind).get_table_names():
        if table.startswith("_alembic_tmp_"):
            op.drop_table(table)

    llm_columns = _columns("llm_configurations")
    added = [name for name in ("provider_config", "enabled") if name not in llm_columns]
    if added:
        with op.batch_alter_table("llm_configurations") as batch_op:
            if "provider_config" in added:
                batch_op.add_column(sa.Column("provider_config", sa.JSON(), nullable=False, server_default="{}"))
            if "enabled" in added:
                batch_op.add_column(sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    drop_columns = _fold_draft_columns()
    if added or drop_columns:
        with op.batch_alter_table("llm_configurations") as batch_op:
            for name in added:
                batch_op.alter_column(name, server_default=None)
            for name in drop_columns:
                batch_op.drop_column(name)

    project_columns = _columns("projects")
    new_defaults = [
        name for name in ("default_discovery_llm_config_id", "default_kg_llm_config_id") if name not in project_columns
    ]
    if new_defaults:
        with op.batch_alter_table("projects") as batch_op:
            for name in new_defaults:
                batch_op.add_column(sa.Column(name, sa.String(36), nullable=True))
    for name in ("default_discovery_llm_config_id", "default_kg_llm_config_id"):
        bind.execute(sa.text(
            f"UPDATE projects SET {name} = default_llm_config_id WHERE {name} IS NULL"
        ))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("default_kg_llm_config_id")
        batch_op.drop_column("default_discovery_llm_config_id")
    with op.batch_alter_table("llm_configurations") as batch_op:
        batch_op.drop_column("enabled")
        batch_op.drop_column("provider_config")