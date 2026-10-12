"""Graph Compatibility Report: what a target preserves of an ontology version and a build (Phase 4.4).

Generated per (ontology version, projection, capability profile, mapping profile) and stored on
every deployment. A report with *semantic loss* rows requires an explicit acknowledgement before
deployment.
"""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.graph.capabilities import CapabilityProfile, MappingProfile
from app.modules.graph.projection import PropertyGraphProjection
from app.modules.registry.snapshot import OntologySnapshot

Outcome = Literal["native", "transformed", "partial", "unsupported", "semantic_loss"]


class CompatibilityRow(BaseModel):
    feature: str
    scope: Literal["data", "ontology"]
    outcome: Outcome
    detail: str
    recommendation: str = ""
    affected: int = 0


class CompatibilityReport(BaseModel):
    target_kind: str
    capability_profile: str
    capability_profile_verified: bool
    mapping_profile: str
    data_model: str
    rows: list[CompatibilityRow]
    counts: dict[str, int]
    has_semantic_loss: bool
    summary: str
    data_features: dict[str, int] = Field(default_factory=dict)


def data_features(projection: PropertyGraphProjection | None) -> dict[str, int]:
    if projection is None:
        return {}
    multi_valued = 0
    values = 0
    for vertex in projection.vertices:
        for key, value in vertex.properties.items():
            if key in ("identifier", "aliases") or value is None:
                continue
            items = value if isinstance(value, list) else [value]
            values += len(items)
            multi_valued += 1 if len(items) > 1 else 0
    return {
        "entities": len(projection.vertices),
        "relationships": len(projection.edges),
        "attribute_values": values,
        "multi_valued_attributes": multi_valued,
        # The extraction model assigns one class per entity and produces untagged literals.
        "multi_typed_entities": 0,
        "language_tagged_values": 0,
    }


def analyze(
    snapshot: OntologySnapshot,
    projection: PropertyGraphProjection | None,
    profile: CapabilityProfile,
    mapping: MappingProfile,
    *,
    features: dict[str, int] | None = None,
) -> CompatibilityReport:
    f = features if features is not None else data_features(projection)
    rdf = profile.data_model == "rdf"
    ontology_stored = rdf and profile.stores_ontology and mapping.include_ontology
    classes = snapshot.classes
    subclass = sum(len(c.parent_ids) for c in classes)
    restrictions = sum(len(c.semantics.restrictions) for c in classes)
    disjoint_equivalent = sum(len(c.semantics.disjoint_ids) + len(c.semantics.equivalent_ids) for c in classes)
    characteristics = sum(
        len(p.semantics.characteristics) + (1 if p.semantics.inverse_id else 0) for p in snapshot.object_properties
    )
    language = sum(
        1 for e in (*classes, *snapshot.object_properties, *snapshot.datatype_properties) if e.semantics.annotation_language
    )
    axioms = sum(1 for a in snapshot.extension_axioms if a.scope == "ontology")
    rows: list[CompatibilityRow] = []

    def row(feature: str, scope: Literal["data", "ontology"], outcome: Outcome, detail: str, recommendation: str = "", affected: int = 0) -> None:
        rows.append(CompatibilityRow(feature=feature, scope=scope, outcome=outcome, detail=detail,
                                     recommendation=recommendation, affected=affected))

    # ------------------------------------------------------------------ data
    if profile.multi_typing == "single-label" and f.get("multi_typed_entities", 0):
        row("Entities with several classes", "data", "semantic_loss",
            "Only one label per vertex: additional classes are dropped.", "Use a mapping profile with a types list.",
            f["multi_typed_entities"])
    row("Class membership", "data", "native",
        "rdf:type with the class IRI" if rdf else f"Vertex label = class local name ({profile.multi_typing})",
        affected=f.get("entities", 0))
    row("Entity identity", "data", "native" if rdf else "transformed",
        "Instance IRIs {data_namespace}e/{vertex_id}" if rdf else "Vertex id = deterministic vertex id; IRI derivable",
        affected=f.get("entities", 0))
    row("Typed attribute values", "data", "native" if profile.typed_literals else "transformed",
        "Typed literals (xsd datatypes of the ontology)" if profile.typed_literals
        else "Stored as strings; the datatype is defined by the ontology property",
        affected=f.get("attribute_values", 0))
    if profile.typed_literals and rdf and f.get("attribute_values", 0):
        row("Lexical form of typed values", "data", "transformed",
            "Values are preserved, but the store may return canonical lexical forms (for example 007 as 7, 12.50 as "
            "12.5). The original text remains in the canonical fact store.", affected=f["attribute_values"])
    row("Multi-valued attributes", "data", "native" if rdf else "transformed",
        "One triple per value" if rdf else "List property", affected=f.get("multi_valued_attributes", 0))
    if f.get("language_tagged_values", 0):
        row("Language-tagged values", "data", "native" if profile.language_tags else "semantic_loss",
            "Language tags kept" if profile.language_tags else "Language tags are dropped",
            "" if profile.language_tags else "Deploy to an RDF target to keep language tags.", f["language_tagged_values"])
    row("Relationship provenance", "data",
        "native" if profile.statement_metadata == "edge-properties" else "transformed",
        "Fact and source ids on edges" if profile.statement_metadata == "edge-properties"
        else "Companion provenance named graph (one resource per relationship); explorer provenance always comes from "
        "the canonical fact store", affected=f.get("relationships", 0))
    row("Build isolation", "data", "native" if profile.named_graphs else "transformed",
        "One named graph per build" if profile.named_graphs else "Build id as graph scope")

    # ------------------------------------------------------------------ ontology
    row("Class hierarchy (rdfs:subClassOf)", "ontology", "native" if ontology_stored else "partial",
        "Ontology graph deployed alongside the data" if ontology_stored
        else "The hierarchy is not stored with the data; queries must expand subclasses",
        "" if ontology_stored else "Use rdf-default/1 on an RDF target to store the ontology.", subclass)
    if restrictions:
        row("OWL restrictions", "ontology", "partial" if ontology_stored else "unsupported",
            "Stored in the ontology graph; not enforced by the store (no reasoner assumed)" if ontology_stored
            else "Not representable in the target", "Enforced before load where SHACL shapes exist.", restrictions)
    if disjoint_equivalent:
        row("Disjointness and equivalence", "ontology", "partial" if ontology_stored else "unsupported",
            "Stored; inferences are not materialized" if ontology_stored else "Not representable in the target",
            affected=disjoint_equivalent)
    if characteristics:
        row("Property characteristics and inverses", "ontology", "partial" if ontology_stored else "unsupported",
            "Asserted direction only; entailments are not materialized", affected=characteristics)
    if language:
        row("Language-tagged annotations", "ontology", "native" if ontology_stored else "unsupported",
            "Kept in the ontology graph" if ontology_stored else "Ontology annotations are not stored in the target "
            "(they remain in the registry package)", affected=language)
    if axioms:
        row("Preserved extension axioms", "ontology", "native" if ontology_stored else "unsupported",
            "Included verbatim in the ontology graph" if ontology_stored
            else "Not stored in the target (they remain in the registry package)", affected=axioms)
    row("SHACL shapes", "ontology", "partial",
        "Validated before load by the application SHACL lane; the store does not enforce them",
        affected=len(snapshot.shapes))

    counts = dict(Counter(r.outcome for r in rows))
    loss = counts.get("semantic_loss", 0) > 0
    summary = (
        f"{profile.label}: {counts.get('native', 0)} native, {counts.get('transformed', 0)} transformed, "
        f"{counts.get('partial', 0)} partial, {counts.get('unsupported', 0)} unsupported, "
        f"{counts.get('semantic_loss', 0)} with semantic loss."
    )
    return CompatibilityReport(
        target_kind=profile.target_kind,
        capability_profile=f"{profile.id}/{profile.version}",
        capability_profile_verified=profile.verified,
        mapping_profile=mapping.id,
        data_model=profile.data_model,
        rows=rows,
        counts=counts,
        has_semantic_loss=loss,
        summary=summary,
        data_features=f,
    )
