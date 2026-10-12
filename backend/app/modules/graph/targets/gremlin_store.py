"""Azure Cosmos DB for Apache Gremlin: connection probe and property-graph store.

Follows the documented client configuration: ``wss://<account>.gremlin.cosmos.azure.com:443/``,
traversal source ``g``, user name ``/dbs/<database>/colls/<graph>``, the account key as password and
the GraphSON 2 serializer. Cosmos specifics honoured here:

* every vertex carries the graph's partition-key property; a build's scope (its id) is the
  partition-key value, so a build occupies one logical partition and is addressed with
  ``g.V([partitionKey, id])``;
* values always travel as bindings; labels and property keys are restricted to ``[A-Za-z0-9_]`` so a
  script contains no user-controlled text;
* throttled requests (HTTP 429) are retried after the service's ``x-ms-retry-after-ms`` hint;
* Cosmos stores a vertex property as a list of values, so multi-valued ontology attributes are kept
  exactly in a JSON property and, where single-valued, also as a plain queryable property.

This adapter is covered by tests against a scripted Gremlin client. It has not been run against a live
Cosmos DB account or emulator.
"""

import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Sequence
from typing import Any

from app.core.net_safety import EndpointError, assert_reachable_target
from app.modules.graph.store import GraphData, GraphEdge, GraphVertex
from app.modules.graph.targets import ConnectionResult
from app.modules.graph.targets.errors import DeploymentError
from app.modules.graph.targets.property_graph import (
    PREFIX,
    PropertyTarget,
    ReadableGraphStore,
    encode_properties,
    json_list,
)

logger = logging.getLogger(__name__)

WINDOW = 8
MAX_ATTEMPTS = 6
EDGE_FETCH_LIMIT = 20_000
SEARCH_FETCH_LIMIT = 5_000
_UNSAFE = re.compile(r"[^A-Za-z0-9_]")
_BAD_ID = re.compile(r"[/\\?#]")


def literal(name: str, fallback: str = "x") -> str:
    """A Gremlin string literal built from a sanitised identifier (never from raw user text)."""
    cleaned = _UNSAFE.sub("_", name) or fallback
    return f"'{cleaned}'"


class _Settings:
    def __init__(self, target: PropertyTarget) -> None:
        config = target.config
        secret = target.secret
        if not secret:
            raise DeploymentError(
                f"Environment variable {target.secret_env or '(not configured)'} is not set on the server."
            )
        endpoint = str(config.get("endpoint") or "")
        self.scheme = "ws" if endpoint.startswith("ws://") else "wss"
        self.host = endpoint.removeprefix("ws://")
        self.port = int(config.get("port") or 443)
        self.database = str(config.get("database") or "")
        self.graph = str(config.get("graph") or "")
        self.partition_key = str(config.get("partition_key_path") or "/pk").lstrip("/")
        self.timeout = float(config.get("timeout_seconds") or 30)
        self.key = secret
        self.allow_private = target.allow_private

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}/"

    @property
    def username(self) -> str:
        return f"/dbs/{self.database}/colls/{self.graph}"


def describe_error(error: BaseException) -> str:
    """A provider-specific message; never includes the key or the connection URL."""
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    name = error.__class__.__name__
    if status in (401, 403):
        return "Cosmos DB rejected the account key or the key has no access to this graph."
    if status == 404:
        return "The Cosmos DB database or graph was not found."
    if status == 408 or "timeout" in name.lower() or isinstance(error, TimeoutError):
        return "Cosmos DB did not respond in time."
    if status == 429:
        return "Cosmos DB throttled the request (request units exhausted). Try again or raise the graph's throughput."
    if isinstance(status, int) and status >= 500:
        return f"Cosmos DB is temporarily unavailable (status {status})."
    message = str(getattr(error, "status_message", "") or "").replace("\n", " ").strip()
    if status and message:
        return f"Cosmos DB returned status {status}: {message[:200]}"
    if status:
        return f"Cosmos DB returned status {status}."
    return "Could not connect to the Cosmos DB Gremlin endpoint (unreachable, TLS failure or protocol error)."


def _create_client(settings: _Settings) -> Any:
    try:
        assert_reachable_target(settings.host, settings.port, allow_private=settings.allow_private)
    except EndpointError as error:
        raise DeploymentError(str(error)) from error
    from gremlin_python.driver import client, serializer

    return client.Client(
        settings.url,
        "g",
        username=settings.username,
        password=settings.key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
        pool_size=2,
        max_workers=2,
        read_timeout=settings.timeout,
        write_timeout=settings.timeout,
    )


_clients: dict[tuple[str, str, str, str], Any] = {}
_clients_lock = threading.Lock()


def _client_key(settings: _Settings) -> tuple[str, str, str, str]:
    return settings.url, settings.username, hashlib.sha256(settings.key.encode()).hexdigest(), str(settings.timeout)


def close_clients() -> None:
    with _clients_lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        try:
            client.close()
        except Exception:
            logger.debug("Closing a Gremlin client failed", exc_info=True)


def _is_gremlin_error(error: BaseException) -> bool:
    return error.__class__.__name__ == "GremlinServerError"


# ---------------------------------------------------------------------------------- probe


def check_cosmos(config: dict[str, Any], secret_env: str | None, *, allow_private: bool = True) -> ConnectionResult:
    """A read-only traversal (``g.V().limit(1)``) over an authenticated connection."""
    started = time.perf_counter()

    def finish(ok: bool, message: str, details: dict[str, Any] | None = None) -> ConnectionResult:
        return ConnectionResult(ok, message, int((time.perf_counter() - started) * 1000), details or {})

    try:
        settings = _Settings(PropertyTarget("cosmos-gremlin", config, secret_env, allow_private))
        client = _create_client(settings)
    except DeploymentError as error:
        return finish(False, str(error))
    except ImportError:
        return finish(False, "The gremlinpython driver is not installed on the server.")
    try:
        client.submit("g.V().limit(1)").all().result()
    except Exception as error:  # noqa: BLE001 - mapped to a sanitised provider-specific message
        return finish(False, describe_error(error))
    finally:
        try:
            client.close()
        except Exception:
            logger.debug("Closing the probe client failed", exc_info=True)
    return finish(
        True,
        f"Connected to Cosmos DB Gremlin; a read-only traversal succeeded on {settings.database}/{settings.graph}.",
        {"database": settings.database, "graph": settings.graph, "partition_key": settings.partition_key},
    )


# ---------------------------------------------------------------------------------- decoding


def _first(value: Any) -> Any:
    """Cosmos returns vertex properties as ``[{"id": ..., "value": ...}]``; edge properties as plain values."""
    if isinstance(value, list):
        if value and isinstance(value[0], dict) and "value" in value[0]:
            return value[0]["value"]
        return value[0] if value else None
    return value


def _properties_of(document: dict[str, Any]) -> dict[str, Any]:
    raw = document.get("properties") or {}
    if not isinstance(raw, dict):
        raise DeploymentError("Cosmos DB returned an unexpected element shape.")
    return {key: _first(value) for key, value in raw.items()}


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default if value is None else value


def vertex_from(document: Any, partition_key: str) -> GraphVertex:
    if not isinstance(document, dict) or "id" not in document:
        raise DeploymentError("Cosmos DB returned an unexpected vertex shape.")
    props = _properties_of(document)
    attributes = _json(props.get("_ols_props"), None)
    if not isinstance(attributes, dict):
        skip = {"id", partition_key}
        attributes = {k: v for k, v in props.items() if not k.startswith(PREFIX) and k not in skip}
    return GraphVertex(
        id=str(document["id"]),
        label=str(document.get("label") or ""),
        name=str(props.get("_ols_name") or ""),
        class_id=str(props.get("_ols_class_id") or ""),
        properties=attributes,
        fact_ids=list(_json(props.get("_ols_facts"), [])),
        source_ids=list(_json(props.get("_ols_sources"), [])),
    )


def edge_from(document: Any) -> GraphEdge:
    if not isinstance(document, dict) or "id" not in document:
        raise DeploymentError("Cosmos DB returned an unexpected edge shape.")
    props = _properties_of(document)
    attributes = _json(props.get("_ols_props"), {})
    return GraphEdge(
        id=str(props.get("_ols_id") or document["id"]),
        label=str(document.get("label") or ""),
        predicate_id=str(props.get("_ols_predicate_id") or ""),
        out_id=str(document.get("outV") or ""),
        in_id=str(document.get("inV") or ""),
        properties=attributes if isinstance(attributes, dict) else {},
        fact_ids=list(_json(props.get("_ols_facts"), [])),
        source_ids=list(_json(props.get("_ols_sources"), [])),
    )


# ---------------------------------------------------------------------------------- store


class CosmosGremlinStore(ReadableGraphStore):
    name = "cosmos-gremlin"

    def __init__(self, client: Any, partition_key: str, *, sleep: Any = time.sleep) -> None:
        self.client = client
        self.pk = partition_key
        self._sleep = sleep

    @classmethod
    def connect(cls, target: PropertyTarget) -> "CosmosGremlinStore":
        settings = _Settings(target)
        key = _client_key(settings)
        with _clients_lock:
            client = _clients.get(key)
            if client is None:
                client = _clients[key] = _create_client(settings)
        return cls(client, settings.partition_key)

    def close(self) -> None:  # the client is pooled; see close_clients()
        return None

    # ------------------------------------------------------------------ execution

    def _run(self, query: str, bindings: dict[str, Any] | None = None) -> list[Any]:
        last: BaseException | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                return list(self.client.submit(query, bindings or {}).all().result())
            except Exception as error:  # noqa: BLE001 - classified below
                last = error
                if _is_gremlin_error(error) and getattr(error, "status_code", None) == 429 and attempt < MAX_ATTEMPTS - 1:
                    attributes = getattr(error, "status_attributes", None) or {}
                    delay_ms = float(attributes.get("x-ms-retry-after-ms", 0) or 0) or 200 * 2**attempt
                    self._sleep(min(delay_ms, 5000) / 1000)
                    continue
                break
        assert last is not None
        raise DeploymentError(describe_error(last)) from last

    def _run_many(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        for start in range(0, len(items), WINDOW):
            window = items[start : start + WINDOW]
            futures = [self.client.submit_async(query, bindings) for query, bindings in window]
            for (query, bindings), future in zip(window, futures, strict=True):
                try:
                    future.result().all().result()
                except Exception:  # noqa: BLE001 - retried through _run, which maps the error
                    self._run(query, bindings)

    # ------------------------------------------------------------------ deployment

    def clear_scope(self, scope: str) -> None:
        pk = literal(self.pk, "pk")
        while True:
            self._run(f"g.V().has({pk}, s_pk).limit(100).drop()", {"s_pk": scope})
            if not self._run(f"g.V().has({pk}, s_pk).limit(1)", {"s_pk": scope}):
                return

    def _vertex_query(self, scope: str, vertex: GraphVertex) -> tuple[str, dict[str, Any]]:
        if not vertex.id or _BAD_ID.search(vertex.id):
            raise DeploymentError(f"Vertex id '{vertex.id[:60]}' is not valid for Cosmos DB (empty or contains / \\ ? #).")
        pk = literal(self.pk, "pk")
        encoded = encode_properties(vertex.properties, reserved={"id", "label", self.pk})
        flat = {
            _UNSAFE.sub("_", key): value[0] if isinstance(value, list) else value
            for key, value in encoded.items()
            if not isinstance(value, list) or (len(value) == 1 and not isinstance(value[0], list))
        }
        bindings: dict[str, Any] = {
            "v_id": vertex.id, "v_pk": scope, "s_name": vertex.name, "s_class": vertex.class_id,
            "s_props": json.dumps(vertex.properties, ensure_ascii=False, default=str),
            "s_facts": json.dumps(json_list(vertex.fact_ids)),
            "s_sources": json.dumps(json_list(vertex.source_ids)),
        }
        query = (
            f"g.addV({literal(vertex.label, 'vertex')}).property('id', v_id).property({pk}, v_pk)"
            ".property('_ols_name', s_name).property('_ols_class_id', s_class).property('_ols_props', s_props)"
            ".property('_ols_facts', s_facts).property('_ols_sources', s_sources)"
        )
        reserved = {"id", "label", self.pk}
        for index, (key, value) in enumerate(flat.items()):
            if key in reserved or key.startswith(PREFIX) or value is None:
                continue
            bindings[f"p{index}"] = value
            query += f".property({literal(key)}, p{index})"
        return query, bindings

    def _edge_query(self, scope: str, edge: GraphEdge) -> tuple[str, dict[str, Any]]:
        query = (
            f"g.V([e_pk, e_out]).addE({literal(edge.label, 'edge')}).to(g.V([e_pk, e_in]))"
            ".property('_ols_id', e_id).property('_ols_predicate_id', e_pred).property('_ols_props', e_props)"
            ".property('_ols_facts', e_facts).property('_ols_sources', e_sources)"
        )
        bindings = {
            "e_pk": scope, "e_out": edge.out_id, "e_in": edge.in_id, "e_id": edge.id, "e_pred": edge.predicate_id,
            "e_props": json.dumps(edge.properties, ensure_ascii=False, default=str),
            "e_facts": json.dumps(json_list(edge.fact_ids)), "e_sources": json.dumps(json_list(edge.source_ids)),
        }
        return query, bindings

    def replace_scope(self, scope: str, vertices: Sequence[GraphVertex], edges: Sequence[GraphEdge]) -> None:
        self.clear_scope(scope)
        self._run_many([self._vertex_query(scope, vertex) for vertex in vertices])
        self._run_many([self._edge_query(scope, edge) for edge in edges])

    # ------------------------------------------------------------------ reads

    def counts(self, graph_id: str) -> tuple[int, int]:
        pk = literal(self.pk, "pk")
        vertices = self._run(f"g.V().has({pk}, s_pk).count()", {"s_pk": graph_id})
        edges = self._run(f"g.V().has({pk}, s_pk).outE().count()", {"s_pk": graph_id})
        return int(vertices[0]), int(edges[0])

    def get_vertex(self, graph_id: str, vertex_id: str) -> GraphVertex | None:
        rows = self._run("g.V([v_pk, v_id])", {"v_pk": graph_id, "v_id": vertex_id})
        return vertex_from(rows[0], self.pk) if rows else None

    def get_edge(self, graph_id: str, edge_id: str) -> GraphEdge | None:
        pk = literal(self.pk, "pk")
        rows = self._run(f"g.V().has({pk}, s_pk).outE().has('_ols_id', e_id).limit(1)", {"s_pk": graph_id, "e_id": edge_id})
        return edge_from(rows[0]) if rows else None

    def fetch_graph(self, graph_id: str, *, limit: int) -> GraphData:
        pk = literal(self.pk, "pk")
        total, _ = self.counts(graph_id)
        rows = self._run(f"g.V().has({pk}, s_pk).limit(lim)", {"s_pk": graph_id, "lim": limit})
        vertices = sorted(
            (vertex_from(row, self.pk) for row in rows), key=lambda v: (v.label, v.name, v.id)
        )
        ids = {v.id for v in vertices}
        edges: list[GraphEdge] = []
        if vertices:
            edge_rows = self._run(f"g.V().has({pk}, s_pk).outE().limit(lim)", {"s_pk": graph_id, "lim": EDGE_FETCH_LIMIT})
            edges = sorted(
                (e for e in map(edge_from, edge_rows) if e.out_id in ids and e.in_id in ids), key=lambda e: e.id
            )
        return GraphData(vertices=vertices, edges=edges, truncated=total > len(vertices))

    def search_vertices(
        self, graph_id: str, text: str, *, label: str | None = None, limit: int = 20
    ) -> list[GraphVertex]:
        # Case-insensitive substring search is not a portable Gremlin predicate, so it runs on the fetched scope.
        pk = literal(self.pk, "pk")
        rows = self._run(f"g.V().has({pk}, s_pk).limit(lim)", {"s_pk": graph_id, "lim": SEARCH_FETCH_LIMIT})
        needle = text.strip().lower()
        matches = [
            v for v in (vertex_from(row, self.pk) for row in rows)
            if (label is None or v.label == label) and (not needle or needle in v.name.lower() or needle in v.id.lower())
        ]
        return sorted(matches, key=lambda v: v.name)[:limit]

    def edges_of(self, graph_id: str, vertex_id: str) -> list[GraphEdge]:
        rows = self._run("g.V([v_pk, v_id]).bothE()", {"v_pk": graph_id, "v_id": vertex_id})
        unique = {e.id: e for e in map(edge_from, rows)}
        return sorted(unique.values(), key=lambda e: (e.label, e.id))
