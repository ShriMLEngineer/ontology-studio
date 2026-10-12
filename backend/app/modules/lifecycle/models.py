"""Project lifecycle iterations (Phase 4 Project Lifecycle Navigator)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id, utcnow
from app.db.base import Base, UTCDateTime


class ProjectIteration(Base):
    """One pass through the lifecycle. Exactly one iteration per project is ``active``.

    An iteration covers the time window ``[started_at, closed_at)``; stage statuses are derived from
    the records created in that window. ``reused`` records, per stage before ``start_stage``, the
    outputs taken over from earlier iterations. When the next iteration starts, this one is closed
    and its stage statuses are frozen in ``closing_snapshot``.
    """

    __tablename__ = "project_iterations"
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Ontology in focus; NULL or a deleted ontology falls back to the project's first ontology.
    ontology_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    start_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    base_iteration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reused: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    closing_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
