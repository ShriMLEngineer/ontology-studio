"""value normalisation audit record

Adds ``kg_candidate_facts.value_normalization``: for attribute facts, how the raw extracted value was typed
(raw value, normalised value, datatype, rule, status, unit, scale). Additive only: existing facts keep NULL,
which means "built before value normalisation existed"; historical build results are never re-evaluated.
Safe to re-run after an interrupted attempt (SQLite DDL is not transactional).

Revision ID: 0011
Revises: 0010
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "value_normalization" not in _columns("kg_candidate_facts"):
        with op.batch_alter_table("kg_candidate_facts") as batch_op:
            batch_op.add_column(sa.Column("value_normalization", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kg_candidate_facts") as batch_op:
        batch_op.drop_column("value_normalization")
