from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id, utcnow
from app.db.base import Base, UTCDateTime


class ImmutableVersionError(RuntimeError):
    pass


class OntologyVersion(Base):
    """An immutable published snapshot of an ontology.

    Immutability is enforced in layers: no mutation endpoints, the ORM guards below, database
    triggers (migration 0002) and write-once, hash-verified artifact files.
    """

    __tablename__ = "ontology_versions"
    __table_args__ = (
        UniqueConstraint("ontology_id", "version"),
        UniqueConstraint("ontology_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ontology_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontologies.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    class_count: Mapped[int] = mapped_column(Integer, nullable=False)
    object_property_count: Mapped[int] = mapped_column(Integer, nullable=False)
    datatype_property_count: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    validation_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    change_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    previous_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    published_by: Mapped[str] = mapped_column(String(200), nullable=False)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


@event.listens_for(OntologyVersion, "before_update")
def _reject_update(*_: Any) -> None:
    raise ImmutableVersionError("Published ontology versions are immutable.")


@event.listens_for(OntologyVersion, "before_delete")
def _reject_delete(*_: Any) -> None:
    raise ImmutableVersionError("Published ontology versions are immutable.")
