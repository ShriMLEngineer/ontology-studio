"""External property-graph stores (Neo4j, Azure Cosmos DB Gremlin) behind the :class:`GraphStore` protocol.

A build is deployed to an external property graph *by replacing its scope*: every element carries
the build id as its scope, a redeployment first removes only that scope's elements and then writes
the projection, so re-deploying is exact and idempotent and data outside the scope is never touched.
The Graph Explorer reads the target through the same protocol the local SQL store implements, so
exploration is adapter independent.

System properties are namespaced with ``_ols_`` so ontology attributes named ``id`` or ``name`` can
never collide with them.
"""

import json
import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.secrets import get_secret
from app.modules.graph.projection import PropertyGraphProjection
from app.modules.graph.store import (
    GraphData,
    GraphEdge,
    GraphIntegrityError,
    GraphVertex,
)
from app.modules.graph.targets.errors import DeploymentError

PREFIX = "_ols_"
BATCH = 500


@dataclass(frozen=True)
class PropertyTarget:
    """Resolved, in-memory connection settings of a registered property-graph database."""

    kind: str
    config: dict[str, Any]
    secret_env: str | None
    allow_private: bool = True

    @property
    def secret(self) -> str | None:
        return get_secret(self.secret_env)


# ---------------------------------------------------------------------------------- value encoding


def _scalar(value: Any) -> Any:
    if isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value if -(2**63) <= value < 2**63 else str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def encode_value(value: Any) -> Any:
    """A property value storable by a property graph: a primitive or a homogeneous list of primitives."""
    if isinstance(value, list | tuple | set):
        items = [_scalar(v) for v in value if v is not None]
        kinds = {type(v) for v in items}
        if len(kinds) > 1:
            if kinds <= {int, float}:
                return [float(v) for v in items]
            return [v if isinstance(v, str) else json.dumps(v) for v in items]
        return items
    return _scalar(value)


def encode_properties(properties: dict[str, Any], *, reserved: Iterable[str] = ()) -> dict[str, Any]:
    """Drop null values and rename keys that collide with system or store-reserved names."""
    blocked = set(reserved)
    encoded: dict[str, Any] = {}
    for key, value in properties.items():
        if value is None:
            continue
        name = str(key)
        if name.startswith(PREFIX) or name in blocked:
            name = f"attr_{name}"
        encoded[name] = encode_value(value)
    return encoded


def json_list(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(v) for v in values))


# ---------------------------------------------------------------------------------- store base


class ExternalPropertyGraphStore(Protocol):
    name: str

    def replace_scope(self, scope: str, vertices: Sequence[GraphVertex], edges: Sequence[GraphEdge]) -> None: ...

    def clear_scope(self, scope: str) -> None: ...

    def close(self) -> None: ...


class ReadableGraphStore:
    """Shared explorer semantics for external property-graph stores.

    Subclasses implement the primitive reads; neighbourhood expansion and provenance lookups are
    expressed once in terms of them, exactly as the local SQL store does.
    """

    name = "external"

    # ---- primitives implemented by adapters
    def get_vertex(self, graph_id: str, vertex_id: str) -> GraphVertex | None:
        raise NotImplementedError

    def get_edge(self, graph_id: str, edge_id: str) -> GraphEdge | None:
        raise NotImplementedError

    def edges_of(self, graph_id: str, vertex_id: str) -> list[GraphEdge]:
        raise NotImplementedError

    def fetch_graph(self, graph_id: str, *, limit: int) -> GraphData:
        raise NotImplementedError

    def search_vertices(
        self, graph_id: str, text: str, *, label: str | None = None, limit: int = 20
    ) -> list[GraphVertex]:
        raise NotImplementedError

    def counts(self, graph_id: str) -> tuple[int, int]:
        raise NotImplementedError

    # ---- writes: external targets are written by deployments only
    def upsert_vertices(self, graph_id: str, vertices: Sequence[GraphVertex]) -> int:
        raise GraphIntegrityError(f"{self.name} graphs are written only by deployments, not by incremental upserts.")

    def upsert_edges(self, graph_id: str, edges: Sequence[GraphEdge]) -> int:
        raise GraphIntegrityError(f"{self.name} graphs are written only by deployments, not by incremental upserts.")

    # ---- derived reads
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
        vertex = self.get_vertex(graph_id, element_id)
        if vertex is not None:
            return list(vertex.fact_ids)
        edge = self.get_edge(graph_id, element_id)
        return list(edge.fact_ids) if edge is not None else []

    def close(self) -> None:  # pragma: no cover - overridden where a connection is held
        return None


# ---------------------------------------------------------------------------------- factory


def property_graph_store(target: PropertyTarget) -> Any:
    """The store for a registered property-graph provider (imports the driver lazily)."""
    if target.kind == "neo4j":
        from app.modules.graph.targets.neo4j_store import Neo4jGraphStore

        return Neo4jGraphStore.connect(target)
    if target.kind == "cosmos-gremlin":
        from app.modules.graph.targets.gremlin_store import CosmosGremlinStore

        return CosmosGremlinStore.connect(target)
    raise DeploymentError(f"'{target.kind}' is not an external property-graph provider.")


def close_all_connections() -> None:
    """Release pooled driver connections (application shutdown and tests)."""
    from app.modules.graph.targets import gremlin_store, neo4j_store

    neo4j_store.close_drivers()
    gremlin_store.close_clients()


def projection_counts(projection: PropertyGraphProjection) -> dict[str, int]:
    return {"vertices": len(projection.vertices), "edges": len(projection.edges)}
