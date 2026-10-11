from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    business_domain: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    # Base for knowledge-graph instance IRIs ({data_namespace}e/{vertex_id}); NULL = derived from the ontology IRI.
    data_namespace: Mapped[str | None] = mapped_column(String(500), nullable=True)
