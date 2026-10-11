"""Persistence model for ontology drafts.

The draft is the mutable working copy of a long-lived ontology asset. Element rows are
keyed by ``(ontology_id, id)`` where ``id`` is a stable element identifier that survives
renames of labels and local names. Cross-element references (parents, domain, range) are
stored as element ids rather than foreign keys so that a draft can temporarily hold
inconsistent work-in-progress; the validation module reports such issues and (from Phase 2)
publication is gated on a clean validation.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id, utcnow
from app.db.base import Base, TimestampMixin, UTCDateTime


class Ontology(TimestampMixin, Base):
    __tablename__ = "ontologies"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    namespace: Mapped[str] = mapped_column(String(500), nullable=False)
    prefix: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class _OntologyElementColumns(TimestampMixin):
    ontology_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontologies.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    local_name: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class OntologyClassRecord(_OntologyElementColumns, Base):
    __tablename__ = "ontology_classes"

    parent_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class ObjectPropertyRecord(_OntologyElementColumns, Base):
    __tablename__ = "ontology_object_properties"

    domain_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    range_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DatatypePropertyRecord(_OntologyElementColumns, Base):
    __tablename__ = "ontology_datatype_properties"

    domain_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    datatype: Mapped[str] = mapped_column(String(32), nullable=False, default="string")
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    multi_valued: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class OntologyDiagramLayout(Base):
    """Presentation-only node positions for the visual designer (not part of the ontology)."""

    __tablename__ = "ontology_diagram_layouts"

    ontology_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontologies.id", ondelete="CASCADE"), primary_key=True
    )
    positions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )
