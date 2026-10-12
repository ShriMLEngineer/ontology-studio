"""Unit tests: graph store idempotency/isolation, entity resolution rules and literal validation."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.migrations import upgrade_database
from app.db.session import create_db_engine, create_session_factory
from app.modules.graph.sql_store import SqlGraphStore
from app.modules.graph.store import GraphEdge, GraphIntegrityError, GraphVertex
from app.modules.kg.canonical import LLM, STRUCTURED, Mention, SourceRef
from app.modules.kg.normalization import parse_literal
from app.modules.kg.ontology_view import OntologyView
from app.modules.kg.resolution import resolve_entities
from app.modules.ontology.domain import ClassDefinition
from app.modules.registry.snapshot import OntologySnapshot, SnapshotMetadata


@pytest.fixture
def session(tmp_path: Path) -> Session:
    url = f"sqlite:///{(tmp_path / 'graph.db').as_posix()}"
    upgrade_database(url)
    return create_session_factory(create_db_engine(url))()


def _vertex(vertex_id: str, fact: str, source: str = "doc-1") -> GraphVertex:
    return GraphVertex(id=vertex_id, label="Supplier", name=vertex_id, class_id="cls-supplier", fact_ids=[fact], source_ids=[source])


def test_graph_writes_are_idempotent_and_merge_provenance(session: Session) -> None:
    store = SqlGraphStore(session)
    store.upsert_vertices("build-1", [_vertex("a", "f1"), _vertex("b", "f2")])
    edge = GraphEdge(id="e1", label="supplies", predicate_id="op", out_id="a", in_id="b", fact_ids=["f3"], source_ids=["doc-1"])
    store.upsert_edges("build-1", [edge])
    store.upsert_vertices("build-1", [_vertex("a", "f1")])
    store.upsert_edges("build-1", [edge])
    assert store.counts("build-1") == (2, 1)
    assert store.provenance("build-1", "e1") == ["f3"]

    store.upsert_edges("build-1", [GraphEdge(id="e1", label="supplies", predicate_id="op", out_id="a", in_id="b", fact_ids=["f4"], source_ids=["doc-2"])])
    merged = store.get_edge("build-1", "e1")
    assert merged is not None and merged.fact_ids == ["f3", "f4"] and merged.source_ids == ["doc-1", "doc-2"]
    assert store.counts("build-1") == (2, 1)


def test_graph_scopes_are_isolated_and_integrity_is_enforced(session: Session) -> None:
    store = SqlGraphStore(session)
    store.upsert_vertices("build-1", [_vertex("a", "f1")])
    store.upsert_vertices("build-2", [_vertex("a", "g1"), _vertex("c", "g2")])
    assert store.counts("build-1") == (1, 0)
    assert store.provenance("build-1", "a") == ["f1"]
    with pytest.raises(GraphIntegrityError):
        store.upsert_edges("build-1", [GraphEdge(id="e", label="x", predicate_id="p", out_id="a", in_id="c")])
    store.upsert_edges("build-2", [GraphEdge(id="e", label="x", predicate_id="p", out_id="a", in_id="c")])
    with pytest.raises(GraphIntegrityError):
        store.upsert_edges("build-2", [GraphEdge(id="e", label="x", predicate_id="p", out_id="c", in_id="a")])
    hood = store.neighborhood("build-2", "a")
    assert {v.id for v in hood.vertices} == {"a", "c"} and len(hood.edges) == 1
    assert [v.id for v in store.search_vertices("build-2", "C")] == ["c"]


def _view() -> OntologyView:
    snapshot = OntologySnapshot(
        metadata=SnapshotMetadata(name="Test", namespace="https://example.com/t#", prefix="t"),
        classes=[
            ClassDefinition(id="cls-org", local_name="Organization", label="Organization"),
            ClassDefinition(id="cls-supplier", local_name="Supplier", label="Supplier", parent_ids=["cls-org"], aliases=["Vendor"]),
            ClassDefinition(id="cls-product", local_name="Product", label="Product"),
        ],
    )
    return OntologyView(snapshot, version_id="v1", version="1.0.0")


def _mention(key: str, *, class_id: str | None = "cls-supplier", identifier: str | None = None, label: str | None = None,
             aliases: list[str] | None = None, origin: str = STRUCTURED, reference_only: bool = False) -> Mention:
    return Mention(
        key=key, origin=origin, class_ref=class_id or "Auditor", class_id=class_id, identifier=identifier, key_namespace="",
        label=label, aliases=aliases or [], reference_only=reference_only,
        source=SourceRef(kind="record", document_id="d", document_name="d.csv", row_number=1),
    )


def test_resolution_merges_on_identifiers_and_flags_ambiguity() -> None:
    view = _view()
    result = resolve_entities(
        [
            _mention("m1", identifier="S-001", label="Northwind Ltd", aliases=["Northwind"]),
            _mention("m2", identifier=" s-001 ", reference_only=True),
            _mention("m3", identifier="S-002", label="Contoso Metals", aliases=["Contoso"]),
            _mention("m4", identifier="S-004", label="Contoso Packaging", aliases=["Contoso"]),
            _mention("m5", origin=LLM, label="Northwind"),
            _mention("m6", origin=LLM, label="Contoso"),
            _mention("m7", origin=LLM, class_id="cls-org", identifier="S-002", label="Contoso Metals GmbH"),
            _mention("m8", origin=LLM, label="Northwind Ltd.", class_id="cls-product"),
            _mention("m9", class_id=None, identifier="A-01"),
            _mention("m10", label="No id row"),
        ],
        view,
    )
    northwind = result.entity_of("m1")
    assert northwind is not None and result.entity_of("m2") is northwind and result.entity_of("m5") is northwind
    assert result.mention_method["m5"] == "alias"
    assert result.entity_of("m7") is result.entity_of("m3"), "compatible superclass + same key merges"
    ambiguous = result.entity_of("m6")
    assert ambiguous is not None and ambiguous.method == "ambiguous" and len(ambiguous.candidates) == 2
    assert result.entity_of("m8") is not northwind, "names never merge across incompatible classes"
    assert result.entity_of("m9").method == "unresolved_class"  # type: ignore[union-attr]
    assert result.entity_of("m10").method == "missing_identifier"  # type: ignore[union-attr]
    assert result.stats()["merged_mentions"] == 3, "m2, m5 and m7 merged into existing entities"


@pytest.mark.parametrize(
    ("value", "datatype", "expected"),
    [
        ("42", "integer", "42"),
        ("4.2", "integer", None),
        ("1,250.50", "decimal", "1250.50"),
        ("$12", "decimal", None),
        ("Yes", "boolean", "true"),
        ("2026-07-14", "date", "2026-07-14"),
        ("14/07/2026", "date", None),
        ("2026-07-14T10:00:00", "dateTime", "2026-07-14T10:00:00"),
        ("https://example.com/x", "anyURI", "https://example.com/x"),
        ("example.com", "anyURI", None),
        ("  ", "string", None),
    ],
)
def test_literal_validation(value: str, datatype: str, expected: str | None) -> None:
    valid, canonical, _ = parse_literal(value, datatype)
    assert valid is (expected is not None)
    assert canonical == expected
