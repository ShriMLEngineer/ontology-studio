import os
import stat
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.modules.registry.diff import bump_version, diff_snapshots, parse_semver
from app.modules.registry.models import ImmutableVersionError, OntologyVersion
from app.modules.registry.rdf import snapshot_to_graph
from app.modules.registry.snapshot import OntologySnapshot, SnapshotMetadata, build_snapshot, content_hash
from app.modules.ontology.domain import OntologySchema
from app.modules.seed import supply_chain
from tests.conftest import error_code, start_run

SME = "Dana SME"
NS = "https://example.com/ontology/supply-chain#"


def _seed_snapshot() -> OntologySnapshot:
    content = supply_chain.draft_content()
    schema = OntologySchema(
        namespace=NS,
        prefix="sc",
        classes=content["classes"],
        object_properties=content["object_properties"],
        datatype_properties=content["datatype_properties"],
    )
    return build_snapshot(SnapshotMetadata(**supply_chain.ONTOLOGY), schema)


def _seeded(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    project = client.get("/api/projects").json()[0]
    return project, client.get(f"/api/projects/{project['id']}/ontologies").json()[0]


def _publish(client: TestClient, ontology_id: str, **body: Any) -> Any:
    return client.post(f"/api/ontologies/{ontology_id}/versions", json={"published_by": SME, **body})


# ------------------------------------------------------------------------------ pure functions


def test_semver_helpers() -> None:
    assert parse_semver("1.2.3") == (1, 2, 3) and parse_semver("1.2") is None and parse_semver("01.2.3") is None
    assert bump_version(None, "patch") == "1.0.0"
    assert bump_version("1.2.3", "major") == "2.0.0"
    assert bump_version("1.2.3", "minor") == "1.3.0"
    assert bump_version("1.2.3", "patch") == "1.2.4"


def test_snapshot_hash_is_order_independent() -> None:
    snapshot = _seed_snapshot()
    shuffled = snapshot.model_copy(update={"classes": list(reversed(snapshot.classes))})
    assert content_hash(build_snapshot(snapshot.metadata, shuffled.to_schema())) == content_hash(snapshot)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda s: s.classes[0].__setattr__("description", "Changed"), "patch"),
        (lambda s: s.classes[0].aliases.append("Firm"), "patch"),
        (lambda s: s.datatype_properties[0].__setattr__("required", not s.datatype_properties[0].required), "minor"),
        (lambda s: s.classes.append(s.classes[0].model_copy(update={"id": "cls-new", "local_name": "New", "label": "New"})), "minor"),
        (lambda s: s.classes[0].__setattr__("local_name", "Org"), "major"),
        (lambda s: s.object_properties[0].__setattr__("range_id", "cls-location"), "major"),
        (lambda s: s.datatype_properties.pop(), "major"),
    ],
)
def test_diff_suggests_semantic_version_bumps(mutate: Any, expected: str) -> None:
    base = _seed_snapshot()
    target = base.model_copy(deep=True)
    mutate(target)
    diff = diff_snapshots(base, target, from_label="a", to_label="b")
    assert diff.has_changes and diff.suggested_bump == expected
    assert (expected == "major") == bool(diff.breaking_changes)


def test_diff_of_identical_snapshots_is_empty() -> None:
    diff = diff_snapshots(_seed_snapshot(), _seed_snapshot(), from_label="a", to_label="b")
    assert not diff.has_changes and diff.suggested_bump == "none"


def test_turtle_export_round_trips_with_owl_semantics() -> None:
    snapshot = _seed_snapshot()
    graph = Graph().parse(
        data=snapshot_to_graph(snapshot, version="1.0.0").serialize(format="turtle"), format="turtle"
    )
    sc = lambda name: URIRef(NS + name)  # noqa: E731
    onto = URIRef("https://example.com/ontology/supply-chain")
    assert (onto, RDF.type, OWL.Ontology) in graph
    assert (onto, OWL.versionInfo, Literal("1.0.0")) in graph
    assert len(set(graph.subjects(RDF.type, OWL.Class))) == len(snapshot.classes)
    assert (sc("Supplier"), RDFS.subClassOf, sc("Organization")) in graph
    assert (sc("Supplier"), SKOS.altLabel, Literal("Vendor")) in graph
    assert (sc("Supplier"), DCTERMS.identifier, Literal("cls-supplier")) in graph
    assert (sc("supplies"), RDFS.domain, sc("Supplier")) in graph
    assert (sc("supplies"), RDFS.range, sc("Product")) in graph
    assert (sc("sku"), RDFS.range, XSD.string) in graph
    assert (sc("sku"), RDF.type, OWL.FunctionalProperty) in graph
    restrictions = [
        r for r in graph.objects(sc("Product"), RDFS.subClassOf) if (r, OWL.onProperty, sc("sku")) in graph
    ]
    assert restrictions and (restrictions[0], OWL.minCardinality, Literal(1, datatype=XSD.nonNegativeInteger)) in graph


# ------------------------------------------------------------------------------ API


def test_publish_is_blocked_by_validation_errors(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    seeded_client.post(f"/api/ontologies/{ontology['id']}/datatype-properties", json={"label": "x", "domain_id": "cls-product"})
    seeded_client.patch(f"/api/ontologies/{ontology['id']}/datatype-properties/dp-sku", json={"local_name": "bad name"})

    preview = seeded_client.get(f"/api/ontologies/{ontology['id']}/publish-preview").json()
    assert preview["can_publish"] is False and preview["validation"]["error_count"] == 1
    assert preview["validation"]["blocking_issues"][0]["code"] == "LOCAL_NAME_INVALID"

    blocked = _publish(seeded_client, ontology["id"])
    assert blocked.status_code == 422 and error_code(blocked) == "PUBLISH_BLOCKED_BY_VALIDATION"
    assert seeded_client.get(f"/api/ontologies/{ontology['id']}/versions").json() == []


def test_publish_history_compare_and_export(seeded_client: TestClient, db_path: Path) -> None:
    project, ontology = _seeded(seeded_client)
    oid = ontology["id"]

    preview = seeded_client.get(f"/api/ontologies/{oid}/publish-preview").json()
    assert preview["can_publish"] and preview["suggested_version"] == "1.0.0" and preview["latest_version"] is None

    first = _publish(seeded_client, oid, release_notes="Initial governed release", expected_draft_revision=ontology["draft_revision"])
    assert first.status_code == 201, first.text
    v1 = first.json()
    assert v1["version"] == "1.0.0" and v1["sequence"] == 1 and v1["published_by"] == SME
    assert v1["validation_summary"]["is_valid"] is True
    assert {a["format"] for a in v1["artifacts"]} == {"json", "turtle", "rdfxml", "jsonld", "ntriples", "manifest"}
    assert v1["package_format"] == "ols-semantic/2" and v1["snapshot_format"] == "ols.ontology-snapshot/2"
    assert seeded_client.get(f"/api/ontologies/{oid}").json()["latest_version"]["version"] == "1.0.0"

    artifact_dir = db_path.parent / "artifacts" / oid / v1["id"]
    files = list(artifact_dir.iterdir())
    assert len(files) == 6 and all(not os.access(f, os.W_OK) for f in files), "artifacts are read-only"

    again = _publish(seeded_client, oid)
    assert again.status_code == 409 and error_code(again) == "NOTHING_TO_PUBLISH"

    seeded_client.post(f"/api/ontologies/{oid}/classes", json={"label": "Inventory Lot", "description": "A lot."})
    preview = seeded_client.get(f"/api/ontologies/{oid}/publish-preview").json()
    assert preview["suggested_version"] == "1.1.0" and preview["diff"]["summary"]["class"]["added"] == 1

    stale = _publish(seeded_client, oid, expected_draft_revision=ontology["draft_revision"])
    assert stale.status_code == 409 and error_code(stale) == "DRAFT_REVISION_CONFLICT"
    not_increasing = _publish(seeded_client, oid, version="1.0.0")
    assert not_increasing.status_code == 422 and error_code(not_increasing) == "VERSION_NOT_INCREASING"
    invalid = _publish(seeded_client, oid, version="v2")
    assert invalid.status_code == 422 and error_code(invalid) == "INVALID_VERSION"

    v2 = _publish(seeded_client, oid, bump="minor").json()
    assert v2["version"] == "1.1.0" and v2["previous_version_id"] == v1["id"]
    assert v2["change_summary"]["class"]["added"] == 1

    history = seeded_client.get(f"/api/ontologies/{oid}/versions").json()
    assert [v["version"] for v in history] == ["1.1.0", "1.0.0"]

    diff = seeded_client.get(f"/api/ontologies/{oid}/compare", params={"base": v1["id"], "target": v2["id"]}).json()
    assert diff["from_label"] == "v1.0.0" and diff["to_label"] == "v1.1.0"
    assert [(e["change"], e["label"]) for e in diff["elements"]] == [("added", "Inventory Lot")]
    assert seeded_client.get(f"/api/ontologies/{oid}/compare", params={"base": v2["id"]}).json()["has_changes"] is False

    turtle = seeded_client.get(f"/api/ontologies/{oid}/versions/{v2['id']}/export", params={"format": "turtle"})
    assert turtle.status_code == 200 and turtle.headers["content-type"].startswith("text/turtle")
    assert 'filename="sc-1.1.0.ttl"' in turtle.headers["content-disposition"]
    graph = Graph().parse(data=turtle.text, format="turtle")
    assert (URIRef(NS + "InventoryLot"), RDF.type, OWL.Class) in graph
    exported = seeded_client.get(f"/api/ontologies/{oid}/versions/{v1['id']}/export", params={"format": "json"}).json()
    assert exported["version"] == "1.0.0" and exported["content_hash"] == v1["content_hash"]
    assert len(exported["snapshot"]["classes"]) == ontology["stats"]["class_count"]

    activity = seeded_client.get(f"/api/projects/{project['id']}/activity?limit=1").json()[0]
    assert activity["event_type"] == "ontology.published" and "v1.1.0" in activity["summary"]


def test_tampered_artifacts_are_detected(seeded_client: TestClient, db_path: Path) -> None:
    _, ontology = _seeded(seeded_client)
    v1 = _publish(seeded_client, ontology["id"]).json()
    path = next((db_path.parent / "artifacts" / ontology["id"] / v1["id"]).glob("*.ttl"))
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.write_text("# tampered", encoding="utf-8")
    response = seeded_client.get(f"/api/ontologies/{ontology['id']}/versions/{v1['id']}/export")
    assert response.status_code == 500 and error_code(response) == "ARTIFACT_INTEGRITY_ERROR"


def test_published_versions_are_immutable_at_every_layer(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    v1 = _publish(seeded_client, ontology["id"]).json()
    url = f"/api/ontologies/{ontology['id']}/versions/{v1['id']}"
    assert seeded_client.patch(url, json={"version": "9.9.9"}).status_code == 405
    assert seeded_client.delete(url).status_code == 405

    deleted = seeded_client.delete(f"/api/ontologies/{ontology['id']}")
    assert deleted.status_code == 409 and error_code(deleted) == "ONTOLOGY_HAS_PUBLISHED_VERSIONS"

    session_factory = seeded_client.app.state.session_factory  # type: ignore[attr-defined]
    with session_factory() as session:
        version = session.get(OntologyVersion, v1["id"])
        version.release_notes = "rewritten history"
        with pytest.raises(ImmutableVersionError):
            session.commit()
        session.rollback()
        with pytest.raises(DatabaseError, match="immutable"):
            session.execute(text("UPDATE ontology_versions SET version = '9.9.9'"))
        session.rollback()
        with pytest.raises(DatabaseError, match="immutable"):
            session.execute(text("DELETE FROM ontology_versions"))
        session.rollback()

    assert seeded_client.get(url).json()["version"] == "1.0.0"


def test_applying_proposals_after_publication_changes_only_the_draft(studio: dict[str, Any]) -> None:
    client: TestClient = studio["client"]
    oid = studio["ontology"]["id"]
    v1 = _publish(client, oid).json()

    run = start_run(studio, baseline_version_id=v1["id"]).json()
    assert client.get(f"/api/discovery-runs/{run['id']}").json()["baseline_label"] == "published version 1.0.0"
    proposals = {p["title"]: p for p in client.get(f"/api/ontologies/{oid}/proposals").json()}
    lot = proposals["Add class 'Inventory Lot'"]
    client.post(f"/api/proposals/{lot['id']}/decision", json={"decision": "approve", "actor": SME})
    applied = client.post(f"/api/ontologies/{oid}/proposals/apply", json={"actor": SME}).json()
    assert applied["revision_incremented"] is True

    unchanged = client.get(f"/api/ontologies/{oid}/versions/{v1['id']}").json()
    assert unchanged["content_hash"] == v1["content_hash"]
    assert all(c["label"] != "Inventory Lot" for c in unchanged["snapshot"]["classes"])
    diff = client.get(f"/api/ontologies/{oid}/compare", params={"base": v1["id"]}).json()
    assert [e["label"] for e in diff["elements"] if e["change"] == "added"] == ["Inventory Lot"]
