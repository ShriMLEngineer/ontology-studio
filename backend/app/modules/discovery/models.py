from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id, utcnow
from app.db.base import Base, UTCDateTime


class DiscoveryRun(Base):
    """One AI-assisted analysis of source documents against an ontology baseline."""

    __tablename__ = "discovery_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ontology_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontologies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    baseline_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    baseline_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_versions.id"), nullable=True
    )
    baseline_label: Mapped[str] = mapped_column(String(100), nullable=False)
    baseline_draft_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    discarded: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
