"""Knowledge-graph quality indicators with explicit definitions.

Every metric states its numerator, denominator and calculation. These are pipeline, structural and
provenance indicators computed from persisted build data; they are not measures of factual
precision or recall, which would require a labelled ground-truth sample that does not exist.
"""

from collections import Counter
from typing import Any

from app.core.ids import utcnow
from app.modules.kg.models import KgCandidateFact, KgEntity, KgOntologyGap
from app.modules.kg.ontology_view import OntologyView

DISCLAIMER = (
    "These indicators describe what the pipeline extracted, validated and stored. They do not measure "
    "factual precision or recall: no labelled ground-truth sample has been evaluated, and an accepted "
    "fact is one that passed structural and evidence checks, not one proven to be true."
)

CHECK_LABELS = {
    "predicate_defined": "Relationship not defined in the ontology version",
    "property_defined": "Attribute not defined in the ontology version",
    "class_defined": "Class not defined in the ontology version",
    "subject_class": "Subject class not defined",
    "object_class": "Object class not defined",
    "subject_reference": "Subject does not refer to an extracted entity",
    "object_reference": "Object does not refer to an extracted entity",
    "direction": "Relationship direction reversed",
    "domain": "Domain violation",
    "range": "Range violation",
    "literal_datatype": "Value does not match the datatype",
    "identifier_present": "Missing identifier",
    "subject_identifier": "Subject missing identifier",
    "object_identifier": "Object missing identifier",
    "unambiguous": "Ambiguous entity match",
    "subject_unambiguous": "Ambiguous subject",
    "object_unambiguous": "Ambiguous object",
    "single_value": "Conflicting value for a single-valued attribute",
    "supporting_evidence": "Evidence missing, not located or not supportive",
    "subject_established": "Subject not established by a source",
    "object_established": "Object not established by a source",
}


def _metric(
    key: str,
    label: str,
    value: float | int,
    definition: str,
    *,
    numerator: int | None = None,
    denominator: int | None = None,
    unit: str = "count",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "numerator": numerator,
        "denominator": denominator,
        "definition": definition,
    }


def _rate(key: str, label: str, numerator: int, denominator: int, definition: str) -> dict[str, Any]:
    value = round(numerator / denominator, 4) if denominator else 0.0
    return _metric(key, label, value, definition, numerator=numerator, denominator=denominator, unit="ratio")


def compute_evaluation(
    *,
    view: OntologyView,
    facts: list[KgCandidateFact],
    entities: list[KgEntity],
    gaps: list[KgOntologyGap],
    stats: dict[str, Any],
    graph_counts: tuple[int, int],
    unprovenanced_graph_elements: int,
) -> dict[str, Any]:
    by_status = Counter(f.status for f in facts)
    by_kind: dict[str, Counter[str]] = {}
    for fact in facts:
        by_kind.setdefault(fact.kind, Counter())[fact.status] += 1
    total = len(facts)
    accepted = by_status.get("accepted", 0)
    rel = by_kind.get("relationship", Counter())
    rel_total = sum(rel.values())
    attr = by_kind.get("attribute", Counter())
    attr_total = sum(attr.values())

    accepted_facts = [f for f in facts if f.status == "accepted"]
    classes_used = {f.subject_class_id for f in accepted_facts if f.kind == "type" and f.subject_class_id}
    relations_used = {f.predicate_id for f in accepted_facts if f.kind == "relationship" and f.predicate_id}
    attributes_used = {f.predicate_id for f in accepted_facts if f.kind == "attribute" and f.predicate_id}
    weak_provenance = sum(1 for f in facts if (f.evidence or {}).get("status") != "supported")

    accepted_entities = [e for e in entities if e.status == "accepted"]
    accepted_values: dict[str, set[str]] = {}
    for fact in accepted_facts:
        if fact.kind == "attribute" and fact.subject_entity_id and fact.predicate_id:
            accepted_values.setdefault(fact.subject_entity_id, set()).add(fact.predicate_id)
    incomplete = 0
    for entity in accepted_entities:
        required = {p.id for p in view.required_attributes(entity.class_id or "")}
        if required - accepted_values.get(entity.id, set()):
            incomplete += 1

    gap_counts = Counter(g.gap_type for g in gaps)
    failure_codes: Counter[str] = Counter()
    for fact in facts:
        if fact.status == "accepted":
            continue
        for group in ("structural", "resolution", "evidence"):
            for check in (getattr(fact, group) or {}).get("checks", []):
                if not check.get("passed", True):
                    failure_codes[check["code"]] += 1

    resolution = stats.get("resolution", {})
    sources = stats.get("sources", {})
    extraction = stats.get("extraction", {})
    vertices, edges = graph_counts

    sections = [
        {
            "key": "sources",
            "title": "Sources processed",
            "metrics": [
                _metric(
                    "structured_sources", "Structured sources", sources.get("structured", 0),
                    "Number of structured (CSV) sources read through their saved mappings.",
                ),
                _metric(
                    "records", "Records read", sources.get("records", 0),
                    "Data rows read from structured sources (header rows excluded).",
                ),
                _metric(
                    "documents", "Documents processed", sources.get("documents", 0),
                    "Number of PDF/text documents sent to ontology-guided extraction.",
                ),
                _metric(
                    "chunks_analyzed", "Text chunks analysed", sources.get("chunks_analyzed", 0),
                    "Chunks sent to the LLM / chunks available in the selected documents (limited by the build's "
                    "maximum chunk setting).",
                    numerator=sources.get("chunks_analyzed", 0), denominator=sources.get("chunks_total", 0),
                ),
                _metric(
                    "llm_batches", "LLM batches completed", extraction.get("batches_completed", 0),
                    "Extraction requests that returned schema-valid output / requests made.",
                    numerator=extraction.get("batches_completed", 0), denominator=extraction.get("batches", 0),
                ),
            ],
        },
        {
            "key": "extraction",
            "title": "Extraction",
            "metrics": [
                _metric(
                    "entity_mentions", "Entity mentions extracted", resolution.get("mentions", 0),
                    "Entity occurrences produced by mappings (one per mapped entity per row) and by the LLM.",
                ),
                _metric(
                    "entities", "Resolved entities", len(entities),
                    "Distinct entities after entity resolution.",
                ),
                _metric(
                    "relationship_candidates", "Relationships extracted", rel_total,
                    "Candidate relationship facts before validation (all origins).",
                ),
                _metric(
                    "attribute_candidates", "Attribute values extracted", attr_total,
                    "Candidate attribute facts before validation (all origins).",
                ),
            ],
        },
        {
            "key": "validation",
            "title": "Fact validation",
            "metrics": [
                _metric("candidate_facts", "Candidate facts", total,
                        "All candidate facts: entity type facts + relationship facts + attribute facts."),
                _metric("accepted", "Accepted facts", accepted, "Facts that passed structural and evidence validation."),
                _metric("rejected", "Rejected facts", by_status.get("rejected", 0),
                        "Facts that failed structural validation, or had no evidence at all."),
                _metric("quarantined", "Quarantined facts", by_status.get("quarantined", 0),
                        "Structurally valid facts held back for inadequate evidence, ambiguity or conflicts."),
                _rate("acceptance_rate", "Acceptance rate", accepted, total,
                      "Accepted facts / candidate facts (all kinds)."),
                _rate("relationship_acceptance_rate", "Relationship acceptance rate", rel.get("accepted", 0), rel_total,
                      "Accepted relationship facts / candidate relationship facts."),
            ],
        },
        {
            "key": "coverage",
            "title": "Ontology coverage",
            "metrics": [
                _rate("class_coverage", "Classes populated", len(classes_used), len(view.classes),
                      f"Classes with at least one graph node / classes in {view.name} {view.version}."),
                _rate("relationship_coverage", "Relationships used", len(relations_used), len(view.object_properties),
                      f"Relationship types with at least one graph edge / relationship types in {view.version}."),
                _rate("attribute_coverage", "Attributes used", len(attributes_used), len(view.datatype_properties),
                      f"Attributes with at least one accepted value / attributes in {view.version}."),
                _metric("unknown_classes", "Missing class mappings", gap_counts.get("unknown_class", 0),
                        "Distinct entity types in the sources that the ontology version does not define."),
                _metric("unknown_relationships", "Missing relationship mappings",
                        gap_counts.get("unknown_relationship", 0),
                        "Distinct relationship types in the sources that the ontology version does not define."),
                _metric("unknown_attributes", "Missing attribute mappings", gap_counts.get("unknown_attribute", 0),
                        "Distinct attributes stated in documents that the ontology version does not define."),
                _metric("unmapped_fields", "Unmapped source fields", gap_counts.get("unmapped_field", 0),
                        "Populated structured-source columns not used by any mapping."),
            ],
        },
        {
            "key": "provenance",
            "title": "Provenance and completeness",
            "metrics": [
                _rate("weak_provenance", "Facts lacking adequate provenance", weak_provenance, total,
                      "Candidate facts whose evidence status is not 'supported' (weak, unlocated or missing) / "
                      "candidate facts."),
                _metric("graph_elements_without_provenance", "Graph elements without provenance",
                        unprovenanced_graph_elements,
                        "Graph nodes and edges with no linked accepted fact (expected to be 0)."),
                _rate("incomplete_entities", "Entities missing required attributes", incomplete, len(accepted_entities),
                      "Accepted entities lacking a value for an attribute marked required in the ontology / "
                      "accepted entities."),
                _metric("graph_nodes", "Graph nodes", vertices, "Nodes persisted in the graph store for this build."),
                _metric("graph_edges", "Graph edges", edges,
                        "Edges persisted for this build; duplicate facts from several sources share one edge."),
            ],
        },
        {
            "key": "resolution",
            "title": "Entity resolution",
            "metrics": [
                _metric("merged_mentions", "Mentions merged", resolution.get("merged_mentions", 0),
                        "Entity mentions - resolved entities (mentions merged into an existing entity)."),
                _metric("business_key_matches", "Matched by business key", resolution.get("mentions_business_key", 0),
                        "Mentions resolved by class + identifier."),
                _metric("label_alias_matches", "Matched by label or alias",
                        resolution.get("mentions_label", 0) + resolution.get("mentions_alias", 0),
                        "Mentions without an identifier matched to exactly one identified entity by name or "
                        "configured alias."),
                _metric("ambiguous_entities", "Ambiguous entities", resolution.get("ambiguous_entities", 0),
                        "Names matching more than one entity; flagged and not merged."),
                _metric("unresolved_class_entities", "Entities of unknown classes",
                        resolution.get("unresolved_class_entities", 0),
                        "Entities whose class is not defined in the ontology version."),
            ],
        },
    ]
    return {
        "generated_at": utcnow().isoformat(),
        "ontology_version": view.version,
        "disclaimer": DISCLAIMER,
        "sections": sections,
        "status_counts": dict(by_status),
        "kind_status_counts": {k: dict(v) for k, v in by_kind.items()},
        "failure_reasons": [
            {"code": code, "label": CHECK_LABELS.get(code, code), "count": count}
            for code, count in failure_codes.most_common()
        ],
    }
