"""Persistence for knowledge-graph builds: configuration, execution records, extracted entities,
candidate facts with validation outcomes, entity-resolution decisions and ontology gaps.

Provenance is denormalised onto facts and mentions (file name, page, row, quote) so it survives
deletion of a source document.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id, utcnow
from app.db.base import Base, TimestampMixin, UTCDateTime


class KgSourceMapping(TimestampMixin, Base):
    """A saved, reusable source-to-ontology mapping for one structured source."""

    __tablename__ = "kg_source_mappings"
    __table_args__ = (UniqueConstraint("document_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ontology_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontologies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The published version the mapping was last validated against (element ids are stable).
    ontology_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class KgBuild(Base):
    """One knowledge-graph build: configuration, execution status and results scope.

    The graph produced by a build is stored under ``graph_id == id``; builds never overwrite each
    other. Configuration is editable only while ``status == 'configured'``.
    """

    __tablename__ = "kg_builds"
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ontology_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontologies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ontology_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    ontology_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ontology_name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_build_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    source_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    mapping_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # Frozen at start: sources (with hashes), mapping specs and LLM provider/model/prompt version.
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    graph_store: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_outputs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class KgBuildLog(Base):
    __tablename__ = "kg_build_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    build_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kg_builds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class KgEntity(Base):
    """A resolved entity in one build, with its resolution decision."""

    __tablename__ = "kg_entities"
    __table_args__ = (UniqueConstraint("build_id", "vertex_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    build_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kg_builds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vertex_id: Mapped[str] = mapped_column(String(64), nullable=False)
    class_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    class_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    class_label: Mapped[str] = mapped_column(String(300), nullable=False)
    identifier: Mapped[str | None] = mapped_column(String(300), nullable=True)
    key_namespace: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    resolution_method: Mapped[str] = mapped_column(String(32), nullable=False)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    has_master_record: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    type_fact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class KgEntityMention(Base):
    """One occurrence of an entity in a source, linked to the entity it was resolved to."""

    __tablename__ = "kg_entity_mentions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    build_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kg_builds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kg_entities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    class_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    identifier: Mapped[str | None] = mapped_column(String(300), nullable=True)
    label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution_method: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class KgCandidateFact(Base):
    """A candidate fact with independent structural and evidence validation results.

    ``kind`` is ``type`` (entity is an instance of a class), ``relationship`` or ``attribute``.
    Only ACCEPTED facts are written to the graph store.
    """

    __tablename__ = "kg_candidate_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    build_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kg_builds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    subject_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    subject_label: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    subject_class_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    predicate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    predicate_ref: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    predicate_label: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    object_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    object_label: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    object_class_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    datatype: Mapped[str | None] = mapped_column(String(16), nullable=True)
    structural: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resolution: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    graph_element_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Phase 4 per-lane results (policy, SHACL, entailment); NULL for builds evaluated before Phase 4.
    lanes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class KgOntologyGap(Base):
    """A concept found in the sources that the build's ontology version cannot represent."""

    __tablename__ = "kg_ontology_gaps"
    __table_args__ = (UniqueConstraint("build_id", "gap_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    build_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kg_builds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    gap_type: Mapped[str] = mapped_column(String(32), nullable=False)
    gap_key: Mapped[str] = mapped_column(String(400), nullable=False)
    term: Mapped[str] = mapped_column(String(300), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    suggestion: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    origins: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    proposal_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
