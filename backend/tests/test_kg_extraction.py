"""Ontology-guided LLM extraction (scripted test double) and evidence validation of text facts."""

from typing import Any

from fastapi.testclient import TestClient

from tests.fakes import ScriptedLLMProvider
from tests.kg_helpers import SME, facts, find_fact, setup_kg

PDF = "supplier-performance-review.pdf"


def _q(chunk: str, quote: str) -> dict[str, str]:
    return {"chunk_id": chunk, "quote": quote}


EXTRACTION: dict[str, Any] = {
    "entities": [
        {"ref": "E1", "name": "Northwind Components", "class_id": "cls-supplier", "identifier": "S-001",
         **_q("C1", "Northwind Components (supplier S-001) supplies the Hydraulic Pump HP-100")},
        # A class label instead of an id, and a numeric identifier, must be normalised.
        {"ref": "E2", "name": "Hydraulic Pump HP-100", "class_id": "Product", "identifier": "P-100",
         **_q("C1", "the Hydraulic Pump HP-100 (product P-100)")},
        {"ref": "E3", "name": "Bureau Veritas", "class_id": "Auditor",
         **_q("C1", "certified by Bureau Veritas, an independent quality auditor")},
        {"ref": "E4", "name": "Contoso Metals", "class_id": "cls-supplier", "identifier": "S-002",
         **_q("C1", "Contoso Metals (supplier S-002) supplies the Steel Bracket SB-200")},
        {"ref": "E5", "name": "Contoso", "class_id": "cls-supplier",
         **_q("C2", "Contoso is reviewing a new alloy line")},
        {"ref": "E6", "name": "Polymer Housing PH-300", "class_id": "cls-product", "identifier": "P-300",
         **_q("C2", "the Polymer Housing PH-300 (product P-300)")},
        {"ref": "E7", "name": "Fabrikam Plastics", "class_id": "cls-supplier",
         **_q("C2", "The risk rating of Fabrikam Plastics was raised to high")},
        {"ref": "E8", "name": "Blue Yonder Freight", "class_id": "cls-carrier",
         **_q("C2", "carried by Blue Yonder Freight")},
        {"ref": "E9", "name": "Shipment SH-9001", "class_id": "cls-shipment", "identifier": "SH-9001",
         **_q("C2", "Shipment SH-9001 is carried by")},
        {"ref": "E10", "name": "Phantom Corp", "class_id": "cls-supplier", **_q("C1", "Phantom Corp is a supplier")},
    ],
    "relationships": [
        {"subject_ref": "E1", "predicate_id": "op-supplies", "object_ref": "E2",
         **_q("C1", "Northwind Components (supplier S-001) supplies the Hydraulic Pump HP-100")},
        {"subject_ref": "E2", "predicate_id": "op-supplies", "object_ref": "E1",
         **_q("C1", "Northwind Components (supplier S-001) supplies the Hydraulic Pump HP-100")},
        {"subject_ref": "E4", "predicate_id": "certified by", "object_ref": "E3",
         **_q("C1", "Contoso Metals is certified by Bureau Veritas")},
        {"subject_ref": "E7", "predicate_id": "op-supplies", "object_ref": "E6",
         **_q("C2", "Fabrikam Plastics guarantees supply of the housing until 2030")},
        {"subject_ref": "E9", "predicate_id": "carried by", "object_ref": "E8",
         **_q("C2", "Shipment SH-9001 is carried by Blue Yonder Freight")},
        {"subject_ref": "E5", "predicate_id": "op-supplies", "object_ref": "E6",
         **_q("C2", "Contoso is reviewing a new alloy line")},
        {"subject_ref": "E4", "predicate_id": "op-supplies", "object_ref": "E2",
         **_q("C1", "Contoso Metals (supplier S-002) supplies the Steel Bracket SB-200")},
        {"subject_ref": "E1", "predicate_id": "op-supplies", "object_ref": "E99", **_q("C1", "Northwind Components")},
        {"subject_ref": "E4", "predicate_id": "dp-legal-name", "object_ref": "E2", **_q("C1", "Contoso Metals")},
        {"subject_ref": "E6", "predicate_id": "op-has-component", "object_ref": "E2", "chunk_id": "C2", "quote": ""},
    ],
    "attributes": [
        {"entity_ref": "E7", "property_id": "dp-risk-rating", "value": "high",
         **_q("C2", "The risk rating of Fabrikam Plastics was raised to high")},
        {"entity_ref": "E9", "property_id": "dp-tracking-number", "value": 9001, **_q("C2", "Shipment SH-9001")},
    ],
    "unknown_concepts": [
        {"kind": "relationship", "label": "certified by", "subject_class": "Supplier", "object_class": "Auditor",
         "description": "An independent body certifies the supplier's quality system.",
         **_q("C1", "Contoso Metals is certified by Bureau Veritas")},
        {"kind": "class", "label": "Auditor", "description": "An independent quality auditor.",
         **_q("C1", "an independent quality auditor")},
        {"kind": "class", "label": "Supplier", **_q("C1", "supplier S-001")},
        {"kind": "attribute", "label": "on-time delivery", "subject_class": "cls-supplier",
         **_q("C1", "this quote is invented")},
    ],
}


def _run(seeded_client: TestClient, response: dict[str, Any] | Exception = EXTRACTION) -> tuple[dict[str, Any], dict[str, Any], ScriptedLLMProvider]:
    env = setup_kg(seeded_client, ["suppliers.csv", "products.csv", PDF])
    provider = ScriptedLLMProvider([response])
    seeded_client.app.state.llm_provider = provider  # type: ignore[attr-defined]
    created = seeded_client.post(
        f"/api/projects/{env['project']['id']}/kg/builds",
        json={
            "ontology_version_id": env["version"]["id"],
            "source_document_ids": [d["id"] for d in env["documents"].values()],
            "mapping_ids": [m["id"] for m in env["mappings"].values()],
            "requested_by": SME,
            "start": True,
        },
    )
    assert created.status_code == 201, created.text
    build = seeded_client.get(f"/api/kg/builds/{created.json()['id']}").json()
    return env, build, provider


def _by_triple(client: TestClient, build_id: str) -> list[dict[str, Any]]:
    return facts(client, build_id, kind="relationship")


def test_prompt_is_constrained_by_the_published_snapshot(seeded_client: TestClient) -> None:
    _, build, provider = _run(seeded_client)
    assert build["status"] == "completed", build["error"]
    prompt = provider.calls[0]["user"]
    assert "PUBLISHED ONTOLOGY: Supply Chain Core version 1.0.0" in prompt
    assert "[op-supplies] supplies: Supplier [cls-supplier] -> Product [cls-product]" in prompt
    assert '<chunk id="C2" document="supplier-performance-review.pdf" page="2">' in prompt
    assert provider.calls[0]["schema_name"] == "kg_extraction"
    assert (build["provider"], build["model"], build["prompt_version"]) == ("scripted-test-double", "scripted", "kg-extraction/2026-10-1")


def test_text_facts_are_validated_against_structure_and_evidence(seeded_client: TestClient) -> None:
    env, build, _ = _run(seeded_client)
    client = env["client"]
    rel = _by_triple(client, build["id"])

    merged = [f for f in rel if f["subject_label"] == "Northwind Components Ltd" and f["object_label"] == "Hydraulic Pump HP-100"]
    assert {f["origin"] for f in merged} == {"structured", "llm"}
    assert all(f["status"] == "accepted" for f in merged)
    assert len({f["graph_element_id"] for f in merged}) == 1, "text and record facts share one edge"
    text_fact = client.get(f"/api/kg/facts/{[f for f in merged if f['origin'] == 'llm'][0]['id']}").json()
    assert text_fact["sources"][0]["page"] == 1 and text_fact["sources"][0]["located"] is True
    assert "Northwind Components (supplier S-001) supplies" in text_fact["excerpts"][0]["text"]

    reversed_fact = find_fact(rel, "Hydraulic Pump HP-100", "supplies", "Northwind Components Ltd")
    assert reversed_fact["status"] == "rejected"
    assert any(r.startswith("Direction reversed") for r in reversed_fact["reasons"])

    unlocated = find_fact([f for f in rel if f["origin"] == "llm"], "Fabrikam Plastics Inc", "supplies", "Polymer Housing PH-300")
    assert unlocated["status"] == "quarantined" and unlocated["evidence_status"] == "unlocated"

    weak = find_fact(rel, "Contoso Metals GmbH", "supplies", "Hydraulic Pump HP-100")
    assert weak["status"] == "quarantined" and weak["evidence_status"] == "weak"
    assert any("does not mention 'Hydraulic Pump HP-100'" in r for r in weak["reasons"])

    ambiguous = find_fact(rel, "Contoso", "supplies", "Polymer Housing PH-300")
    assert ambiguous["status"] == "quarantined" and ambiguous["resolution_passed"] is False

    no_evidence = find_fact(rel, "Polymer Housing PH-300", "has component", "Hydraulic Pump HP-100")
    assert no_evidence["status"] == "rejected" and no_evidence["evidence_status"] == "missing"

    dangling = [f for f in rel if f["predicate_ref"] == "op-supplies" and f["object_label"] == "E99"][0]
    assert dangling["status"] == "rejected"
    assert "Object 'E99' does not refer to an extracted entity." in dangling["reasons"]

    wrong_kind = [f for f in rel if f["predicate_ref"] == "dp-legal-name"][0]
    assert "'dp-legal-name' is an attribute in the ontology, not a relationship." in wrong_kind["reasons"]

    carried = find_fact(rel, "Shipment SH-9001", "carried by", "Blue Yonder Freight")
    assert carried["status"] == "accepted", carried["reasons"]


def test_ambiguous_names_are_flagged_not_merged(seeded_client: TestClient) -> None:
    env, build, _ = _run(seeded_client)
    client = env["client"]
    entities = client.get(f"/api/kg/builds/{build['id']}/entities", params={"method": "ambiguous"}).json()
    assert [e["label"] for e in entities] == ["Contoso"]
    detail = client.get(f"/api/kg/entities/{entities[0]['id']}").json()
    assert {c["identifier"] for c in detail["candidates"]} == {"S-002", "S-004"}
    assert detail["status"] == "quarantined"
    fabrikam = client.get(f"/api/kg/builds/{build['id']}/entities", params={"q": "S-003"}).json()[0]
    methods = {m["resolution_method"] for m in client.get(f"/api/kg/entities/{fabrikam['id']}").json()["mentions"]}
    assert "alias" in methods, "the text mention without an identifier matched the configured alias"


def test_single_valued_conflicts_are_quarantined_and_literals_normalised(seeded_client: TestClient) -> None:
    env, build, _ = _run(seeded_client)
    attributes = facts(env["client"], build["id"], kind="attribute")
    risk = [f for f in attributes if f["predicate_label"] == "risk rating" and f["value"] == "high"][0]
    assert risk["status"] == "quarantined"
    assert any("Conflicts with 'medium'" in r for r in risk["reasons"])
    tracking = [f for f in attributes if f["predicate_label"] == "tracking number"][0]
    assert tracking["value"] == "9001" and tracking["status"] == "accepted"


def test_unknown_concepts_become_gaps_only_with_located_evidence(seeded_client: TestClient) -> None:
    env, build, _ = _run(seeded_client)
    client = env["client"]
    gaps = {(g["gap_type"], g["label"]): g for g in client.get(f"/api/kg/builds/{build['id']}/gaps").json()}
    assert ("unknown_class", "Auditor") in gaps
    assert gaps[("unknown_class", "Auditor")]["origins"] == ["llm"]
    relationship = gaps[("unknown_relationship", "certified by")]
    assert relationship["suggestion"]["definition"] == "An independent body certifies the supplier's quality system."
    assert relationship["evidence"][0]["page"] == 1
    assert not any(label == "on-time delivery" for _, label in gaps), "unlocated evidence never creates a gap"
    assert ("unknown_class", "Supplier") not in gaps, "known concepts reported as unknown are discarded"
    logs = [line["message"] for line in client.get(f"/api/kg/builds/{build['id']}/logs").json()]
    assert any("matches 'Supplier'" in m for m in logs)

    unknown_entity = [f for f in facts(client, build["id"], kind="type") if f["subject_label"] == "Bureau Veritas"][0]
    assert unknown_entity["status"] == "rejected"
    phantom = [f for f in facts(client, build["id"], kind="type") if f["subject_label"] == "Phantom Corp"][0]
    assert phantom["status"] == "quarantined" and phantom["evidence_status"] == "unlocated"


def test_invalid_llm_output_fails_the_build_honestly(seeded_client: TestClient) -> None:
    from app.modules.llm.provider import LLMOutputError

    _, build, _ = _run(seeded_client, LLMOutputError("not JSON"))
    assert build["status"] == "failed"
    assert build["error"] == "The model returned invalid output for every extraction batch. not JSON"
    stages = {s["key"]: s["status"] for s in build["stages"]}
    assert stages["entity_extraction"] == "failed" and stages["graph_persistence"] == "skipped"


def test_truncated_output_is_preserved_without_creating_text_facts(seeded_client: TestClient) -> None:
    from app.modules.kg.models import KgBuild
    from app.modules.llm.provider import LLMOutputError

    raw = '{"entities":[{"ref":"E1","name":"unfinished'
    env, build, _ = _run(
        seeded_client,
        LLMOutputError(
            "The model response was truncated at the configured output limit (4096 tokens). "
            "No partial facts were accepted. Increase Max output tokens in Settings or reduce the extraction batch size.",
            raw_text=raw,
        ),
    )
    assert build["status"] == "failed" and "4096 tokens" in build["error"]
    assert "Unexpected error" not in build["error"]
    assert facts(env["client"], build["id"], origin="llm") == []
    with seeded_client.app.state.session_factory() as session:
        stored = session.get(KgBuild, build["id"])
        assert stored is not None and len(stored.llm_outputs) == 1
        assert stored.llm_outputs[0]["raw_text"] == raw
        assert "truncated" in stored.llm_outputs[0]["error"]


def test_transport_errors_fail_the_build(seeded_client: TestClient) -> None:
    from app.modules.llm.provider import LLMTransportError

    _, build, _ = _run(seeded_client, LLMTransportError("connection refused"))
    assert build["status"] == "failed"
    assert "connection refused" in build["error"]
    assert seeded_client.get(f"/api/kg/builds/{build['id']}/graph").json()["total_nodes"] == 0
