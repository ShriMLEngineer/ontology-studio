"""Semantic foundation.

Persisted IRIs and their lock, OWL semantics, lossless RDF import/export with preserved axioms,
legacy-version compatibility, migration 0004, entailment preview and the new structural rules.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS, XSD
from sqlalchemy import create_engine, text

from app.core.ids import new_id
from app.db.migrations import upgrade_database
from app.main import create_app
from app.modules.kg.ontology_view import OntologyView
from app.modules.kg.validation import parse_literal
from app.modules.ontology.domain import (
    ClassDefinition,
    ClassSemantics,
    DatatypePropertyDefinition,
    ExtensionAxiom,
    ObjectPropertyDefinition,
    ObjectPropertySemantics,
    OntologySchema,
    Restriction,
)
from app.modules.registry.diff import diff_snapshots
from app.modules.registry.models import OntologyVersion
from app.modules.registry.rdf import to_turtle
from app.modules.registry.snapshot import OntologySnapshot, SnapshotMetadata
from app.modules.semantics.graphs import canonical_ntriples, parse_rdf, serialize
from app.modules.semantics.owl import snapshot_to_owl
from app.modules.semantics.rdf_import import ImportResult, import_graph
from app.modules.semantics.reasoning import entailment_preview
from app.modules.validation.rules import validate_schema
from app.modules.validation.schemas import Severity
from app.modules.validation.service import ValidationService
from tests.conftest import error_code, make_settings
from tests.test_registry import NS, SME, _publish, _seed_snapshot, _seeded

EX = "https://example.org/onto#"
ONTO = URIRef("https://example.org/onto")
SAMPLE = """
@prefix ex: <https://example.org/onto#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .

<https://example.org/onto> a owl:Ontology ; rdfs:label "Example" ; owl:versionInfo "0.3" ;
   owl:imports <http://xmlns.com/foaf/0.1/> ; rdfs:comment "Header comment" .
ex:Party a owl:Class ; rdfs:label "Party"@en ; rdfs:label "Partei"@de ; skos:definition "A party."@en .
ex:Person a owl:Class ; rdfs:subClassOf ex:Party ; rdfs:label "Person"@en ;
   rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:worksFor ; owl:someValuesFrom ex:Org ] ;
   owl:equivalentClass foaf:Person ; owl:disjointWith ex:Org .
ex:Org a owl:Class ; rdfs:label "Organisation"@en ; rdfs:subClassOf ex:Party ;
   rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:employs ;
                     owl:minQualifiedCardinality "1"^^xsd:nonNegativeInteger ; owl:onClass ex:Person ] .
ex:Vip a owl:Class ; owl:equivalentClass [ a owl:Class ; owl:unionOf ( ex:Person ex:Org ) ] .
ex:worksFor a owl:ObjectProperty, owl:FunctionalProperty ; rdfs:domain ex:Person ; rdfs:range ex:Org ;
   owl:inverseOf ex:employs ; rdfs:label "works for"@en .
ex:employs a owl:ObjectProperty ; rdfs:domain ex:Org ; rdfs:range ex:Person .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:range xsd:string ; rdfs:label "name" .
ex:age a owl:DatatypeProperty, owl:FunctionalProperty ; rdfs:domain ex:Person ; rdfs:range xsd:nonNegativeInteger .
ex:note a owl:AnnotationProperty .
ex:Person ex:note "custom annotation" .
ex:alice a owl:NamedIndividual, ex:Person .
ex:PersonShape a sh:NodeShape ; sh:targetClass ex:Person ; sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""


def _import_sample() -> tuple[Graph, ImportResult]:
    graph = parse_rdf(SAMPLE.encode(), "turtle")
    return graph, import_graph(graph, rdf_format="turtle")


def _snapshot(result: ImportResult, *, with_axioms: bool = True) -> OntologySnapshot:
    schema = result.schema_
    return OntologySnapshot(
        metadata=result.metadata,
        classes=schema.classes,
        object_properties=schema.object_properties,
        datatype_properties=schema.datatype_properties,
        extension_axioms=schema.extension_axioms if with_axioms else [],
    )


def _by_name(items: list[Any]) -> dict[str, Any]:
    return {e.local_name: e for e in items}


# ------------------------------------------------------------------------------ RDF import (pure)


def test_import_models_the_profile_and_preserves_everything_else() -> None:
    source, result = _import_sample()
    report = result.report
    assert report.lossless and report.source_triples == len(source)
    assert report.consumed_triples + report.preserved_triples + report.superseded_triples == len(source)
    assert report.superseded == ['<https://example.org/onto> <http://www.w3.org/2002/07/owl#versionInfo> "0.3" .']

    classes = _by_name(result.schema_.classes)
    props = _by_name(result.schema_.object_properties)
    attrs = _by_name(result.schema_.datatype_properties)
    person = classes["Person"]
    assert person.iri == EX + "Person" and person.parent_ids == [classes["Party"].id]
    assert person.semantics.annotation_language == "en"
    assert person.semantics.disjoint_ids == [classes["Org"].id]
    assert person.semantics.restrictions == [Restriction(property_id=props["worksFor"].id, kind="some", class_id=classes["Org"].id)]
    assert classes["Org"].semantics.restrictions[0].model_dump(exclude_none=True) == {
        "property_id": props["employs"].id, "kind": "min", "class_id": person.id, "cardinality": 1,
    }
    assert props["worksFor"].semantics.characteristics == ["functional"]
    assert props["worksFor"].semantics.inverse_id == props["employs"].id
    assert attrs["age"].semantics.functional and not attrs["age"].semantics.range_declared
    assert attrs["age"].multi_valued is False and attrs["name"].multi_valued is True
    assert result.metadata.ontology_iri == str(ONTO) and result.metadata.imports == ["http://xmlns.com/foaf/0.1/"]
    assert {"foaf", "sh"} <= {p.prefix for p in result.metadata.prefixes}

    axioms = result.schema_.extension_axioms
    assert {"owl-class-expression", "shacl-shape", "individual", "annotation", "annotation-property"} <= {
        a.kind for a in axioms
    }
    assert all(a.scope == "shapes" for a in axioms if a.kind == "shacl-shape")
    union = next(a for a in axioms if a.kind == "owl-class-expression")
    assert set(union.anchor_ids) == {classes["Vip"].id, person.id, classes["Org"].id}

    # Independent no-loss check against the export of the typed model + preserved axioms.
    exported = snapshot_to_owl(_snapshot(result))
    for axiom in axioms:
        if axiom.scope == "shapes":
            exported.parse(data=axiom.ntriples, format="nt")
    superseded = (ONTO, OWL.versionInfo, Literal("0.3"))
    for triple in source:
        if not any(isinstance(term, BNode) for term in triple) and triple != superseded:
            assert triple in exported, triple
    assert len(set(exported.subjects(RDF.type, OWL.Restriction))) == 2
    unions = list(exported.objects(URIRef(EX + "Vip"), OWL.equivalentClass))
    assert len(unions) == 1 and (unions[0], OWL.unionOf, None) in exported
    assert (ONTO, OWL.versionInfo, None) not in exported, "superseded header triples are replaced at publication"


@pytest.mark.parametrize("fmt", ["rdfxml", "jsonld", "ntriples", "turtle"])
def test_exported_rdf_reimports_to_the_same_model(fmt: str) -> None:
    _, first = _import_sample()
    data = serialize(snapshot_to_owl(_snapshot(first)), fmt)
    second = import_graph(parse_rdf(data, fmt), rdf_format=fmt)
    assert second.report.lossless and second.report.added_triples == 0
    for attr in ("classes", "object_properties", "datatype_properties"):
        assert sorted(getattr(second.schema_, attr), key=lambda e: e.id) == sorted(
            getattr(first.schema_, attr), key=lambda e: e.id
        ), attr

    def ontology_axioms(result: ImportResult) -> set[str]:
        return {canonical_ntriples(a.ntriples) for a in result.schema_.extension_axioms if a.scope == "ontology"}

    assert ontology_axioms(second) == ontology_axioms(first)


def test_legacy_published_turtle_reimports_with_explicit_owl_semantics() -> None:
    legacy = to_turtle(_seed_snapshot(), version="1.0.0", published_at=datetime.now(UTC), release_notes="First")
    result = import_graph(parse_rdf(legacy, "turtle"), rdf_format="turtle")
    report = result.report
    assert report.lossless and report.added_triples == 0 and report.superseded_triples == 3
    assert report.preserved_by_kind == {"annotation": 1}, "only the release-notes comment is outside the profile"
    seed = _seed_snapshot()
    assert sorted(c.id for c in result.schema_.classes) == sorted(c.id for c in seed.classes)
    assert sum(p.semantics.functional for p in result.schema_.datatype_properties) == 17
    assert sum(len(c.semantics.restrictions) for c in result.schema_.classes) == 8
    assert (result.metadata.prefix, result.metadata.namespace) == ("sc", NS)


def test_rdf_parse_errors_are_reported() -> None:
    from app.modules.semantics.graphs import RdfParseError, detect_format

    with pytest.raises(RdfParseError):
        parse_rdf(b"@prefix : <x> . this is not turtle", "turtle")
    with pytest.raises(RdfParseError):
        detect_format("ontology.docx")
    assert detect_format("x.owl") == "rdfxml" and detect_format("x.jsonld") == "jsonld"


# ------------------------------------------------------------------------------ RDF import (API)


def _new_project(client: TestClient) -> str:
    return client.post("/api/projects", json={"name": "Imported Project"}).json()["id"]


def _import(client: TestClient, project_id: str, content: str = SAMPLE, **data: str) -> Any:
    return client.post(
        f"/api/projects/{project_id}/ontologies/import",
        files={"file": ("example.ttl", content.encode())},
        data={"imported_by": SME, **data},
    )


def _legacy_save_body(draft: dict[str, Any]) -> dict[str, Any]:
    """A legacy client payload: no IRIs, no semantics, no header fields."""

    def strip(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in e.items() if k not in ("iri", "semantics")} for e in items]

    ontology = draft["ontology"]
    return {
        "base_revision": draft["draft_revision"],
        "metadata": {k: ontology[k] for k in ("name", "namespace", "prefix", "description")},
        "classes": strip(draft["classes"]),
        "object_properties": strip(draft["object_properties"]),
        "datatype_properties": strip(draft["datatype_properties"]),
        "layout": draft["layout"],
    }


def test_import_api_preserves_axioms_through_designer_saves_and_publication(client: TestClient) -> None:
    project_id = _new_project(client)
    response = _import(client, project_id)
    assert response.status_code == 201, response.text
    body = response.json()
    ontology, record = body["ontology"], body["import_record"]
    oid = ontology["id"]
    assert ontology["name"] == "Example" and ontology["ontology_iri"] == str(ONTO)
    assert record["report"]["lossless"] and record["rdf_format"] == "turtle" and len(record["sha256"]) == 64
    assert client.get(f"/api/ontologies/{oid}/imports").json()[0]["id"] == record["id"]

    axioms = client.get(f"/api/ontologies/{oid}/axioms").json()
    assert len(axioms) == record["report"]["preserved_axioms"] and not any(a["orphaned"] for a in axioms)

    # A legacy client saves the draft without knowing about IRIs, semantics or axioms.
    draft = client.get(f"/api/ontologies/{oid}/draft").json()
    person = next(c for c in draft["classes"] if c["local_name"] == "Person")
    saved = client.put(f"/api/ontologies/{oid}/draft", json=_legacy_save_body(draft))
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision_incremented"] is False, "omitted semantics are not treated as changes"
    after = client.get(f"/api/ontologies/{oid}/draft").json()
    assert next(c for c in after["classes"] if c["id"] == person["id"]) == person
    assert len(client.get(f"/api/ontologies/{oid}/axioms").json()) == len(axioms)

    turtle = client.get(f"/api/ontologies/{oid}/rdf", params={"format": "turtle"})
    assert turtle.status_code == 200 and turtle.headers["content-type"].startswith("text/turtle")
    graph = Graph().parse(data=turtle.text, format="turtle")
    assert (URIRef(EX + "Person"), URIRef(EX + "note"), Literal("custom annotation")) in graph
    assert (URIRef(EX + "worksFor"), RDF.type, OWL.FunctionalProperty) in graph
    for fmt, media in (("rdfxml", "application/rdf+xml"), ("jsonld", "application/ld+json")):
        other = client.get(f"/api/ontologies/{oid}/rdf", params={"format": fmt, "download": True})
        assert other.headers["content-type"].startswith(media) and "attachment" in other.headers["content-disposition"]
        assert isomorphic(Graph().parse(data=other.content, format="xml" if fmt == "rdfxml" else "json-ld"), graph)

    # Deleting an anchor element orphans the preserved union axiom and blocks publication.
    vip = next(c for c in draft["classes"] if c["local_name"] == "Vip")
    assert client.delete(f"/api/ontologies/{oid}/classes/{vip['id']}").status_code == 200
    preview = client.get(f"/api/ontologies/{oid}/publish-preview").json()
    assert not preview["can_publish"]
    assert "EXTENSION_AXIOM_ORPHANED" in {i["code"] for i in preview["validation"]["blocking_issues"]}
    blocked = _publish(client, oid)
    assert blocked.status_code == 422 and error_code(blocked) == "PUBLISH_BLOCKED_BY_VALIDATION"

    orphan = next(a for a in client.get(f"/api/ontologies/{oid}/axioms").json() if a["orphaned"])
    assert orphan["missing_anchor_ids"] == [vip["id"]]
    revision = client.get(f"/api/ontologies/{oid}").json()["draft_revision"]
    assert client.delete(f"/api/ontologies/{oid}/axioms/{orphan['id']}", params={"deleted_by": SME}).status_code == 204
    assert client.get(f"/api/ontologies/{oid}").json()["draft_revision"] == revision + 1
    assert client.delete(f"/api/ontologies/{oid}/axioms/{orphan['id']}").status_code == 404

    published = _publish(client, oid, release_notes="Imported")
    assert published.status_code == 201, published.text
    version = published.json()
    assert version["package_format"] == "ols-semantic/2"
    assert version["snapshot"]["extension_axioms"] and version["snapshot"]["metadata"]["ontology_iri"] == str(ONTO)
    exported = client.get(f"/api/ontologies/{oid}/versions/{version['id']}/export", params={"format": "turtle"})
    assert exported.headers["x-artifact-derived"] == "false"
    published_graph = Graph().parse(data=exported.text, format="turtle")
    assert (URIRef(EX + "Person"), URIRef(EX + "note"), Literal("custom annotation")) in published_graph
    assert (ONTO, OWL.versionInfo, Literal("1.0.0")) in published_graph
    assert (ONTO, OWL.versionInfo, Literal("0.3")) not in published_graph
    manifest = client.get(f"/api/ontologies/{oid}/versions/{version['id']}/export", params={"format": "manifest"}).json()
    assert manifest["package_format"] == "ols-semantic/2" and manifest["version_iri"] == f"{ONTO}/1.0.0"
    assert manifest["preserved_axioms"] == len(axioms) - 1
    assert set(manifest["artifacts"]) == {"json", "turtle", "rdfxml", "jsonld", "ntriples", "shapes"}


def test_import_targets_only_new_or_empty_ontologies(client: TestClient, ontology: dict[str, Any]) -> None:
    project_id = ontology["project_id"]
    into_empty = _import(client, project_id, ontology_id=ontology["id"])
    assert into_empty.status_code == 201, into_empty.text
    assert into_empty.json()["ontology"]["id"] == ontology["id"]
    assert into_empty.json()["ontology"]["namespace"] == EX and into_empty.json()["ontology"]["name"] == "Test Ontology"
    again = _import(client, project_id, ontology_id=ontology["id"])
    assert again.status_code == 409 and error_code(again) == "IMPORT_TARGET_NOT_EMPTY"
    assert _import(client, project_id).json()["ontology"]["name"] == "Example"
    second = _import(client, project_id)
    assert second.status_code == 201 and second.json()["ontology"]["name"] == "Example (2)"
    bad = client.post(
        f"/api/projects/{project_id}/ontologies/import", files={"file": ("x.ttl", b"not turtle at all")}
    )
    assert bad.status_code == 422 and error_code(bad) == "RDF_PARSE_ERROR"


# ------------------------------------------------------------------------------ IRIs


def test_deleting_elements_removes_semantic_references(client: TestClient) -> None:
    oid = _import(client, _new_project(client)).json()["ontology"]["id"]
    draft = client.get(f"/api/ontologies/{oid}/draft").json()
    org = next(c for c in draft["classes"] if c["local_name"] == "Org")
    deleted = client.delete(f"/api/ontologies/{oid}/classes/{org['id']}", params={"cascade": True})
    assert deleted.status_code == 200, deleted.text
    after = client.get(f"/api/ontologies/{oid}/draft").json()
    person = next(c for c in after["classes"] if c["local_name"] == "Person")
    assert person["semantics"]["disjoint_ids"] == [] and person["semantics"]["restrictions"] == []
    report = client.post(f"/api/ontologies/{oid}/validations").json()
    assert "SEMANTIC_REFERENCE_INVALID" not in {i["code"] for i in report["issues"]}


def test_iris_are_minted_followed_and_locked_after_publication(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    oid = ontology["id"]
    assert seeded_client.get(f"/api/ontologies/{oid}/draft").json()["locked_iri_ids"] == []
    assert _publish(seeded_client, oid).status_code == 201
    assert {"cls-supplier", "op-supplies"} <= set(seeded_client.get(f"/api/ontologies/{oid}/draft").json()["locked_iri_ids"])

    renamed = seeded_client.patch(f"/api/ontologies/{oid}/classes/cls-supplier", json={"local_name": "Vendor"}).json()
    assert renamed["local_name"] == "Vendor" and renamed["iri"] == NS + "Supplier", "published IRIs are locked"

    created = seeded_client.post(f"/api/ontologies/{oid}/classes", json={"label": "Inventory Lot"}).json()
    assert created["id"] not in seeded_client.get(f"/api/ontologies/{oid}/draft").json()["locked_iri_ids"]
    assert created["iri"] == NS + "InventoryLot"
    moved = seeded_client.patch(f"/api/ontologies/{oid}/classes/{created['id']}", json={"local_name": "Lot"}).json()
    assert moved["iri"] == NS + "Lot", "unpublished IRIs follow the local name"

    draft = seeded_client.get(f"/api/ontologies/{oid}/draft").json()
    body = _legacy_save_body(draft) | {"classes": draft["classes"]}
    body["classes"] = [c | {"iri": NS + "Other"} if c["id"] == "cls-supplier" else c for c in body["classes"]]
    locked = seeded_client.put(f"/api/ontologies/{oid}/draft", json=body)
    assert locked.status_code == 422 and error_code(locked) == "IRI_LOCKED"

    seeded_client.patch(f"/api/ontologies/{oid}", json={"namespace": "https://example.com/v2#"})
    by_id = {c["id"]: c for c in seeded_client.get(f"/api/ontologies/{oid}/draft").json()["classes"]}
    assert by_id["cls-supplier"]["iri"] == NS + "Supplier"
    assert by_id[created["id"]]["iri"] == "https://example.com/v2#Lot"
    diff = seeded_client.get(f"/api/ontologies/{oid}/publish-preview").json()["diff"]
    assert diff["suggested_bump"] == "major"
    assert not any("IRI changed" in b for b in diff["breaking_changes"]), "locked IRIs did not change"


# ------------------------------------------------------------------------------ legacy versions


def _insert_legacy_version(client: TestClient, ontology_id: str) -> tuple[str, bytes]:
    """A version exactly as the legacy publisher produced it: snapshot /1 + frozen Turtle + JSON artifacts."""
    seed = _seed_snapshot()
    legacy = json.loads(seed.model_dump_json(exclude={"extension_axioms"}))
    legacy["format"] = "ols.ontology-snapshot/1"
    legacy["metadata"] = {k: legacy["metadata"][k] for k in ("name", "namespace", "prefix", "description")}
    for key in ("classes", "object_properties", "datatype_properties"):
        legacy[key] = [{k: v for k, v in e.items() if k not in ("iri", "semantics")} for e in legacy[key]]
    snapshot = OntologySnapshot.model_validate(legacy)
    published_at = datetime(2026, 1, 15, tzinfo=UTC)
    turtle = to_turtle(snapshot, version="1.0.0", published_at=published_at, release_notes="Legacy release")
    version_id = new_id()
    repo = client.app.state.artifact_repository  # type: ignore[attr-defined]
    stored = {
        "turtle": repo.store(ontology_id, version_id, fmt="turtle", filename="sc-1.0.0.ttl", media_type="text/turtle", content=turtle),
        "json": repo.store(
            ontology_id, version_id, fmt="json", filename="sc-1.0.0.json", media_type="application/json",
            content=json.dumps({"version": "1.0.0", "snapshot": legacy}).encode(),
        ),
    }
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        run = ValidationService(session).run(ontology_id)
        session.add(
            OntologyVersion(
                id=version_id, ontology_id=ontology_id, version="1.0.0", sequence=1, draft_revision=1,
                snapshot=legacy, content_hash="0" * 64, class_count=len(legacy["classes"]),
                object_property_count=len(legacy["object_properties"]),
                datatype_property_count=len(legacy["datatype_properties"]), validation_run_id=run.id,
                validation_summary={"is_valid": True}, change_summary={}, previous_version_id=None,
                artifacts={k: v.as_dict() for k, v in stored.items()}, release_notes="Legacy release",
                published_by=SME, published_at=published_at,
            )
        )
        session.commit()
    return version_id, turtle


def test_legacy_versions_keep_their_artifacts_and_flag_the_profile_change(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    oid = ontology["id"]
    version_id, turtle = _insert_legacy_version(seeded_client, oid)
    base = f"/api/ontologies/{oid}/versions/{version_id}"

    summary = seeded_client.get(f"/api/ontologies/{oid}/versions").json()[0]
    assert summary["package_format"] == "ols-semantic/1 (legacy)" and summary["snapshot_format"] == "ols.ontology-snapshot/1"
    stored = seeded_client.get(f"{base}/export", params={"format": "turtle"})
    assert stored.content == turtle and stored.headers["x-artifact-derived"] == "false"
    derived = seeded_client.get(f"{base}/export", params={"format": "rdfxml"})
    assert derived.status_code == 200 and derived.headers["x-artifact-derived"] == "true"
    assert isomorphic(Graph().parse(data=derived.content, format="xml"), Graph().parse(data=turtle, format="turtle"))
    missing = seeded_client.get(f"{base}/export", params={"format": "manifest"})
    assert missing.status_code == 404 and error_code(missing) == "EXPORT_FORMAT_NOT_AVAILABLE"
    assert seeded_client.get(base).json()["snapshot"]["format"] == "ols.ontology-snapshot/1"

    preview = seeded_client.get(f"/api/ontologies/{oid}/publish-preview").json()
    assert preview["diff"]["elements"] == [], "migrated draft IRIs equal the IRIs the legacy version derived"
    assert any("Semantic profile change" in n and "17 owl:FunctionalProperty" in n for n in preview["diff"]["notes"])
    assert preview["suggested_version"] == "1.1.0" and preview["can_publish"]

    renamed = seeded_client.patch(f"/api/ontologies/{oid}/classes/cls-supplier", json={"local_name": "Vendor"}).json()
    assert renamed["iri"] == NS + "Supplier", "legacy publications lock IRIs too"

    v2 = _publish(seeded_client, oid).json()
    assert v2["package_format"] == "ols-semantic/2"
    v2_graph = Graph().parse(
        data=seeded_client.get(f"/api/ontologies/{oid}/versions/{v2['id']}/export").text, format="turtle"
    )
    assert (URIRef(NS + "sku"), RDF.type, OWL.FunctionalProperty) not in v2_graph, "D2: no derived OWL axioms"
    assert (URIRef(NS + "Supplier"), RDF.type, OWL.Class) in v2_graph
    assert seeded_client.get(f"{base}/export", params={"format": "turtle"}).content == turtle, "legacy bytes unchanged"


# ------------------------------------------------------------------------------ migration 0004


def test_migration_0004_backfills_iris_and_keeps_drafts_stable(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    url = f"sqlite:///{db.as_posix()}"
    upgrade_database(url, "0003")
    engine = create_engine(url)
    now = "2026-01-01 00:00:00.000000"
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (id, name, business_domain, description, created_at, updated_at) "
                                f"VALUES ('p', 'P', '', '', '{now}', '{now}')"))
        connection.execute(text("INSERT INTO ontologies (id, project_id, name, namespace, prefix, description, "
                                f"draft_revision, created_at, updated_at) VALUES ('o', 'p', 'O', 'https://e.com/o#', 'o', '', "
                                f"3, '{now}', '{now}')"))
        connection.execute(text("INSERT INTO ontology_classes (parent_ids, ontology_id, id, local_name, label, description, "
                                f"aliases, sort_order, created_at, updated_at) VALUES ('[]', 'o', 'c1', 'Thing1', 'Thing 1', "
                                f"'A thing.', '[]', 0, '{now}', '{now}')"))
        connection.execute(text("INSERT INTO ontology_datatype_properties (domain_id, datatype, required, multi_valued, "
                                "ontology_id, id, local_name, label, description, aliases, sort_order, created_at, updated_at) "
                                "VALUES ('c1', 'string', 1, 0, 'o', 'd1', 'code', 'code', 'A code.', '[]', 0, "
                                f"'{now}', '{now}')"))
    engine.dispose()
    upgrade_database(url, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT iri, semantics FROM ontology_classes")).one() == ("https://e.com/o#Thing1", "{}")
        assert connection.execute(text("SELECT iri FROM ontology_datatype_properties")).scalar() == "https://e.com/o#code"
        header = connection.execute(text("SELECT ontology_iri, prefixes, imports, require_domain_range FROM ontologies")).one()
        assert header == (None, "[]", "[]", 1)
    engine.dispose()

    with TestClient(create_app(make_settings(db))) as client:
        draft = client.get("/api/ontologies/o/draft").json()
        assert draft["classes"][0]["semantics"]["restrictions"] == []
        body = {
            "base_revision": draft["draft_revision"],
            "metadata": {k: draft["ontology"][k] for k in ("name", "namespace", "prefix", "description")},
            "classes": draft["classes"],
            "object_properties": draft["object_properties"],
            "datatype_properties": draft["datatype_properties"],
            "layout": draft["layout"],
        }
        saved = client.put("/api/ontologies/o/draft", json=body).json()
        assert saved["revision_incremented"] is False and saved["draft"]["draft_revision"] == 3


# ------------------------------------------------------------------------------ entailment


def _small_schema(**extra: Any) -> OntologySchema:
    return OntologySchema(
        namespace=EX,
        prefix="ex",
        classes=[
            ClassDefinition(id="a", local_name="A", label="A", parent_ids=["b"],
                            semantics=ClassSemantics(disjoint_ids=["d"])),
            ClassDefinition(id="b", local_name="B", label="B", parent_ids=["c"]),
            ClassDefinition(id="c", local_name="C", label="C"),
            ClassDefinition(id="d", local_name="D", label="D"),
        ],
        object_properties=[
            ObjectPropertyDefinition(id="p", local_name="p", label="p", domain_id="a", range_id="c"),
        ],
        datatype_properties=[DatatypePropertyDefinition(id="v", local_name="v", label="v", domain_id="a")],
        **extra,
    )


def test_entailment_preview_infers_and_detects_inconsistency_without_writing() -> None:
    individual = ExtensionAxiom(
        id="x", kind="individual", summary="x", anchor_ids=["a", "d"],
        ntriples=f"<{EX}x> <{RDF.type}> <{EX}A> .\n<{EX}x> <{RDF.type}> <{EX}D> .\n",
    )
    schema = _small_schema(extension_axioms=[individual])
    snapshot = OntologySnapshot(
        metadata=SnapshotMetadata(name="S", namespace=EX, prefix="ex"),
        **{k: getattr(schema, k) for k in ("classes", "object_properties", "datatype_properties", "extension_axioms")},
    )
    graph = snapshot_to_owl(snapshot)
    before = len(graph)
    report = entailment_preview(graph)
    assert len(graph) == before, "the preview never modifies the ontology graph"
    displays = {e.display for e in report.entailments}
    assert "ex:A rdfs:subClassOf ex:C" in displays and "ex:x rdf:type ex:C" in displays
    assert report.informational and report.inconsistencies


def test_entailment_endpoint(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    report = seeded_client.get(f"/api/ontologies/{ontology['id']}/entailments").json()
    assert report["informational"] is True and report["inconsistencies"] == []
    assert report["asserted_triples"] > 0 and isinstance(report["entailments"], list)


# ------------------------------------------------------------------------------ structural rules


def _codes(schema: OntologySchema) -> dict[str, Severity]:
    return {i.code: i.severity for i in validate_schema(schema)}


def test_rules_for_iris_semantics_axioms_and_domain_policy() -> None:
    base = _small_schema()
    assert not [i for i in validate_schema(base) if i.severity == Severity.ERROR]

    dup = base.model_copy(update={"classes": [*base.classes[:3], base.classes[3].model_copy(update={"iri": EX + "A"})]})
    assert _codes(dup)["DUPLICATE_IRI"] == Severity.ERROR
    bad = base.model_copy(update={"classes": [base.classes[0].model_copy(update={"iri": "not an iri"}), *base.classes[1:]]})
    assert _codes(bad)["IRI_INVALID"] == Severity.ERROR

    broken = base.classes[0].model_copy(
        update={"semantics": ClassSemantics(restrictions=[Restriction(property_id="nope", kind="min", cardinality=1)])}
    )
    assert _codes(base.model_copy(update={"classes": [broken, *base.classes[1:]]}))["SEMANTIC_REFERENCE_INVALID"] == Severity.ERROR
    conflicting = base.object_properties[0].model_copy(
        update={"semantics": ObjectPropertySemantics(characteristics=["symmetric", "asymmetric"], inverse_id="zz")}
    )
    codes = _codes(base.model_copy(update={"object_properties": [conflicting]}))
    assert codes["CHARACTERISTICS_CONFLICT"] == Severity.WARNING and codes["SEMANTIC_REFERENCE_INVALID"] == Severity.ERROR

    orphan = ExtensionAxiom(id="ax", kind="annotation", summary="s", ntriples="", anchor_ids=["gone"])
    assert _codes(base.model_copy(update={"extension_axioms": [orphan]}))["EXTENSION_AXIOM_ORPHANED"] == Severity.ERROR

    open_prop = base.object_properties[0].model_copy(update={"domain_id": None, "range_id": None})
    strict = base.model_copy(update={"object_properties": [open_prop]})
    assert _codes(strict)["PROPERTY_DOMAIN_MISSING"] == Severity.ERROR
    relaxed = strict.model_copy(update={"require_domain_range": False})
    assert _codes(relaxed)["PROPERTY_DOMAIN_MISSING"] == Severity.WARNING
    assert _codes(relaxed)["PROPERTY_RANGE_MISSING"] == Severity.WARNING


def test_open_signatures_admit_any_class_in_kg_checks() -> None:
    schema = _small_schema()
    open_prop = schema.object_properties[0].model_copy(update={"domain_id": None})
    snapshot = OntologySnapshot(
        metadata=SnapshotMetadata(name="S", namespace=EX, prefix="ex"),
        classes=schema.classes, object_properties=[open_prop], datatype_properties=schema.datatype_properties,
    )
    view = OntologyView(snapshot, version_id="v", version="1.0.0")
    assert view.satisfies("d", None) and view.satisfies("a", "c") and not view.satisfies("d", "c")
    assert not view.satisfies(None, None) and view.constraint_label(None) == "any class (open)"


# ------------------------------------------------------------------------------ diff and literals


def test_diff_classifies_semantic_iri_and_axiom_changes() -> None:
    base = _seed_snapshot()

    def bump(mutate: Any) -> str:
        target = base.model_copy(deep=True)
        mutate(target)
        return diff_snapshots(base, target, from_label="a", to_label="b").suggested_bump

    assert bump(lambda s: s.classes[0].semantics.__setattr__("deprecated", True)) == "minor"
    assert bump(lambda s: s.classes[0].__setattr__("iri", NS + "Renamed")) == "major"
    axiom = ExtensionAxiom(id="ax", kind="annotation", summary="s", ntriples=f"<{NS}X> <{RDFS.seeAlso}> <{NS}Y> .\n")
    assert bump(lambda s: s.extension_axioms.append(axiom)) == "minor"
    with_axiom = base.model_copy(update={"extension_axioms": [axiom]})
    removed = diff_snapshots(with_axiom, base, from_label="a", to_label="b")
    assert removed.suggested_bump == "major" and removed.axiom_changes[0].change == "removed"
    renamed_only = base.model_copy(deep=True)
    renamed_only.classes[0].local_name = "Renamed"
    renamed_only.classes[0].iri = NS + base.classes[0].local_name
    assert diff_snapshots(base, renamed_only, from_label="a", to_label="b").suggested_bump == "patch"


def test_new_xsd_datatypes_are_parsed() -> None:
    assert parse_literal("42", "int")[1] == "42" and not parse_literal("9999999999", "int")[0]
    assert parse_literal("9999999999", "long")[0]
    assert parse_literal("1.5e3", "double")[1] == "1500.0" and parse_literal("INF", "float")[0]
    assert parse_literal("12:30:00", "time")[1] == "12:30:00" and not parse_literal("25:00", "time")[0]
    assert parse_literal("2024", "gYear")[0] and not parse_literal("24", "gYear")[0]
    assert XSD.gYear and str(XSD.int).endswith("int")
