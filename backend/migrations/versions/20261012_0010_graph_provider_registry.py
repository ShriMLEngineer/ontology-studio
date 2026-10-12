"""Provider-aware graph database registry.

Adds, to registered graph connections, the graph data model, an enabled flag and an optional
workspace-default flag; and to graph deployments a snapshot of the non-secret connection settings
used, so editing a registration never redirects reads of historical deployments. Existing generic
SPARQL registrations keep their ``kind`` and configuration untouched. Safe to re-run after an
interrupted attempt (SQLite DDL is not transactional).

Revision ID: 0010
Revises: 0009
"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RDF_KINDS = {"sparql-http", "graphdb", "fuseki", "oxigraph"}


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table in sa.inspect(bind).get_table_names():
        if table.startswith("_alembic_tmp_"):
            op.drop_table(table)

    graph_columns = _columns("graph_connections")
    with op.batch_alter_table("graph_connections") as batch_op:
        if "data_model" not in graph_columns:
            batch_op.add_column(sa.Column("data_model", sa.String(20), nullable=False, server_default="rdf"))
        if "enabled" not in graph_columns:
            batch_op.add_column(sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        if "is_default" not in graph_columns:
            batch_op.add_column(sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Every registration made before this migration is a generic SPARQL endpoint (an RDF target).
    for (kind,) in bind.execute(sa.text("SELECT DISTINCT kind FROM graph_connections")).all():
        model = "rdf" if kind in _RDF_KINDS else "property-graph"
        bind.execute(sa.text("UPDATE graph_connections SET data_model = :model WHERE kind = :kind"),
                     {"model": model, "kind": kind})
    with op.batch_alter_table("graph_connections") as batch_op:
        batch_op.alter_column("data_model", server_default=None)
        batch_op.alter_column("enabled", server_default=None)
        batch_op.alter_column("is_default", server_default=None)

    if "target_snapshot" not in _columns("kg_graph_deployments"):
        with op.batch_alter_table("kg_graph_deployments") as batch_op:
            batch_op.add_column(sa.Column("target_snapshot", sa.JSON(), nullable=True))
    rows = bind.execute(sa.text(
        "SELECT d.id, c.kind, c.config, c.secret_env FROM kg_graph_deployments d "
        "JOIN graph_connections c ON c.id = d.target_id WHERE d.target_snapshot IS NULL"
    )).all()
    for deployment_id, kind, config, secret_env in rows:
        parsed = json.loads(config) if isinstance(config, str) else (config or {})
        snapshot = {"provider": kind, "config": parsed, "secret_env": secret_env, "origin": "migration-0010"}
        bind.execute(
            sa.text("UPDATE kg_graph_deployments SET target_snapshot = :snapshot WHERE id = :id"),
            {"snapshot": json.dumps(snapshot), "id": deployment_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("kg_graph_deployments") as batch_op:
        batch_op.drop_column("target_snapshot")
    with op.batch_alter_table("graph_connections") as batch_op:
        batch_op.drop_column("is_default")
        batch_op.drop_column("enabled")
        batch_op.drop_column("data_model")
