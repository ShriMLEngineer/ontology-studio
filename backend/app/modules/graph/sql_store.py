"""Durable local implementation of :class:`GraphStore` on the application database.

Chosen for the MVP because no Neo4j or Cosmos DB Gremlin connection is configured. It keeps the
Gremlin-compatible shape (labelled vertices, directed labelled edges, properties, graph scope) so
a Cosmos adapter can implement the same protocol without changing the pipeline or the UI.
"""

from collections import deque
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.graph.models import GraphEdgeRecord, GraphVertexRecord
from app.modules.graph.store import (
    GraphData,
    GraphEdge,
    GraphIntegrityError,
    GraphVertex,
    merge_properties,
    merge_unique,
)


def _vertex(record: GraphVertexRecord) -> GraphVertex:
    return GraphVertex(
        id=record.id,
        label=record.label,
        name=record.name,
        class_id=record.class_id,
        properties=dict(record.properties or {}),
        fact_ids=list(record.fact_ids or []),
        source_ids=list(record.source_ids or []),
    )


def _edge(record: GraphEdgeRecord) -> GraphEdge:
    return GraphEdge(
        id=record.id,
        label=record.label,
        predicate_id=record.predicate_id,
        out_id=record.out_id,
        in_id=record.in_id,
        properties=dict(record.properties or {}),
        fact_ids=list(record.fact_ids or []),
        source_ids=list(record.source_ids or []),
    )


class SqlGraphStore:
    name = "sql"

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ writes (idempotent)

    def upsert_vertices(self, graph_id: str, vertices: Sequence[GraphVertex]) -> int:
        for vertex in vertices:
            record = self.session.get(GraphVertexRecord, (graph_id, vertex.id))
            if record is None:
                self.session.add(
                    GraphVertexRecord(
                        graph_id=graph_id,
                        id=vertex.id,
                        label=vertex.label,
                        name=vertex.name[:500],
                        class_id=vertex.class_id,
                        properties=vertex.properties,
                        fact_ids=merge_unique([], vertex.fact_ids),
                        source_ids=merge_unique([], vertex.source_ids),
                    )
                )
            else:
                record.label = vertex.label
                record.name = vertex.name[:500]
                record.class_id = vertex.class_id
                record.properties = merge_properties(record.properties or {}, vertex.properties)
                record.fact_ids = merge_unique(record.fact_ids or [], vertex.fact_ids)
                record.source_ids = merge_unique(record.source_ids or [], vertex.source_ids)
        self.session.flush()
        return len(vertices)

    def upsert_edges(self, graph_id: str, edges: Sequence[GraphEdge]) -> int:
        endpoint_ids = {e.out_id for e in edges} | {e.in_id for e in edges}
        existing = set(
            self.session.scalars(
                select(GraphVertexRecord.id).where(
                    GraphVertexRecord.graph_id == graph_id, GraphVertexRecord.id.in_(endpoint_ids)
                )
            )
        )
        missing = sorted(endpoint_ids - existing)
        if missing:
            raise GraphIntegrityError(f"Edges reference vertices that are not in the graph: {', '.join(missing[:5])}")
        for edge in edges:
            record = self.session.get(GraphEdgeRecord, (graph_id, edge.id))
            if record is None:
                self.session.add(
                    GraphEdgeRecord(
                        graph_id=graph_id,
                        id=edge.id,
                        label=edge.label,
                        predicate_id=edge.predicate_id,
                        out_id=edge.out_id,
                        in_id=edge.in_id,
                        properties=edge.properties,
                        fact_ids=merge_unique([], edge.fact_ids),
                        source_ids=merge_unique([], edge.source_ids),
                    )
                )
            else:
                if (record.out_id, record.in_id, record.predicate_id) != (edge.out_id, edge.in_id, edge.predicate_id):
                    raise GraphIntegrityError(f"Edge id '{edge.id}' is already used by a different relationship.")
                record.properties = merge_properties(record.properties or {}, edge.properties)
                record.fact_ids = merge_unique(record.fact_ids or [], edge.fact_ids)
                record.source_ids = merge_unique(record.source_ids or [], edge.source_ids)
        self.session.flush()
        return len(edges)

    # ------------------------------------------------------------------ reads

    def get_vertex(self, graph_id: str, vertex_id: str) -> GraphVertex | None:
        record = self.session.get(GraphVertexRecord, (graph_id, vertex_id))
        return _vertex(record) if record else None

    def get_edge(self, graph_id: str, edge_id: str) -> GraphEdge | None:
        record = self.session.get(GraphEdgeRecord, (graph_id, edge_id))
        return _edge(record) if record else None

    def fetch_graph(self, graph_id: str, *, limit: int) -> GraphData:
        total = self.session.scalar(
            select(func.count()).select_from(GraphVertexRecord).where(GraphVertexRecord.graph_id == graph_id)
        ) or 0
        vertices = [
            _vertex(r)
            for r in self.session.scalars(
                select(GraphVertexRecord)
                .where(GraphVertexRecord.graph_id == graph_id)
                .order_by(GraphVertexRecord.label, GraphVertexRecord.name, GraphVertexRecord.id)
                .limit(limit)
            )
        ]
        ids = {v.id for v in vertices}
        edges = [
            _edge(r)
            for r in self.session.scalars(
                select(GraphEdgeRecord).where(GraphEdgeRecord.graph_id == graph_id).order_by(GraphEdgeRecord.id)
            )
            if r.out_id in ids and r.in_id in ids
        ]
        return GraphData(vertices=vertices, edges=edges, truncated=total > len(vertices))

    def search_vertices(
        self, graph_id: str, text: str, *, label: str | None = None, limit: int = 20
    ) -> list[GraphVertex]:
        pattern = f"%{text.strip().lower()}%"
        stmt = select(GraphVertexRecord).where(GraphVertexRecord.graph_id == graph_id)
        if text.strip():
            stmt = stmt.where(
                or_(func.lower(GraphVertexRecord.name).like(pattern), func.lower(GraphVertexRecord.id).like(pattern))
            )
        if label:
            stmt = stmt.where(GraphVertexRecord.label == label)
        stmt = stmt.order_by(GraphVertexRecord.name).limit(limit)
        return [_vertex(r) for r in self.session.scalars(stmt)]

    def edges_of(self, graph_id: str, vertex_id: str) -> list[GraphEdge]:
        stmt = (
            select(GraphEdgeRecord)
            .where(
                GraphEdgeRecord.graph_id == graph_id,
                or_(GraphEdgeRecord.out_id == vertex_id, GraphEdgeRecord.in_id == vertex_id),
            )
            .order_by(GraphEdgeRecord.label, GraphEdgeRecord.id)
        )
        return [_edge(r) for r in self.session.scalars(stmt)]

    def neighborhood(self, graph_id: str, vertex_id: str, *, depth: int = 1, limit: int = 200) -> GraphData:
        start = self.get_vertex(graph_id, vertex_id)
        if start is None:
            return GraphData(vertices=[], edges=[])
        vertices: dict[str, GraphVertex] = {start.id: start}
        edges: dict[str, GraphEdge] = {}
        queue: deque[tuple[str, int]] = deque([(start.id, 0)])
        truncated = False
        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            for edge in self.edges_of(graph_id, current):
                other = edge.in_id if edge.out_id == current else edge.out_id
                if other not in vertices:
                    if len(vertices) >= limit:
                        truncated = True
                        continue
                    neighbour = self.get_vertex(graph_id, other)
                    if neighbour is None:
                        continue
                    vertices[other] = neighbour
                    queue.append((other, level + 1))
                edges[edge.id] = edge
        return GraphData(vertices=list(vertices.values()), edges=list(edges.values()), truncated=truncated)

    def provenance(self, graph_id: str, element_id: str) -> list[str]:
        vertex = self.session.get(GraphVertexRecord, (graph_id, element_id))
        if vertex is not None:
            return list(vertex.fact_ids or [])
        edge = self.session.get(GraphEdgeRecord, (graph_id, element_id))
        return list(edge.fact_ids or []) if edge is not None else []

    def counts(self, graph_id: str) -> tuple[int, int]:
        vertices = self.session.scalar(
            select(func.count()).select_from(GraphVertexRecord).where(GraphVertexRecord.graph_id == graph_id)
        )
        edges = self.session.scalar(
            select(func.count()).select_from(GraphEdgeRecord).where(GraphEdgeRecord.graph_id == graph_id)
        )
        return int(vertices or 0), int(edges or 0)
