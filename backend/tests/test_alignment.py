from typing import Any

from app.modules.discovery.alignment import align_findings, normalize_term
from app.modules.discovery.contract import LLMDiscoveryResponse, LLMFinding
from app.modules.discovery.grounding import ChunkRef, GroundedEvidence
from app.modules.ontology.domain import OntologySchema
from app.modules.seed import supply_chain


def _schema() -> OntologySchema:
    content = supply_chain.draft_content()
    return OntologySchema(
        namespace=content["metadata"]["namespace"],
        prefix=content["metadata"]["prefix"],
        classes=content["classes"],
        object_properties=content["object_properties"],
        datatype_properties=content["datatype_properties"],
    )


def _evidence(quote: str = "quote") -> list[GroundedEvidence]:
    chunk = ChunkRef("c", "C1", "d", "doc.txt", None, 0, quote)
    return [GroundedEvidence(chunk, quote, quote, 0, len(quote), True, quote)]


def _finding(**data: Any) -> LLMFinding:
    base = {"term": data.get("label", "x"), "rationale": "r", "confidence": 0.8}
    return LLMFinding.model_validate({**base, **data})


def _align(*findings: LLMFinding) -> Any:
    return align_findings(_schema(), [(f, _evidence(f"quote for {f.term}")) for f in findings])


def test_normalization_handles_case_plural_and_camel_case() -> None:
    assert normalize_term("PurchaseOrders") == normalize_term("purchase order")
    assert normalize_term("Inventory Lots") == "inventory lot"
    assert normalize_term("address") == "address"


def test_contract_is_lenient_on_confidence_and_case() -> None:
    finding = LLMFinding.model_validate(
        {"action": "ADD", "element_kind": "Class", "term": "t", "label": "T", "confidence": 85, "target_id": "null"}
    )
    assert (finding.action, finding.element_kind, finding.confidence, finding.target_id) == ("add", "class", 0.85, None)
    assert len(LLMDiscoveryResponse.model_validate({"findings": [finding.model_dump()] * 50}).findings) == 40


def test_duplicate_add_becomes_reuse() -> None:
    result = _align(_finding(action="add", element_kind="class", term="vendors", label="Vendor"))
    (proposal,) = result.proposals
    assert proposal.proposal_type == "reuse"
    assert proposal.target_element_id == "cls-supplier"
    assert any("Duplicate prevented" in note for note in proposal.alignment["notes"])
    assert proposal.alignment["llm_action"] == "add"


def test_add_with_new_synonym_becomes_alias() -> None:
    result = _align(_finding(action="add", element_kind="class", term="Haulier", label="Carrier"))
    (proposal,) = result.proposals
    assert proposal.proposal_type == "alias"
    assert proposal.changes["aliases"]["after"][-1] == "Haulier"


def test_reuse_of_unknown_concept_becomes_add_with_unique_local_name() -> None:
    result = _align(_finding(action="reuse", element_kind="class", label="Inventory Lot", target_id="cls-made-up"))
    (proposal,) = result.proposals
    assert proposal.proposal_type == "add"
    assert proposal.new_element["local_name"] == "InventoryLot"
    assert proposal.new_element["id"].startswith("cls_")


def test_property_with_existing_name_but_different_signature_is_a_conflict() -> None:
    result = _align(
        _finding(action="add", element_kind="object_property", label="supplies", domain="Carrier", range="Product")
    )
    (proposal,) = result.proposals
    assert proposal.proposal_type == "conflict"
    assert proposal.target_element_id == "op-supplies"
    assert any("Semantic conflict" in note for note in proposal.alignment["notes"])


def test_property_with_same_signature_is_reused() -> None:
    result = _align(
        _finding(action="add", element_kind="object_property", label="supplies", domain="Supplier", range="cls-product")
    )
    assert result.proposals[0].proposal_type == "reuse"


def test_alias_that_names_another_element_is_a_conflict() -> None:
    result = _align(_finding(action="alias", element_kind="class", label="Carrier", target_id="cls-carrier", alias="Vendor"))
    assert result.proposals[0].proposal_type == "conflict"


def test_modify_unknown_target_is_discarded_and_noop_modify_is_reuse() -> None:
    result = _align(
        _finding(action="modify", element_kind="class", label="Pallet", target_id="cls-pallet", definition="x"),
        _finding(action="modify", element_kind="class", label="Product", target_id="cls-product"),
    )
    assert [d.term for d in result.discarded] == ["Pallet"]
    assert result.proposals[0].proposal_type == "reuse"


def test_modify_records_before_and_after_and_flags_breaking_changes() -> None:
    result = _align(
        _finding(
            action="modify", element_kind="object_property", label="ships to", target_id="op-ships-to",
            definition="Destination facility.", range="Warehouse",
        )
    )
    proposal = result.proposals[0]
    assert proposal.changes["range_id"] == {"before": "cls-facility", "after": "cls-warehouse"}
    assert proposal.changes["description"]["after"] == "Destination facility."
    assert any("breaking change" in note for note in proposal.alignment["notes"])


def test_new_properties_depend_on_new_classes_from_the_same_run() -> None:
    result = _align(
        _finding(action="add", element_kind="object_property", label="held at", domain="Inventory Lot", range="Warehouse"),
        _finding(action="add", element_kind="class", label="Inventory Lot", term="inventory lots"),
        _finding(action="add", element_kind="class", label="Inventory Lots", term="lots"),
    )
    classes = [p for p in result.proposals if p.element_kind == "class"]
    (relationship,) = [p for p in result.proposals if p.element_kind == "object_property"]
    assert len(classes) == 1, "duplicate class findings are merged"
    assert relationship.new_element["domain_id"] == classes[0].new_element["id"]
    assert relationship.new_element["range_id"] == "cls-warehouse"
    assert relationship.depends_on == [classes[0].key]
    assert len(classes[0].evidence) == 2


def test_unresolved_references_are_reported() -> None:
    result = _align(_finding(action="add", element_kind="datatype_property", label="lot size", domain="Unknown Thing"))
    proposal = result.proposals[0]
    assert proposal.new_element["domain_id"] is None
    assert any("could not be resolved" in note for note in proposal.alignment["notes"])


def test_relationship_with_literal_range_becomes_attribute() -> None:
    result = _align(
        _finding(action="add", element_kind="object_property", label="inspection date", domain="Shipment", range="xsd:date")
    )
    proposal = result.proposals[0]
    assert proposal.element_kind == "datatype_property"
    assert proposal.new_element["datatype"] == "date" and proposal.new_element["domain_id"] == "cls-shipment"
    assert "range_id" not in proposal.new_element
    assert any("literal datatype" in note for note in proposal.alignment["notes"])
    assert proposal.title == "Add attribute 'inspection date'"
    assert proposal.llm_output["element_kind"] == "object_property", "original model output is preserved"
