"""Typed API contracts for knowledge-graph engineering."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.governance.schemas import ProposalSummary
from app.modules.graph.compatibility import CompatibilityReport
from app.modules.kg.mapping import MappingSpec
from app.modules.kg.policy import DEFAULT_POLICY_ID, POLICIES

Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
BuildStatus = Literal["configured", "queued", "running", "completed", "failed"]
FactStatus = Literal["accepted", "rejected", "quarantined"]


# ---------------------------------------------------------------------------------- sources


class ColumnProfile(BaseModel):
    name: str
    non_empty: int
    distinct_values: int
    sample_values: list[str]
    inferred_datatype: str


class PreviewRow(BaseModel):
    row_number: int
    values: dict[str, str]


class SourcePreview(BaseModel):
    document_id: str
    filename: str
    media_type: str
    kind: Literal["table", "text"]
    columns: list[ColumnProfile] = Field(default_factory=list)
    rows: list[PreviewRow] = Field(default_factory=list)
    total_rows: int = 0
    page_count: int | None = None
    chunk_count: int = 0
    text_excerpt: str = ""


# ---------------------------------------------------------------------------------- versions


class PublishedVersionOption(BaseModel):
    version_id: str
    ontology_id: str
    ontology_name: str
    version: str
    published_at: datetime
    published_by: str
    class_count: int
    object_property_count: int
    datatype_property_count: int
    is_latest: bool


# ---------------------------------------------------------------------------------- mappings


class MappingIssueRead(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    path: str


class MappingCreate(BaseModel):
    document_id: str
    ontology_version_id: str = Field(description="Published version the mapping is validated against")
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    spec: MappingSpec
    updated_by: Actor


class MappingUpdate(BaseModel):
    ontology_version_id: str | None = None
    name: Name | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    spec: MappingSpec | None = None
    updated_by: Actor


class MappingRead(BaseModel):
    id: str
    project_id: str
    document_id: str
    document_name: str
    ontology_id: str
    ontology_version_id: str | None
    ontology_version: str | None
    name: str
    description: str
    spec: MappingSpec
    updated_by: str
    created_at: datetime
    updated_at: datetime
    issues: list[MappingIssueRead]


class MappingValidateRequest(BaseModel):
    document_id: str
    ontology_version_id: str
    spec: MappingSpec


class MappingValidation(BaseModel):
    valid: bool
    issues: list[MappingIssueRead]


class MappingSuggestion(BaseModel):
    spec: MappingSpec | None
    notes: list[str]
    issues: list[MappingIssueRead]


# ---------------------------------------------------------------------------------- builds


class BuildSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_chunks: int = Field(default=20, ge=1, le=200, description="Maximum document chunks sent to the LLM")
    batch_chars: int = Field(default=6000, ge=1000, le=20000, description="Characters of text per LLM request")
    extract_attributes: bool = Field(default=True, description="Also extract attribute values from documents")
    instructions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
    validation_policy: str = Field(default=DEFAULT_POLICY_ID, description="Validation policy id (key/version)")
    llm_config_id: str | None = Field(default=None, description="Registered LLM configuration; None = project default")
    graph_connection_id: str | None = Field(default=None, description="Graph target; None = project default")

    @field_validator("validation_policy")
    @classmethod
    def _known_policy(cls, value: str) -> str:
        if value not in POLICIES:
            raise ValueError(f"unknown validation policy '{value}'; use one of {', '.join(POLICIES)}")
        return value


class ValidationPolicyRead(BaseModel):
    id: str
    name: str
    description: str
    signature: str
    use_signature_shapes: bool
    entailment: bool
    shacl: dict[str, str]
    default: bool


class BuildCreate(BaseModel):
    name: Name | None = None
    ontology_version_id: str
    source_document_ids: list[str] = Field(min_length=1, max_length=50)
    mapping_ids: list[str] = Field(default_factory=list, max_length=50)
    settings: BuildSettings = Field(default_factory=BuildSettings)
    requested_by: Actor
    start: bool = False


class BuildUpdate(BaseModel):
    name: Name | None = None
    ontology_version_id: str | None = None
    source_document_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)
    mapping_ids: list[str] | None = Field(default=None, max_length=50)
    settings: BuildSettings | None = None


class BuildStart(BaseModel):
    requested_by: Actor


class RebuildRequest(BaseModel):
    ontology_version_id: str
    requested_by: Actor
    name: Name | None = None
    start: bool = False


class ReadinessIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class BuildReadiness(BaseModel):
    ready: bool
    issues: list[ReadinessIssue]


class BuildStage(BaseModel):
    key: str
    label: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    summary: str = ""
    counts: dict[str, Any] = Field(default_factory=dict)


class BuildSourceRead(BaseModel):
    id: str
    filename: str
    media_type: str
    kind: Literal["table", "text"]
    available: bool
    mapping_id: str | None = None
    mapping_name: str | None = None


class BuildSummary(BaseModel):
    id: str
    project_id: str
    number: int
    name: str
    status: BuildStatus
    ontology_id: str
    ontology_name: str
    ontology_version_id: str
    ontology_version: str
    parent_build_id: str | None
    current_stage: str | None
    stages_completed: int
    stage_count: int
    stats: dict[str, Any]
    graph_store: str | None
    provider: str | None
    model: str | None
    requested_by: str
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None


class BuildDetail(BuildSummary):
    sources: list[BuildSourceRead]
    mapping_ids: list[str]
    settings: BuildSettings
    stages: list[BuildStage]
    readiness: BuildReadiness | None
    prompt_version: str | None
    gap_count: int


class BuildLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: str
    level: str
    message: str
    details: dict[str, Any]
    created_at: datetime


# ---------------------------------------------------------------------------------- facts / entities


class FactSummary(BaseModel):
    id: str
    sequence: int
    kind: Literal["type", "relationship", "attribute"]
    origin: str
    status: FactStatus
    subject_entity_id: str | None
    subject_label: str
    subject_class_id: str | None
    subject_class_label: str | None
    predicate_id: str | None
    predicate_ref: str
    predicate_label: str
    object_entity_id: str | None
    object_label: str
    object_class_id: str | None
    object_class_label: str | None
    value: str | None
    datatype: str | None
    normalization_status: Literal["exact", "normalized", "ambiguous", "failed"] | None = Field(
        default=None,
        description="How the raw attribute value was typed; None for non-attribute facts and for builds created "
        "before value normalisation existed",
    )
    structural_passed: bool
    evidence_status: str
    resolution_passed: bool
    reasons: list[str]
    document_ids: list[str]
    source_label: str
    graph_element_id: str | None
    shacl_status: Literal["conforms", "Violation", "Warning", "Info"] | None = Field(
        default=None, description="Most severe SHACL result for the fact; None for builds evaluated before SHACL validation existed"
    )
    policy_id: str | None = None


class SourceExcerpt(BaseModel):
    document_id: str
    document_name: str
    available: bool
    page: int | None = None
    chunk_index: int | None = None
    text: str | None = None
    row_number: int | None = None
    record: dict[str, str] | None = None
    columns: list[str] | None = None


class FactDetail(FactSummary):
    structural: dict[str, Any]
    evidence: dict[str, Any]
    resolution: dict[str, Any]
    sources: list[dict[str, Any]]
    excerpts: list[SourceExcerpt]
    lanes: dict[str, Any] | None = Field(default=None, description="Policy, SHACL and entailment lanes")
    value_normalization: dict[str, Any] | None = Field(
        default=None,
        description="Audit record of the attribute value: raw value, normalised value, datatype, rule, status, unit, scale",
    )
    subject_vertex_id: str | None
    object_vertex_id: str | None
    build_id: str
    build_number: int
    ontology_version: str
    ontology_version_id: str


class FactPage(BaseModel):
    items: list[FactSummary]
    total: int
    status_counts: dict[str, int]
    kind_counts: dict[str, int]


class MentionRead(BaseModel):
    id: str
    origin: str
    class_ref: str
    identifier: str | None
    label: str | None
    reference_only: bool
    resolution_method: str
    document_id: str | None
    source: dict[str, Any]


class EntitySummary(BaseModel):
    id: str
    vertex_id: str
    class_id: str | None
    class_label: str
    label: str
    identifier: str | None
    resolution_method: str
    ambiguous: bool
    has_master_record: bool
    mention_count: int
    status: str


class EntityDetail(EntitySummary):
    aliases: list[str]
    candidates: list[dict[str, Any]]
    notes: list[str]
    type_fact_id: str | None
    mentions: list[MentionRead]


# ---------------------------------------------------------------------------------- graph


class GraphPropertyRead(BaseModel):
    key: str
    label: str
    property_id: str | None
    values: list[Any]


class GraphNodeRead(BaseModel):
    id: str
    label: str
    name: str
    class_id: str
    class_label: str
    identifier: str | None
    entity_id: str | None
    properties: list[GraphPropertyRead]
    fact_count: int
    source_ids: list[str]


class GraphEdgeRead(BaseModel):
    id: str
    label: str
    predicate_id: str
    predicate_label: str
    source: str
    target: str
    fact_count: int
    source_ids: list[str]


class FacetCount(BaseModel):
    id: str
    label: str
    count: int


class GraphRead(BaseModel):
    build_id: str
    build_number: int
    ontology_version: str
    graph_store: str | None
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]
    truncated: bool
    total_nodes: int
    total_edges: int
    classes: list[FacetCount]
    predicates: list[FacetCount]
    sources: list[FacetCount]
    # Set when the graph was read back from a deployment target instead of the canonical store.
    deployment_id: str | None = None
    read_warnings: list[str] = Field(default_factory=list)


class GraphElementDetail(BaseModel):
    kind: Literal["node", "edge"]
    node: GraphNodeRead | None = None
    edge: GraphEdgeRead | None = None
    subject: GraphNodeRead | None = None
    object: GraphNodeRead | None = None
    relationships: list[GraphEdgeRead] = Field(default_factory=list)
    neighbours: list[GraphNodeRead] = Field(default_factory=list)
    facts: list[FactDetail]
    build_id: str
    build_number: int
    ontology_version: str
    ontology_version_id: str
    project_id: str
    deployment_id: str | None = None


# ---------------------------------------------------------------------------------- evaluation & feedback


class MetricRead(BaseModel):
    key: str
    label: str
    value: float | int
    unit: str
    numerator: int | None
    denominator: int | None
    definition: str


class MetricSection(BaseModel):
    key: str
    title: str
    metrics: list[MetricRead]


class FailureReason(BaseModel):
    code: str
    label: str
    count: int


class EvaluationRead(BaseModel):
    build_id: str
    generated_at: datetime
    ontology_version: str
    disclaimer: str
    sections: list[MetricSection]
    status_counts: dict[str, int]
    kind_status_counts: dict[str, dict[str, int]]
    failure_reasons: list[FailureReason]


class GapProposalRef(BaseModel):
    id: str
    title: str
    status: str
    proposal_type: str


class GapRead(BaseModel):
    id: str
    build_id: str
    gap_type: Literal["unknown_class", "unknown_relationship", "unknown_attribute", "unmapped_field"]
    term: str
    label: str
    description: str
    suggestion: dict[str, Any]
    occurrences: int
    origins: list[str]
    evidence: list[dict[str, Any]]
    fact_ids: list[str]
    status: Literal["open", "proposed"]
    proposals: list[GapProposalRef]


class GapProposalRequest(BaseModel):
    gap_ids: list[str] = Field(min_length=1, max_length=50)
    requested_by: Actor
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ""


class DiscardedGap(BaseModel):
    term: str
    reason: str


class GapProposalResult(BaseModel):
    proposals: list[ProposalSummary]
    included_gap_ids: list[str]
    discarded: list[DiscardedGap]


class ElementDiff(BaseModel):
    added: int
    removed: int
    unchanged: int
    added_items: list[dict[str, str]]
    removed_items: list[dict[str, str]]


class MetricComparison(BaseModel):
    key: str
    label: str
    unit: str
    base: float | int | None
    target: float | int | None


class BuildComparison(BaseModel):
    base: BuildSummary
    target: BuildSummary
    nodes: ElementDiff
    edges: ElementDiff
    metrics: list[MetricComparison]


# ---------------------------------------------------------------------------------- graph deployments


class CapabilityProfileRead(BaseModel):
    id: str
    version: int
    target_kind: str
    label: str
    data_model: str
    query_languages: list[str]
    multi_typing: str
    named_graphs: bool
    language_tags: bool
    typed_literals: bool
    multi_valued_properties: bool
    statement_metadata: str
    stores_ontology: bool
    reasoning: str
    native_shacl: bool
    verified: bool
    notes: list[str]
    adapter_available: bool


class MappingProfileRead(BaseModel):
    id: str
    data_model: str
    label: str
    description: str
    include_ontology: bool
    include_provenance: bool


class GraphCapabilitiesRead(BaseModel):
    profiles: list[CapabilityProfileRead]
    mapping_profiles: list[MappingProfileRead]


class CompatibilityRead(BaseModel):
    build_id: str
    target_id: str | None
    target_name: str
    target_kind: str
    adapter_available: bool
    report: CompatibilityReport


class DeploymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]
    mapping_profile: str | None = None
    acknowledge_semantic_loss: bool = False
    requested_by: Actor


class DeploymentRead(BaseModel):
    id: str
    build_id: str
    build_number: int
    project_id: str
    target_id: str
    target_name: str
    target_kind: str
    data_model: str
    mapping_profile: str
    capability_profile: str
    data_namespace: str | None
    graphs: dict[str, str]
    compatibility: CompatibilityReport | None
    acknowledged_loss_by: str | None
    status: Literal["running", "completed", "failed", "superseded"]
    stats: dict[str, Any]
    error: str | None
    origin: Literal["build", "manual", "legacy"]
    requested_by: str
    created_at: datetime
    completed_at: datetime | None
    explorable: bool
    queryable: bool


class SparqlQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(min_length=1, max_length=20000)]
