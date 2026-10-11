"""Persistence for ontology change proposals, their evidence and the SME decision trail."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id, utcnow
from app.db.base import Base, TimestampMixin, UTCDateTime


class ChangeProposal(TimestampMixin, Base):
    __tablename__ = "change_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ontology_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontologies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("discovery_runs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # "discovery" (AI discovery run) or "kg_build" (ontology gap found while building a KG).
    origin: Mapped[str] = mapped_column(String(16), default="discovery", server_default="discovery", nullable=False)
    kg_build_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("kg_builds.id", ondelete="SET NULL"), index=True, nullable=True
    )
    proposal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    element_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_element_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ADD: complete definition of the element to create (canonical model fields incl. id).
    new_element: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # MODIFY / ALIAS / CONFLICT resolution: {field: {"before": value, "after": value}}.
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    alignment: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # Verbatim validated LLM finding, kept unchanged for traceability even after SME edits.
    llm_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    applied_draft_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    apply_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProposalEvidence(Base):
    """A source quote supporting a proposal. Quote, document name and page are stored with the
    evidence so it survives deletion of the source document."""

    __tablename__ = "proposal_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("change_proposals.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    chunk_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_chunks.id", ondelete="SET NULL"), nullable=True
    )
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, default="", nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class ProposalEvent(Base):
    """Append-only review timeline: creation, edits, decisions, comments and application."""

    __tablename__ = "proposal_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("change_proposals.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
