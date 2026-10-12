"""Capability profiles of graph database targets and projection mapping profiles (Phase 4.4).

A capability profile states what a target can represent natively. ``verified`` marks profiles
checked against the implementation that ships with this release (the adapter and its integration
tests); unverified profiles are documented assumptions used only for compatibility *reports*
(no adapter exists for them). Having an RDF export or a SHACL plugin is never treated as native
enforcement.
"""

from dataclasses import asdict, dataclass, field
from typing import Literal

DataModel = Literal["rdf", "property-graph"]


@dataclass(frozen=True)
class CapabilityProfile:
    id: str
    version: int
    target_kind: str
    label: str
    data_model: DataModel
    query_languages: tuple[str, ...]
    multi_typing: Literal["rdf:type", "multiple-labels", "single-label"]
    named_graphs: bool
    language_tags: bool
    typed_literals: bool
    multi_valued_properties: bool
    statement_metadata: Literal["companion-graph", "edge-properties", "rdf-star", "none"]
    stores_ontology: bool
    reasoning: str
    native_shacl: bool
    verified: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


PROFILES: dict[str, CapabilityProfile] = {
    p.target_kind: p
    for p in (
        CapabilityProfile(
            id="local-sql", version=1, target_kind="local-sql", label="Local SQL property graph",
            data_model="property-graph", query_languages=(), multi_typing="single-label", named_graphs=False,
            language_tags=False, typed_literals=False, multi_valued_properties=True,
            statement_metadata="edge-properties", stores_ontology=False, reasoning="none", native_shacl=False,
            verified=True, notes=("Values are stored as JSON strings; the build id scopes the graph.",),
        ),
        CapabilityProfile(
            id="oxigraph", version=1, target_kind="oxigraph", label="Embedded Oxigraph",
            data_model="rdf", query_languages=("SPARQL 1.1",), multi_typing="rdf:type", named_graphs=True,
            language_tags=True, typed_literals=True, multi_valued_properties=True,
            statement_metadata="companion-graph", stores_ontology=True, reasoning="none", native_shacl=False,
            verified=True,
        ),
        CapabilityProfile(
            id="sparql-http", version=1, target_kind="sparql-http", label="SPARQL 1.1 endpoint (generic)",
            data_model="rdf", query_languages=("SPARQL 1.1",), multi_typing="rdf:type", named_graphs=True,
            language_tags=True, typed_literals=True, multi_valued_properties=True,
            statement_metadata="companion-graph", stores_ontology=True, reasoning="store-specific (not assumed)",
            native_shacl=False, verified=True,
            notes=(
                "Verified against the Oxigraph SPARQL server through the SPARQL 1.1 Protocol. Other stores implement "
                "the same protocol; their reasoning and SHACL features are not relied upon.",
            ),
        ),
        CapabilityProfile(
            id="neo4j", version=1, target_kind="neo4j", label="Neo4j 5 (assumed, no adapter)",
            data_model="property-graph", query_languages=("Cypher",), multi_typing="multiple-labels",
            named_graphs=False, language_tags=False, typed_literals=True, multi_valued_properties=True,
            statement_metadata="edge-properties", stores_ontology=False, reasoning="none", native_shacl=False,
            verified=False,
            notes=("Lists must be homogeneous; constraints depend on the edition.",),
        ),
        CapabilityProfile(
            id="cosmos-gremlin", version=1, target_kind="cosmos-gremlin", label="Azure Cosmos DB Gremlin (assumed, no adapter)",
            data_model="property-graph", query_languages=("Gremlin",), multi_typing="single-label",
            named_graphs=False, language_tags=False, typed_literals=True, multi_valued_properties=True,
            statement_metadata="edge-properties", stores_ontology=False, reasoning="none", native_shacl=False,
            verified=False,
            notes=("Requires a partition key; supported Gremlin steps are a subset of TinkerPop.",),
        ),
    )
}


@dataclass(frozen=True)
class MappingProfile:
    """How the ontology-level projection is mapped to a target model. Versioned and immutable."""

    id: str
    data_model: DataModel
    label: str
    description: str
    include_ontology: bool = True
    include_provenance: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


MAPPING_PROFILES: dict[str, MappingProfile] = {
    m.id: m
    for m in (
        MappingProfile(
            id="rdf-default/1",
            data_model="rdf",
            label="RDF with ontology and provenance",
            description=(
                "Instance IRIs {data_namespace}e/{vertex_id}; rdf:type with the class IRI; typed literals; "
                "relationships with the property IRI; one named graph per build, plus a provenance graph "
                "(fact and source ids per element) and the published ontology graph."
            ),
        ),
        MappingProfile(
            id="rdf-data-only/1",
            data_model="rdf",
            label="RDF data and provenance only",
            description="As rdf-default/1 without the ontology graph (for stores whose ontology is managed separately).",
            include_ontology=False,
        ),
        MappingProfile(
            id="lpg-default/1",
            data_model="property-graph",
            label="Property graph",
            description=(
                "Vertex label = class local name; edge label = property local name; attributes keyed by local "
                "name (multi-valued as lists); fact and source ids on vertices and edges; build id as scope."
            ),
        ),
    )
}


def default_mapping_profile(data_model: DataModel) -> MappingProfile:
    return MAPPING_PROFILES["rdf-default/1" if data_model == "rdf" else "lpg-default/1"]
