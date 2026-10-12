"""In-memory :class:`GraphStore` read model with the exact read semantics of ``SqlGraphStore``.

Used to serve graph-explorer reads from graphs fetched out of a deployment target (for example
the RDF read back from Oxigraph or a SPARQL endpoint), so the explorer behaves identically on
every target. Ordering rules mirror the SQL store: vertices by (label, name, id), edges by id,
edges of a vertex by (label, id), search results by name.
"""

from collections import deque
from collections.abc import Iterable, Sequence

from app.modules.graph.store import GraphData, GraphEdge, GraphVertex


class ReadOnlyGraphError(RuntimeError):
    pass


class MemoryGraphStore:
    def __init__(self, name: str, graph_id: str, vertices: Iterable[GraphVertex], edges: Iterable[GraphEdge]) -> None:
        self.name = name
        self.graph_id = graph_id
        self.vertices = {v.id: v for v in vertices}
        self.edges = {e.id: e for e in edges}
        self._edges_by_vertex: dict[str, list[GraphEdge]] = {}
        for edge in sorted(self.edges.values(), key=lambda e: (e.label, e.id)):
            self._edges_by_vertex.setdefault(edge.out_id, []).append(edge)
            if edge.in_id != edge.out_id:
                self._edges_by_vertex.setdefault(edge.in_id, []).append(edge)

    def _scoped(self, graph_id: str) -> bool:
        return graph_id == self.graph_id

    def upsert_vertices(self, graph_id: str, vertices: Sequence[GraphVertex]) -> int:
        raise ReadOnlyGraphError("Deployment reads are read-only.")

    def upsert_edges(self, graph_id: str, edges: Sequence[GraphEdge]) -> int:
        raise ReadOnlyGraphError("Deployment reads are read-only.")

    def get_vertex(self, graph_id: str, vertex_id: str) -> GraphVertex | None:
        return self.vertices.get(vertex_id) if self._scoped(graph_id) else None

    def get_edge(self, graph_id: str, edge_id: str) -> GraphEdge | None:
        return self.edges.get(edge_id) if self._scoped(graph_id) else None

    def fetch_graph(self, graph_id: str, *, limit: int) -> GraphData:
        if not self._scoped(graph_id):
            return GraphData(vertices=[], edges=[])
        ordered = sorted(self.vertices.values(), key=lambda v: (v.label, v.name, v.id))
        vertices = ordered[:limit]
        ids = {v.id for v in vertices}
        edges = [e for e in sorted(self.edges.values(), key=lambda e: e.id) if e.out_id in ids and e.in_id in ids]
        return GraphData(vertices=vertices, edges=edges, truncated=len(ordered) > len(vertices))

    def search_vertices(self, graph_id: str, text: str, *, label: str | None = None, limit: int = 20) -> list[GraphVertex]:
        if not self._scoped(graph_id):
            return []
        needle = text.strip().lower()
        found = [
            v
            for v in self.vertices.values()
            if (not needle or needle in v.name.lower() or needle in v.id.lower()) and (not label or v.label == label)
        ]
        return sorted(found, key=lambda v: v.name)[:limit]

    def edges_of(self, graph_id: str, vertex_id: str) -> list[GraphEdge]:
        return list(self._edges_by_vertex.get(vertex_id, [])) if self._scoped(graph_id) else []

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
        if not self._scoped(graph_id):
            return []
        element = self.vertices.get(element_id) or self.edges.get(element_id)
        return list(element.fact_ids) if element is not None else []

    def counts(self, graph_id: str) -> tuple[int, int]:
        return (len(self.vertices), len(self.edges)) if self._scoped(graph_id) else (0, 0)
