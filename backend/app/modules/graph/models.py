"""Tables backing :class:`SqlGraphStore`, the durable local graph adapter.

Vertices and edges are keyed by ``(graph_id, id)``. ``graph_id`` is an opaque scope (the KG build
id), so builds never share or overwrite each other's graph elements.
"""

from typing import Any

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class GraphVertexRecord(TimestampMixin, Base):
    __tablename__ = "graph_vertices"
    __table_args__ = (Index("ix_graph_vertices_graph_label", "graph_id", "label"),)

    graph_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    class_id: Mapped[str] = mapped_column(String(64), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class GraphEdgeRecord(TimestampMixin, Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        Index("ix_graph_edges_graph_out", "graph_id", "out_id"),
        Index("ix_graph_edges_graph_in", "graph_id", "in_id"),
    )

    graph_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    predicate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    out_id: Mapped[str] = mapped_column(String(64), nullable=False)
    in_id: Mapped[str] = mapped_column(String(64), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
