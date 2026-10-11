"""Milestones 3.2-3.4 on structured sources: deterministic mapping, entity resolution, fact
validation, graph persistence with provenance, evaluation and ontology feedback."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import error_code
from tests.kg_helpers import SME, facts, find_fact, publish, run_build, save_suggested_mapping, setup_kg, upload


def _build(seeded_client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    env = setup_kg(seeded_client)
    return env, run_build(env)


def test_build_runs_all_nine_stages_with_persisted_logs(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    assert [s["key"] for s in build["stages"]] == [
        "source_loading", "content_parsing", "entity_extraction", "relationship_extraction", "entity_resolution",
        "structural_validation", "evidence_validation", "graph_persistence", "evaluation",
    ]
    assert all(s["status"] == "completed" for s in build["stages"])
    assert build["stages_completed"] == 9 and build["duration_ms"] is not None
    assert build["graph_store"] == "sql"
    assert build["stats"]["sources"]["records"] == 15
    logs = env["client"].get(f"/api/kg/builds/{build['id']}/logs").json()
    assert any("Schema authority: Supply Chain Core 1.0.0" in line["message"] for line in logs)
    later = env["client"].get(f"/api/kg/builds/{build['id']}/logs", params={"after": logs[-2]["id"]}).json()
    assert len(later) == 1


def test_reversed_relationship_is_rejected_and_never_repaired(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    fact = find_fact(facts(env["client"], build["id"], kind="relationship"), "Steel Bracket SB-200", "supplies", "Contoso Metals GmbH")
    assert fact["status"] == "rejected"
    assert fact["structural_passed"] is False
    assert any(r.startswith("Direction reversed") for r in fact["reasons"])
    assert fact["graph_element_id"] is None
    detail = env["client"].get(f"/api/kg/facts/{fact['id']}").json()
    codes = {c["code"]: c["passed"] for c in detail["structural"]["checks"]}
    assert codes["direction"] is False and codes["domain"] is False and codes["range"] is False
    assert detail["evidence"]["status"] == "supported", "evidence is evaluated independently of structure"
    assert detail["excerpts"][0]["record"]["subject_type"] == "Product"


def test_relationship_to_an_unestablished_entity_is_quarantined(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    fact = find_fact(facts(env["client"], build["id"], kind="relationship"), "Fabrikam Plastics Inc", "supplies", "P-999")
    assert fact["status"] == "quarantined"
    assert fact["structural_passed"] is True
    assert any("not established by any source record" in r for r in fact["reasons"])
    entity_fact = [f for f in facts(env["client"], build["id"], kind="type") if f["subject_label"] == "P-999"][0]
    assert entity_fact["status"] == "quarantined"


def test_unknown_predicates_and_classes_are_rejected_and_become_gaps(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    client = env["client"]
    fact = find_fact(facts(client, build["id"], kind="relationship"), "Contoso Metals GmbH", "certified by", "A-01")
    assert fact["status"] == "rejected"
    assert "Relationship 'certified by' is not defined in Supply Chain Core 1.0.0." in fact["reasons"]
    gaps = {(g["gap_type"], g["label"]): g for g in client.get(f"/api/kg/builds/{build['id']}/gaps").json()}
    relationship_gap = gaps[("unknown_relationship", "certified by")]
    assert relationship_gap["suggestion"]["domain_id"] == "cls-supplier"
    assert relationship_gap["suggestion"]["range_ref"] == "Auditor"
    assert relationship_gap["fact_ids"] == [fact["id"]]
    assert ("unknown_class", "Auditor") in gaps
    unmapped = {g["label"]: g for (t, _), g in gaps.items() if t == "unmapped_field"}
    assert set(unmapped) == {"country", "certification", "quantity"}
    assert unmapped["quantity"]["suggestion"]["domain_id"] == "cls-purchase-order"
    assert unmapped["quantity"]["suggestion"]["datatype"] == "integer"


def test_duplicate_facts_merge_into_one_edge_with_multiple_provenance(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    client = env["client"]
    rel = facts(client, build["id"], kind="relationship")
    northwind = [f for f in rel if f["subject_label"] == "Northwind Components Ltd" and f["object_label"] == "Hydraulic Pump HP-100"]
    assert len(northwind) == 2 and all(f["status"] == "accepted" for f in northwind)
    assert northwind[0]["graph_element_id"] == northwind[1]["graph_element_id"]
    element = client.get(f"/api/kg/builds/{build['id']}/graph/elements/{northwind[0]['graph_element_id']}").json()
    assert element["kind"] == "edge"
    assert element["edge"]["fact_count"] == 2
    assert {f["excerpts"][0]["document_name"] for f in element["facts"]} == {"products.csv", "supply_relationships.csv"}
    assert element["subject"]["name"] == "Northwind Components Ltd"
    assert element["ontology_version"] == "1.0.0"
    assert element["facts"][0]["evidence"]["status"] == "supported"


def test_entity_resolution_merges_by_business_key(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    client = env["client"]
    entities = client.get(f"/api/kg/builds/{build['id']}/entities", params={"q": "S-001"}).json()
    assert len(entities) == 1
    detail = client.get(f"/api/kg/entities/{entities[0]['id']}").json()
    assert detail["resolution_method"] == "business_key"
    assert detail["has_master_record"] is True
    assert {m["source"]["document_name"] for m in detail["mentions"]} == {
        "suppliers.csv", "products.csv", "purchase_orders.csv", "supply_relationships.csv",
    }
    assert "Northwind" in detail["aliases"]


def test_invalid_literal_is_rejected_and_valid_values_are_node_properties(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    client = env["client"]
    amounts = [f for f in facts(client, build["id"], kind="attribute") if f["predicate_label"] == "total amount"]
    invalid = [f for f in amounts if f["value"] == "approx. 1000"][0]
    assert invalid["status"] == "rejected"
    assert "'approx. 1000' is not a decimal number." in invalid["reasons"]
    graph = client.get(f"/api/kg/builds/{build['id']}/graph").json()
    po = [n for n in graph["nodes"] if n["identifier"] == "PO-7001"][0]
    properties = {p["label"]: p["values"] for p in po["properties"]}
    assert properties["total amount"] == ["8400.00"]
    assert properties["order date"] == ["2026-07-14"]


def test_graph_contains_only_accepted_facts_and_supports_exploration(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    client = env["client"]
    graph = client.get(f"/api/kg/builds/{build['id']}/graph").json()
    names = {n["name"] for n in graph["nodes"]}
    assert "P-999" not in names and "A-01" not in names
    assert graph["total_nodes"] == len(graph["nodes"]) == 11
    labels = {(e["predicate_label"]) for e in graph["edges"]}
    assert labels == {"supplies", "issued to", "orders product"}
    by_id = {n["id"]: n["name"] for n in graph["nodes"]}
    triples = {(by_id[e["source"]], e["predicate_label"], by_id[e["target"]]) for e in graph["edges"]}
    assert ("Steel Bracket SB-200", "supplies", "Contoso Metals GmbH") not in triples
    assert ("Contoso Metals GmbH", "supplies", "Steel Bracket SB-200") in triples
    accepted_rel = [f for f in facts(client, build["id"], kind="relationship", status="accepted")]
    assert all(f["graph_element_id"] for f in accepted_rel)

    filtered = client.get(f"/api/kg/builds/{build['id']}/graph", params={"class_id": "cls-supplier"}).json()
    assert {n["class_id"] for n in filtered["nodes"]} == {"cls-supplier"}
    by_predicate = client.get(f"/api/kg/builds/{build['id']}/graph", params={"predicate_id": "op-issued-to"}).json()
    assert {e["predicate_id"] for e in by_predicate["edges"]} == {"op-issued-to"}
    source_id = env["documents"]["purchase_orders.csv"]["id"]
    by_source = client.get(f"/api/kg/builds/{build['id']}/graph", params={"source_id": source_id}).json()
    assert {e["predicate_id"] for e in by_source["edges"]} == {"op-issued-to", "op-orders-product"}

    found = client.get(f"/api/kg/builds/{build['id']}/graph/search", params={"q": "contoso"}).json()
    assert {n["name"] for n in found} == {"Contoso Metals GmbH", "Contoso Packaging BV"}
    neighbours = client.get(f"/api/kg/builds/{build['id']}/graph/nodes/{found[0]['id']}/neighborhood").json()
    assert found[0]["id"] in {n["id"] for n in neighbours["nodes"]}
    node = client.get(f"/api/kg/builds/{build['id']}/graph/elements/{found[0]['id']}").json()
    assert node["kind"] == "node" and node["facts"][0]["kind"] == "type"
    assert {f["status"] for f in node["facts"]} == {"accepted"}


def test_evaluation_metrics_state_denominators(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    evaluation = env["client"].get(f"/api/kg/builds/{build['id']}/evaluation").json()
    metrics = {m["key"]: m for s in evaluation["sections"] for m in s["metrics"]}
    total = metrics["candidate_facts"]["value"]
    assert total == sum(evaluation["status_counts"].values())
    rate = metrics["acceptance_rate"]
    assert (rate["numerator"], rate["denominator"]) == (metrics["accepted"]["value"], total)
    assert rate["value"] == round(rate["numerator"] / total, 4)
    assert metrics["class_coverage"]["denominator"] == 11
    assert metrics["graph_elements_without_provenance"]["value"] == 0
    assert metrics["unknown_relationships"]["value"] == 1
    assert "do not measure factual precision or recall" in evaluation["disclaimer"]
    codes = {r["code"] for r in evaluation["failure_reasons"]}
    assert {"direction", "predicate_defined", "literal_datatype", "object_established"} <= codes


def test_gap_to_proposal_to_new_version_and_isolated_rebuild(seeded_client: TestClient) -> None:
    env, first = _build(seeded_client)
    client, ontology_id = env["client"], env["ontology"]["id"]
    gaps = {(g["gap_type"], g["label"]): g for g in client.get(f"/api/kg/builds/{first['id']}/gaps").json()}
    relationship_gap = gaps[("unknown_relationship", "certified by")]

    created = client.post(
        f"/api/kg/builds/{first['id']}/gaps/proposals",
        json={"gap_ids": [relationship_gap["id"]], "requested_by": SME, "comment": "Seen in partner data"},
    )
    assert created.status_code == 201, created.text
    result = created.json()
    assert len(result["proposals"]) == 2, "the unknown range class is proposed together with the relationship"
    assert set(result["included_gap_ids"]) == {relationship_gap["id"], gaps[("unknown_class", "Auditor")]["id"]}
    by_kind = {p["element_kind"]: p for p in result["proposals"]}
    assert all(p["origin"] == "kg_build" and p["kg_build_id"] == first["id"] for p in result["proposals"])
    assert all(p["status"] == "pending" for p in result["proposals"])
    detail = client.get(f"/api/proposals/{by_kind['object_property']['id']}").json()
    assert detail["depends_on"] == [by_kind["class"]["id"]]
    assert detail["new_element"]["domain_id"] == "cls-supplier"
    assert detail["new_element"]["range_id"] == by_kind["class"]["new_element_id"]
    assert detail["evidence"][0]["quote"] == "Supplier,S-002,certified by,Auditor,A-01"
    assert detail["llm_output"] is None
    assert client.get(f"/api/ontologies/{ontology_id}/versions").json()[0]["version"] == "1.0.0"
    again = client.post(
        f"/api/kg/builds/{first['id']}/gaps/proposals", json={"gap_ids": [relationship_gap["id"]], "requested_by": SME}
    )
    assert error_code(again) == "KG_GAP_ALREADY_PROPOSED"
    listed = client.get(f"/api/ontologies/{ontology_id}/proposals", params={"origin": "kg_build"}).json()
    assert {p["id"] for p in listed} == {p["id"] for p in result["proposals"]}

    for proposal in (by_kind["class"], by_kind["object_property"]):
        decided = client.post(
            f"/api/proposals/{proposal['id']}/decision", json={"decision": "approve", "actor": SME, "comment": ""}
        )
        assert decided.status_code == 200, decided.text
    applied = client.post(f"/api/ontologies/{ontology_id}/proposals/apply", json={"actor": SME}).json()
    assert len(applied["applied"]) == 2
    v11 = publish(client, ontology_id, "1.1.0")
    versions = client.get(f"/api/projects/{env['project']['id']}/kg/ontology-versions").json()
    assert [(v["version"], v["is_latest"]) for v in versions] == [("1.1.0", True), ("1.0.0", False)]

    auditors = upload(client, env["project"]["id"], "auditors.csv")
    auditor_mapping = save_suggested_mapping(client, env["project"]["id"], auditors, v11["id"])
    assert auditor_mapping["spec"]["entities"][0]["class_id"] == by_kind["class"]["new_element_id"]
    before = client.get(f"/api/kg/builds/{first['id']}/graph").json()

    rebuilt = client.post(
        f"/api/kg/builds/{first['id']}/rebuild", json={"ontology_version_id": v11["id"], "requested_by": SME}
    ).json()
    assert rebuilt["status"] == "configured" and rebuilt["parent_build_id"] == first["id"]
    client.patch(
        f"/api/kg/builds/{rebuilt['id']}",
        json={
            "source_document_ids": [*[s["id"] for s in rebuilt["sources"]], auditors["id"]],
            "mapping_ids": [*rebuilt["mapping_ids"], auditor_mapping["id"]],
        },
    )
    started = client.post(f"/api/kg/builds/{rebuilt['id']}/start", json={"requested_by": SME})
    assert started.status_code == 202
    second = client.get(f"/api/kg/builds/{rebuilt['id']}").json()
    assert second["status"] == "completed" and second["ontology_version"] == "1.1.0"

    certified = find_fact(facts(client, second["id"], kind="relationship"), "Contoso Metals GmbH", "certified by", "Bureau Veritas Certification")
    assert certified["status"] == "accepted"
    assert client.get(f"/api/kg/builds/{first['id']}/graph").json() == before, "the earlier build is unchanged"
    first_fact = find_fact(facts(client, first["id"], kind="relationship"), "Contoso Metals GmbH", "certified by", "A-01")
    assert first_fact["status"] == "rejected"

    comparison = client.get("/api/kg/compare", params={"base": first["id"], "target": second["id"]}).json()
    assert comparison["edges"]["added"] == 1 and comparison["edges"]["removed"] == 0
    assert comparison["nodes"]["added"] == 2
    assert any(i["label"].endswith("→ certifiedBy → Bureau Veritas Certification") for i in comparison["edges"]["added_items"])
    assert client.delete(f"/api/kg/builds/{first['id']}").status_code == 409


def test_concurrent_builds_are_refused_and_started_builds_are_frozen(seeded_client: TestClient) -> None:
    env, build = _build(seeded_client)
    client = env["client"]
    edit = client.patch(f"/api/kg/builds/{build['id']}", json={"name": "renamed"})
    assert error_code(edit) == "KG_BUILD_NOT_EDITABLE"
    restart = client.post(f"/api/kg/builds/{build['id']}/start", json={"requested_by": SME})
    assert error_code(restart) == "KG_BUILD_ALREADY_STARTED"
    assert build["stats"]["graph"]["graph_id"] == build["id"]
