"""Provider-independent property-graph storage interface.

The model deliberately mirrors the Apache TinkerPop / Gremlin property graph used by the enterprise
target (Azure Cosmos DB Gremlin API): vertices and directed edges have an id, a label and
properties, and every element belongs to a graph scope (``graph_id``) that maps naturally onto a
Cosmos partition key. Knowledge-graph services depend only on :class:`GraphStore`, never on a
concrete database.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


class GraphIntegrityError(RuntimeError):
    """Raised when a write would violate graph integrity (e.g. an edge to a missing vertex)."""


@dataclass
class GraphVertex:
    id: str
    label: str  # Gremlin vertex label: the ontology class local name
    name: str
    class_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    fact_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass
class GraphEdge:
    id: str
    label: str  # Gremlin edge label: the ontology object property local name
    predicate_id: str
    out_id: str  # subject vertex
    in_id: str  # object vertex
    properties: dict[str, Any] = field(default_factory=dict)
    fact_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass
class GraphData:
    vertices: list[GraphVertex]
    edges: list[GraphEdge]
    truncated: bool = False


class GraphStore(Protocol):
    """Operations required by the knowledge-graph pipeline and the graph explorer.

    Writes are idempotent upserts keyed by stable element ids: writing the same element twice
    leaves one element whose provenance (fact ids, source ids) is the union of both writes.
    """

    name: str

    def upsert_vertices(self, graph_id: str, vertices: Sequence[GraphVertex]) -> int: ...

    def upsert_edges(self, graph_id: str, edges: Sequence[GraphEdge]) -> int: ...

    def get_vertex(self, graph_id: str, vertex_id: str) -> GraphVertex | None: ...

    def get_edge(self, graph_id: str, edge_id: str) -> GraphEdge | None: ...

    def fetch_graph(self, graph_id: str, *, limit: int) -> GraphData: ...

    def search_vertices(
        self, graph_id: str, text: str, *, label: str | None = None, limit: int = 20
    ) -> list[GraphVertex]: ...

    def edges_of(self, graph_id: str, vertex_id: str) -> list[GraphEdge]: ...

    def neighborhood(self, graph_id: str, vertex_id: str, *, depth: int = 1, limit: int = 200) -> GraphData: ...

    def provenance(self, graph_id: str, element_id: str) -> list[str]: ...

    def counts(self, graph_id: str) -> tuple[int, int]: ...


def merge_unique(existing: list[str], new: Sequence[str]) -> list[str]:
    return list(dict.fromkeys([*existing, *new]))


def merge_properties(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """List-valued properties are unioned; scalar properties take the newest value."""
    merged = dict(existing)
    for key, value in new.items():
        current = merged.get(key)
        if isinstance(current, list) and isinstance(value, list):
            merged[key] = list(dict.fromkeys([*current, *value]))
        else:
            merged[key] = value
    return merged
