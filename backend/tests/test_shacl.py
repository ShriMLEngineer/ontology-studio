"""Phase 4 milestone 4.2 - SHACL shapes, PySHACL engine, validation policies and the KG SHACL lane."""

from pathlib import Path
from typing import Any

import pyshacl
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SH, XSD
from sqlalchemy import create_engine, text

from app.modules.kg.policy import POLICIES, get_policy
from app.modules.semantics.owl import snapshot_to_owl
from app.modules.shacl.engine import check_shapes, run_shacl, without_signature_shapes
from app.modules.shacl.shapes import OLS, build_shapes_graph, shapes_namespace
from tests.conftest import error_code
from tests.kg_helpers import SME, facts, find_fact, publish, run_build, save_suggested_mapping, setup_kg, upload
from tests.test_registry import NS, _publish, _seed_snapshot, _seeded
from tests.test_semantics import _insert_legacy_version

SC = Namespace(NS)
DATA = Namespace("https://example.com/ontology/supply-chain/data/e/")
REVERSED = ("Steel Bracket SB-200", "supplies", "Contoso Metals GmbH")


# ------------------------------------------------------------------------------ generation and engine


def test_generated_shapes_reflect_data_constraints_and_are_well_formed() -> None:
    snapshot = _seed_snapshot()
    graph, index = build_shapes_graph(snapshot)
    sns = shapes_namespace(snapshot)
    sku = sns["g-cls-product-dp-sku"]
    assert (sku, SH.path, SC.sku) in graph and (sku, SH.datatype, XSD.string) in graph
    assert (sku, SH.minCount, Literal(1)) in graph and (sku, SH.maxCount, Literal(1)) in graph
    assert (sns["g-cls-organization-dp-duns"], SH.minCount, None) not in graph, "optional attribute: no minCount"
    assert (sns["g-cls-supplier-op-supplies"], SH["class"], SC.Product) in graph
    signature = sns["sig-domain-op-supplies"]
    assert (signature, SH.targetSubjectsOf, SC.supplies) in graph and (signature, SH["class"], SC.Supplier) in graph
    assert (signature, OLS.shapeRole, Literal("signature")) in graph
    assert index.counts()["generated_signature"] == len(index.iris(role="signature"))
    assert check_shapes(graph).well_formed
    assert not any(without_signature_shapes(graph).subjects(SH.targetSubjectsOf, None))


def test_shacl_runs_without_inference_so_reversed_relationships_are_caught() -> None:
    snapshot = _seed_snapshot()
    shapes, index = build_shapes_graph(snapshot)
    ontology = snapshot_to_owl(snapshot, include_axioms=False)
    data = Graph()
    data.add((DATA.p1, RDF.type, SC.Product))
    data.add((DATA.s1, RDF.type, SC.Supplier))
    data.add((DATA.p1, SC.supplies, DATA.s1))
    for subject, prop in ((DATA.p1, SC.sku), (DATA.p1, SC.productName), (DATA.s1, SC.legalName)):
        data.add((subject, prop, Literal("x", datatype=XSD.string)))

    shapes_before = len(shapes)
    report = run_shacl(data, shapes, ontology, index)
    signature = [r for r in report.results if r.shape and r.shape.role == "signature"]
    assert {(r.focus, r.shape.signature_side) for r in signature} == {(str(DATA.p1), "domain"), (str(DATA.s1), "range")}
    # Regression guard: with RDFS inference the domain axiom of 'supplies' would type p1 as a Supplier, and the
    # very signature shape meant to catch the reversed relationship would pass.
    domain_shape = URIRef(f"{shapes_namespace(snapshot)}sig-domain-op-supplies")
    only_domain = Graph()
    for triple in shapes.triples((domain_shape, None, None)):
        only_domain.add(triple)
    conforms_with_inference, _, _ = pyshacl.validate(data, shacl_graph=only_domain, ont_graph=ontology, inference="rdfs")
    assert conforms_with_inference
    assert not run_shacl(data, only_domain, ontology, index).conforms
    assert len(data) == 6 and len(shapes) == shapes_before, "neither the data nor the shapes graph is modified"

    inherited = Graph()
    inherited.add((DATA.s2, RDF.type, SC.Supplier))
    missing = run_shacl(inherited, without_signature_shapes(shapes), ontology, index)
    assert [r.path for r in missing.results] == [str(SC.legalName)], "Organization's required attribute applies to Supplier"


def test_policies_map_lane_results_to_outcomes() -> None:
    strict, signature, infer = (get_policy(p) for p in ("application-strict/1", "shacl-signature/1", "infer-and-flag/1"))
    assert get_policy(None) is strict and set(POLICIES) == {strict.id, signature.id, infer.id}
    generated_min = {"severity": "Violation", "component": "MinCountConstraintComponent", "origin": "generated", "role": "constraint"}
    assert strict.shacl_outcome(**generated_min) == "warn"
    assert strict.shacl_outcome(**{**generated_min, "component": "MaxCountConstraintComponent"}) == "info"
    assert strict.shacl_outcome(**{**generated_min, "origin": "authored"}) == "reject"
    assert strict.shacl_outcome(**{**generated_min, "origin": "authored", "severity": "Warning"}) == "warn"
    assert strict.shacl_outcome(**{**generated_min, "role": "signature"}) == "info"
    assert signature.shacl_outcome(**{**generated_min, "role": "signature"}) == "reject"
    assert (strict.use_signature_shapes, signature.use_signature_shapes, infer.entailment) == (False, True, True)


# ------------------------------------------------------------------------------ shapes API


def _shape_body(**overrides: Any) -> dict[str, Any]:
    return {
        "target_class_id": "cls-supplier",
        "label": "Supplier naming",
        "severity": "Warning",
        "message": "Legal names start with a capital letter.",
        "properties": [{"path_id": "dp-legal-name", "pattern": "^[A-Z]", "max_length": 120}],
        **overrides,
    }


def test_authored_shapes_are_governed_draft_content(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    oid = ontology["id"]
    base = f"/api/ontologies/{oid}/shapes"
    overview = seeded_client.get(base).json()
    assert overview["authored"] == [] and overview["check"]["well_formed"]
    assert {g["target_class_id"] for g in overview["generated"]} >= {"cls-product", "cls-organization"}
    product = next(g for g in overview["generated"] if g["target_class_id"] == "cls-product")
    sku = next(c for c in product["constraints"] if c["property_id"] == "dp-sku")
    assert (sku["min_count"], sku["max_count"], sku["datatype"]) == (1, 1, "string")
    assert any(s["property_id"] == "op-supplies" and s["side"] == "range" for s in overview["signatures"])

    bad = seeded_client.post(base, json=_shape_body(target_class_id="cls-missing"))
    assert bad.status_code == 422 and error_code(bad) == "SHAPE_INVALID"
    wrong = seeded_client.post(base, json=_shape_body(properties=[{"path_id": "dp-sku", "class_id": "cls-product"}]))
    assert wrong.status_code == 422 and error_code(wrong) == "SHAPE_INVALID"
    regex = seeded_client.post(base, json=_shape_body(properties=[{"path_id": "dp-sku", "pattern": "("}]))
    assert regex.status_code == 422

    revision = seeded_client.get(f"/api/ontologies/{oid}").json()["draft_revision"]
    created = seeded_client.post(base, params={"actor": SME}, json=_shape_body())
    assert created.status_code == 201, created.text
    shape = created.json()
    assert shape["id"].startswith("shp_") and shape["properties"][0]["id"].startswith("pc_")
    assert seeded_client.get(f"/api/ontologies/{oid}").json()["draft_revision"] == revision + 1
    turtle = seeded_client.get(f"{base}/rdf").text
    assert "sh:pattern" in turtle and "Legal names start with a capital letter." in turtle

    updated = seeded_client.put(f"{base}/{shape['id']}", params={"actor": SME}, json=_shape_body(severity="Violation"))
    assert updated.status_code == 200 and updated.json()["severity"] == "Violation"
    v1 = _publish(seeded_client, oid).json()
    assert [s["label"] for s in v1["snapshot"]["shapes"]] == ["Supplier naming"]
    shapes_ttl = seeded_client.get(f"/api/ontologies/{oid}/versions/{v1['id']}/export", params={"format": "shapes"})
    assert shapes_ttl.headers["x-artifact-derived"] == "false" and "sh:pattern" in shapes_ttl.text
    manifest = seeded_client.get(f"/api/ontologies/{oid}/versions/{v1['id']}/export", params={"format": "manifest"}).json()
    assert manifest["shapes"]["authored_constraint"] == 1

    assert seeded_client.delete(f"{base}/{shape['id']}", params={"actor": SME}).status_code == 204
    preview = seeded_client.get(f"/api/ontologies/{oid}/publish-preview").json()
    assert preview["diff"]["shape_changes"] == [{"shape_id": shape["id"], "label": "Supplier naming", "change": "removed"}]
    assert preview["suggested_version"] == "1.0.1", "a shape-only change is a patch"
    activity = seeded_client.get(f"/api/projects/{ontology['project_id']}/activity?limit=5").json()
    assert {"ontology.shape_deleted", "ontology.published"} <= {e["event_type"] for e in activity}


def test_shapes_with_deleted_targets_block_publication(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    oid = ontology["id"]
    seeded_client.post(f"/api/ontologies/{oid}/shapes", json=_shape_body(target_class_id="cls-carrier", properties=[]))
    seeded_client.delete(f"/api/ontologies/{oid}/classes/cls-carrier", params={"cascade": True})
    preview = seeded_client.get(f"/api/ontologies/{oid}/publish-preview").json()
    assert "SHAPE_TARGET_UNKNOWN" in {i["code"] for i in preview["validation"]["blocking_issues"]}


def test_sample_data_is_validated_against_draft_shapes(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    base = f"/api/ontologies/{ontology['id']}/shapes"
    seeded_client.post(base, json=_shape_body(severity="Violation"))
    data = f"""
        @prefix sc: <{NS}> . @prefix d: <https://example.org/d/> .
        d:s1 a sc:Supplier ; sc:legalName "lower case ltd" .
        d:p1 a sc:Product ; sc:sku "SKU-1" ; sc:productName "Bolt" ; sc:supplies d:s1 .
    """
    report = seeded_client.post(f"{base}/validate", json={"data": data}).json()
    assert report["conforms"] is False and report["data_triples"] == 6
    assert [(r["component"], r["shape_origin"]) for r in report["results"]] == [("PatternConstraintComponent", "authored")]
    strict = seeded_client.post(f"{base}/validate", json={"data": data, "include_signature_shapes": True}).json()
    assert {r["shape_role"] for r in strict["results"]} == {"constraint", "signature"}
    invalid = seeded_client.post(f"{base}/validate", json={"data": "not turtle"})
    assert invalid.status_code == 422 and error_code(invalid) == "RDF_PARSE_ERROR"


def test_imported_shacl_is_meta_validated_and_preserved(seeded_client: TestClient) -> None:
    _, ontology = _seeded(seeded_client)
    url = f"/api/ontologies/{ontology['id']}/shapes/import"
    shapes = f"""
        @prefix sh: <http://www.w3.org/ns/shacl#> . @prefix sc: <{NS}> . @prefix ex: <https://example.org/shapes#> .
        ex:CarrierShape a sh:NodeShape ; sh:targetClass sc:Carrier ;
            sh:property [ sh:path sc:legalName ; sh:minLength 2 ] ;
            sh:or ( [ sh:path sc:duns ; sh:minCount 1 ] [ sh:path sc:legalName ; sh:minCount 1 ] ) .
    """
    imported = seeded_client.post(url, files={"file": ("carrier.ttl", shapes.encode())}, data={"imported_by": SME})
    assert imported.status_code == 201, imported.text
    preserved = imported.json()["preserved"]
    assert len(preserved) == 1 and "cls-carrier" in preserved[0]["anchor_ids"]
    overview = seeded_client.get(f"/api/ontologies/{ontology['id']}/shapes").json()
    assert overview["preserved"][0]["axiom_id"] == preserved[0]["axiom_id"] and overview["check"]["well_formed"]
    again = seeded_client.post(url, files={"file": ("carrier.ttl", shapes.encode())})
    assert again.status_code == 409 and error_code(again) == "SHAPES_ALREADY_PRESENT"
    broken = shapes.replace("sh:minLength 2", 'sh:minLength "two"')
    rejected = seeded_client.post(url, files={"file": ("broken.ttl", broken.encode())})
    assert rejected.status_code == 422 and error_code(rejected) == "SHAPES_INVALID"


# ------------------------------------------------------------------------------ knowledge-graph lanes


def _lanes(client: TestClient, fact: dict[str, Any]) -> dict[str, Any]:
    return client.get(f"/api/kg/facts/{fact['id']}").json()["lanes"]


def test_strict_policy_reproduces_phase3_outcomes_and_reports_shacl(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    client = env["client"]
    build = run_build(env)
    assert build["settings"]["validation_policy"] == "application-strict/1"
    assert build["stats"]["facts"]["by_status"] == {"accepted": 51, "quarantined": 2, "rejected": 4}
    shacl = build["stats"]["shacl"]
    assert shacl["shapes_source"].startswith("version package (sc-1.0.0.shapes.ttl")
    assert shacl["by_outcome"] == {"warn": 5, "reject": 1} and shacl["unmapped_results"] == 0
    stage = next(s for s in build["stages"] if s["key"] == "shacl_validation")
    assert stage["status"] == "completed" and "under application-strict/1" in stage["summary"]

    reversed_fact = find_fact(facts(client, build["id"], kind="relationship"), *REVERSED)
    assert reversed_fact["status"] == "rejected" and reversed_fact["shacl_status"] == "conforms"
    assert reversed_fact["reasons"][0].startswith("Direction reversed")
    po = next(f for f in facts(client, build["id"], kind="type") if f["subject_label"] == "PO-7001")
    assert po["status"] == "accepted" and po["shacl_status"] == "Violation" and po["policy_id"] == "application-strict/1"
    result = _lanes(client, po)["shacl"]["results"][0]
    assert (result["component"], result["outcome"], result["shape_origin"]) == ("MinCountConstraintComponent", "warn", "generated")
    amount = next(f for f in facts(client, build["id"], kind="attribute") if f["shacl_status"] == "Violation")
    assert amount["status"] == "rejected" and amount["structural_passed"] is False, "SHACL agrees with the literal check"


def test_shacl_signature_policy_enforces_domain_and_range_with_shapes(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env, validation_policy="shacl-signature/1")
    assert build["stats"]["facts"]["by_status"] == {"accepted": 51, "quarantined": 2, "rejected": 4}
    fact = find_fact(facts(env["client"], build["id"], kind="relationship"), *REVERSED)
    lanes = _lanes(env["client"], fact)
    assert fact["status"] == "rejected" and fact["shacl_status"] == "Violation"
    assert all(reason.startswith("SHACL:") for reason in fact["reasons"])
    assert {c["code"] for c in lanes["policy"]["relaxed_checks"]} == {"direction", "domain", "range"}
    assert {r["shape_role"] for r in lanes["shacl"]["results"]} == {"signature"}


def test_infer_and_flag_policy_quarantines_incompatible_implications(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    build = run_build(env, validation_policy="infer-and-flag/1")
    fact = find_fact(facts(env["client"], build["id"], kind="relationship"), *REVERSED)
    lanes = _lanes(env["client"], fact)
    assert fact["status"] == "quarantined", "not rejected under the open-world policy, but flagged for review"
    assert lanes["entailment"]["ran"] and not lanes["entailment"]["passed"]
    assert any(c["message"].startswith("Suspicious:") for c in lanes["entailment"]["checks"])
    assert "Steel Bracket SB-200 is a Supplier" in lanes["entailment"]["inferred_types"]
    assert build["stats"]["shacl"]["inconsistencies"] == []


def test_authored_violation_shapes_reject_facts(seeded_client: TestClient) -> None:
    env = setup_kg(seeded_client)
    client = env["client"]
    oid = env["ontology"]["id"]
    client.post(
        f"/api/ontologies/{oid}/shapes",
        json=_shape_body(severity="Violation", message="Legal names must start with 'Zz'.",
                         properties=[{"path_id": "dp-legal-name", "pattern": "^Zz"}]),
    )
    v2 = publish(client, oid, "1.0.1")
    build = run_build(env, version_id=v2["id"])
    rejected = [
        f for f in facts(client, build["id"], kind="attribute", status="rejected") if f["predicate_id"] == "dp-legal-name"
    ]
    assert rejected and all(f["structural_passed"] for f in rejected), "rejected by SHACL only"
    assert rejected[0]["reasons"] == ["SHACL: Legal names must start with 'Zz'."]


def test_builds_on_legacy_versions_derive_shapes_and_label_them(seeded_client: TestClient) -> None:
    project, ontology = _seeded(seeded_client)
    version_id, _ = _insert_legacy_version(seeded_client, ontology["id"])
    document = upload(seeded_client, project["id"], "suppliers.csv")
    mapping = save_suggested_mapping(seeded_client, project["id"], document, version_id)
    env = {
        "client": seeded_client, "project": project, "version": {"id": version_id},
        "documents": {"suppliers.csv": document}, "mappings": {"suppliers.csv": mapping},
    }
    build = run_build(env)
    assert build["stats"]["shacl"]["shapes_source"].startswith("derived at build time")
    derived = seeded_client.get(f"/api/ontologies/{ontology['id']}/versions/{version_id}/export", params={"format": "shapes"})
    assert derived.headers["x-artifact-derived"] == "true" and "sh:NodeShape" in derived.text


def test_pre_phase4_facts_are_reported_without_lanes(seeded_client: TestClient, db_path: Path) -> None:
    env = setup_kg(seeded_client, ["suppliers.csv"])
    build = run_build(env)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:  # simulate facts written by a Phase 3 build
        connection.execute(text("UPDATE kg_candidate_facts SET lanes = NULL WHERE build_id = :id"), {"id": build["id"]})
    engine.dispose()
    items = facts(env["client"], build["id"])
    assert items and all(f["shacl_status"] is None and f["policy_id"] is None for f in items)
    assert _lanes(env["client"], items[0]) is None


def test_validation_policies_are_listed(client: TestClient) -> None:
    policies = client.get("/api/kg/validation-policies").json()
    assert [p["id"] for p in policies if p["default"]] == ["application-strict/1"]
    assert {p["id"] for p in policies} == set(POLICIES)
    bad = client.post("/api/projects/x/kg/builds", json={
        "ontology_version_id": "v", "source_document_ids": ["d"], "requested_by": SME,
        "settings": {"validation_policy": "lenient/9"},
    })
    assert bad.status_code == 422


@pytest.mark.parametrize("severity", ["Violation", "Warning", "Info"])
def test_authored_severity_is_serialised(severity: str) -> None:
    snapshot = _seed_snapshot()
    from app.modules.ontology.domain import NodeShape, PropertyConstraint

    shaped = snapshot.model_copy(update={"shapes": [NodeShape(
        id="s1", target_class_id="cls-product", label="L", severity=severity,  # type: ignore[arg-type]
        properties=[PropertyConstraint(id="p1", path_id="dp-sku", min_length=3, allowed_values=["A", "B"])],
    )]})
    graph, index = build_shapes_graph(shaped)
    node = URIRef(f"{shapes_namespace(shaped)}a-s1-p1")
    assert (node, SH.severity, SH[severity]) in graph and (node, SH["in"], None) in graph
    assert index.get(str(node)).shape_id == "s1" and check_shapes(graph).well_formed
