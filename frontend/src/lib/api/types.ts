export type XsdDatatype =
  | 'string'
  | 'integer'
  | 'decimal'
  | 'boolean'
  | 'date'
  | 'dateTime'
  | 'anyURI'
  | 'float'
  | 'double'
  | 'int'
  | 'long'
  | 'time'
  | 'gYear'

export const XSD_DATATYPES: readonly XsdDatatype[] = [
  'string',
  'integer',
  'decimal',
  'boolean',
  'date',
  'dateTime',
  'anyURI',
  'float',
  'double',
  'int',
  'long',
  'time',
  'gYear',
]

export interface Health {
  status: 'ok' | 'degraded'
  app: string
  version: string
  environment: string
  database: string
}

export interface Project {
  id: string
  name: string
  description: string
  business_domain: string
  ontology_count: number
  default_llm_config_id: string
  default_discovery_llm_config_id: string
  default_kg_llm_config_id: string
  default_graph_connection_id: string
  data_namespace: string | null
  created_at: string
  updated_at: string
}

export interface PrefixBinding {
  prefix: string
  namespace: string
}

export interface OntologyMetadata {
  name: string
  namespace: string
  prefix: string
  description: string
  /** Phase 4 ontology header. Omitted fields are left unchanged by the backend on save. */
  ontology_iri?: string | null
  prefixes?: PrefixBinding[]
  imports?: string[]
  require_domain_range?: boolean
}

export interface ProjectCreate {
  name: string
  description?: string
  business_domain?: string
  initial_ontology?: OntologyMetadata | null
  default_llm_config_id?: string | null
  default_discovery_llm_config_id?: string | null
  default_kg_llm_config_id?: string | null
  default_graph_connection_id?: string | null
}

export interface OntologyStats {
  class_count: number
  object_property_count: number
  datatype_property_count: number
}

export interface PublishedVersionRef {
  id: string
  version: string
  draft_revision: number
  published_at: string
}

export interface Ontology extends OntologyMetadata {
  id: string
  project_id: string
  ontology_iri: string | null
  prefixes: PrefixBinding[]
  imports: string[]
  require_domain_range: boolean
  draft_revision: number
  stats: OntologyStats
  latest_version: PublishedVersionRef | null
  created_at: string
  updated_at: string
}

// ------------------------------------------------------------------ OWL semantics (Phase 4)

export type Characteristic =
  | 'functional'
  | 'inverse_functional'
  | 'transitive'
  | 'symmetric'
  | 'asymmetric'
  | 'reflexive'
  | 'irreflexive'

export const CHARACTERISTICS: readonly Characteristic[] = [
  'functional',
  'inverse_functional',
  'transitive',
  'symmetric',
  'asymmetric',
  'reflexive',
  'irreflexive',
]

export type RestrictionKind = 'some' | 'all' | 'has_value' | 'min' | 'max' | 'exact'

export interface Restriction {
  property_id: string
  kind: RestrictionKind
  class_id?: string | null
  datatype?: XsdDatatype | null
  value?: string | null
  cardinality?: number | null
}

export type DescriptionPredicate = 'skos:definition' | 'rdfs:comment'

interface BaseSemantics {
  deprecated?: boolean
  equivalent_ids?: string[]
  annotation_language?: string | null
  description_predicate?: DescriptionPredicate
}

export interface ClassSemantics extends BaseSemantics {
  disjoint_ids?: string[]
  restrictions?: Restriction[]
}

export interface ObjectPropertySemantics extends BaseSemantics {
  parent_ids?: string[]
  inverse_id?: string | null
  characteristics?: Characteristic[]
}

export interface DatatypePropertySemantics extends BaseSemantics {
  parent_ids?: string[]
  functional?: boolean
  range_declared?: boolean
}

export interface ClassDefinition {
  id: string
  local_name: string
  label: string
  description: string
  aliases: string[]
  parent_ids: string[]
  /** Persisted IRI; locked once the element is published. Omit to let the server mint it. */
  iri?: string | null
  semantics?: ClassSemantics
}

export interface ObjectPropertyDefinition {
  id: string
  local_name: string
  label: string
  description: string
  aliases: string[]
  domain_id: string | null
  range_id: string | null
  iri?: string | null
  semantics?: ObjectPropertySemantics
}

export interface DatatypePropertyDefinition {
  id: string
  local_name: string
  label: string
  description: string
  aliases: string[]
  domain_id: string | null
  datatype: XsdDatatype
  required: boolean
  multi_valued: boolean
  iri?: string | null
  semantics?: DatatypePropertySemantics
}

export interface Position {
  x: number
  y: number
}

export interface DiagramLayout {
  positions: Record<string, Position>
}

export interface OntologyDraft {
  ontology: Ontology
  draft_revision: number
  classes: ClassDefinition[]
  object_properties: ObjectPropertyDefinition[]
  datatype_properties: DatatypePropertyDefinition[]
  layout: DiagramLayout
  /** Elements of the latest published version (their IRIs are locked). */
  locked_iri_ids?: string[]
}

export interface DraftSaveRequest {
  base_revision: number
  metadata: OntologyMetadata
  classes: ClassDefinition[]
  object_properties: ObjectPropertyDefinition[]
  datatype_properties: DatatypePropertyDefinition[]
  layout: DiagramLayout
}

export interface ElementChangeCounts {
  added: number
  updated: number
  removed: number
}

export interface DraftChangeSummary {
  metadata_changed: boolean
  classes: ElementChangeCounts
  object_properties: ElementChangeCounts
  datatype_properties: ElementChangeCounts
  layout_changed: boolean
}

export interface DraftSaveResponse {
  draft: OntologyDraft
  changes: DraftChangeSummary
  revision_incremented: boolean
}

export type Severity = 'error' | 'warning' | 'info'
export type ElementKind = 'ontology' | 'class' | 'object_property' | 'datatype_property'

export interface ValidationIssue {
  code: string
  severity: Severity
  message: string
  element_kind: ElementKind
  element_id: string | null
  element_label: string | null
  field: string | null
  related_element_ids: string[]
}

export interface ValidationReport {
  id: string
  ontology_id: string
  draft_revision: number
  current_draft_revision: number
  is_current: boolean
  is_valid: boolean
  error_count: number
  warning_count: number
  info_count: number
  issues: ValidationIssue[]
  created_at: string
}

export interface ActivityEvent {
  id: string
  project_id: string
  ontology_id: string | null
  event_type: string
  summary: string
  details: Record<string, unknown>
  created_at: string
}

// ----------------------------------------------------------------------------- Phase 2: LLM & sources

export interface LLMStatus {
  configured: boolean
  config_name?: string | null
  provider: string | null
  model: string | null
  endpoint_host: string | null
  structured_output: string | null
  reachable: boolean | null
  model_available: boolean | null
  detail: string
}

export interface SourceDocument {
  id: string
  project_id: string
  filename: string
  media_type: string
  size_bytes: number
  sha256: string
  page_count: number | null
  char_count: number
  chunk_count: number
  uploaded_by: string
  created_at: string
}

// ----------------------------------------------------------------------------- Phase 2: discovery

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface DiscardedFinding {
  term: string
  action: string
  element_kind: string
  reason: string
}

export interface DiscoveryRun {
  id: string
  ontology_id: string
  status: RunStatus
  baseline_kind: 'draft' | 'version'
  baseline_label: string
  baseline_version_id: string | null
  baseline_draft_revision: number | null
  documents: { id: string; filename: string | null }[]
  instructions: string
  provider: string
  model: string
  prompt_version: string
  progress: { total_batches?: number; completed_batches?: number; chunks_total?: number; chunks_analyzed?: number }
  stats: {
    findings?: number
    proposals?: number
    discarded?: number
    by_type?: Partial<Record<ProposalType, number>>
    failed_batches?: number
  }
  discarded: DiscardedFinding[]
  usage: { prompt_tokens?: number; completion_tokens?: number }
  error: string | null
  requested_by: string
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface DiscoveryRunCreate {
  document_ids: string[]
  baseline_version_id?: string | null
  instructions?: string
  requested_by?: string
  llm_config_id?: string | null
}

// ----------------------------------------------------------------------------- Phase 2: governance

export type ProposalType = 'add' | 'reuse' | 'alias' | 'modify' | 'conflict'
export type ProposalStatus = 'pending' | 'approved' | 'rejected' | 'needs_refinement' | 'applied'
export type ProposalElementKind = 'class' | 'object_property' | 'datatype_property'

export interface FieldChangeValue {
  before: unknown
  after: unknown
}

export interface ProposalSummary {
  id: string
  ontology_id: string
  run_id: string | null
  origin: 'discovery' | 'kg_build'
  kg_build_id: string | null
  proposal_type: ProposalType
  element_kind: ProposalElementKind
  status: ProposalStatus
  title: string
  term: string
  confidence: number | null
  target_element_id: string | null
  target_label: string | null
  new_element_id: string | null
  evidence_count: number
  edited: boolean
  applied_draft_revision: number | null
  apply_error: string | null
  created_at: string
  updated_at: string
}

export interface ProposalEvidence {
  id: string
  document_id: string | null
  document_name: string
  chunk_id: string | null
  page: number | null
  quote: string
  context: string
  start_offset: number | null
  end_offset: number | null
  verified: boolean
  created_at: string
}

export interface ProposalEvent {
  id: string
  event_type: string
  actor: string
  comment: string
  details: Record<string, unknown>
  created_at: string
}

export interface AlignmentMatch {
  element_id: string
  element_kind: ProposalElementKind
  label: string
  score: number
  match_type: 'exact' | 'alias' | 'similar'
  matched_name: string
}

export interface ProposalImpact {
  applicable: boolean
  reason: string | null
  blocking: boolean
  introduced_issues: ValidationIssue[]
  resolved_issues: ValidationIssue[]
}

export interface ProposalDetail extends ProposalSummary {
  rationale: string
  new_element: Record<string, unknown> | null
  changes: Record<string, FieldChangeValue>
  alignment: { llm_action?: ProposalType; matches?: AlignmentMatch[]; notes?: string[] }
  depends_on: string[]
  llm_output: Record<string, unknown> | null
  target: Record<string, unknown> | null
  evidence: ProposalEvidence[]
  events: ProposalEvent[]
  impact: ProposalImpact | null
}

export interface ProposalUpdate {
  actor: string
  comment?: string
  proposal_type?: ProposalType
  target_element_id?: string | null
  new_element?: Record<string, unknown> | null
  after?: Record<string, unknown> | null
  alias?: string | null
  rationale?: string | null
}

export type Decision = 'approve' | 'reject' | 'request_refinement' | 'reopen'

export interface ProposalStats {
  total: number
  awaiting_review: number
  approved_not_applied: number
  by_status: Partial<Record<ProposalStatus, number>>
  by_type: Partial<Record<ProposalType, number>>
}

export interface ApplyResult {
  applied: ProposalSummary[]
  failed: { proposal_id: string; title: string; reason: string }[]
  draft_revision: number
  revision_incremented: boolean
  changes: DraftChangeSummary
}

// ----------------------------------------------------------------------------- Phase 2: registry

export type ArtifactFormat = 'json' | 'turtle' | 'rdfxml' | 'jsonld' | 'ntriples' | 'shapes' | 'manifest'

export interface VersionArtifact {
  format: ArtifactFormat
  filename: string
  media_type: string
  sha256: string
  size: number
}

export interface VersionSummary {
  id: string
  ontology_id: string
  version: string
  sequence: number
  draft_revision: number
  content_hash: string
  class_count: number
  object_property_count: number
  datatype_property_count: number
  change_summary: Record<string, unknown>
  validation_summary: { is_valid?: boolean; error_count?: number; warning_count?: number; info_count?: number }
  previous_version_id: string | null
  release_notes: string
  published_by: string
  published_at: string
  artifacts: VersionArtifact[]
  snapshot_format: 'ols.ontology-snapshot/1' | 'ols.ontology-snapshot/2'
  package_format: string
}

export interface VersionDetail extends VersionSummary {
  snapshot: {
    format: 'ols.ontology-snapshot/1' | 'ols.ontology-snapshot/2'
    metadata: OntologyMetadata
    classes: ClassDefinition[]
    object_properties: ObjectPropertyDefinition[]
    datatype_properties: DatatypePropertyDefinition[]
    extension_axioms?: ExtensionAxiom[]
  }
}

export interface FieldChange {
  field: string
  before: unknown
  after: unknown
}

export interface ElementChange {
  element_id: string
  element_kind: ProposalElementKind
  label: string
  change: 'added' | 'removed' | 'modified'
  fields: FieldChange[]
}

export type VersionBump = 'major' | 'minor' | 'patch'

export interface SchemaDiff {
  from_label: string
  to_label: string
  metadata_changes: FieldChange[]
  elements: ElementChange[]
  summary: Record<ProposalElementKind, { added: number; removed: number; modified: number }>
  breaking_changes: string[]
  suggested_bump: VersionBump | 'none'
  has_changes: boolean
  axiom_changes?: { axiom_id: string; kind: string; summary: string; change: 'added' | 'removed' }[]
  shape_changes?: { shape_id: string; label: string; change: 'added' | 'removed' | 'modified' }[]
  notes?: string[]
}

export interface PublishPreview {
  ontology_id: string
  draft_revision: number
  latest_version: VersionSummary | null
  validation: {
    is_valid: boolean
    error_count: number
    warning_count: number
    info_count: number
    blocking_issues: ValidationIssue[]
  }
  diff: SchemaDiff
  suggested_version: string
  can_publish: boolean
  blockers: string[]
  proposals_awaiting_review: number
  proposals_approved_not_applied: number
}

export interface PublishRequest {
  published_by: string
  release_notes?: string
  version?: string | null
  bump?: VersionBump | null
  expected_draft_revision?: number | null
}
// ------------------------------------------------------------------------- knowledge graph (Phase 3)

export interface ColumnProfile {
  name: string
  non_empty: number
  distinct_values: number
  sample_values: string[]
  inferred_datatype: string
}

export interface SourcePreview {
  document_id: string
  filename: string
  media_type: string
  kind: 'table' | 'text'
  columns: ColumnProfile[]
  rows: { row_number: number; values: Record<string, string> }[]
  total_rows: number
  page_count: number | null
  chunk_count: number
  text_excerpt: string
}

export interface PublishedVersionOption {
  version_id: string
  ontology_id: string
  ontology_name: string
  version: string
  published_at: string
  published_by: string
  class_count: number
  object_property_count: number
  datatype_property_count: number
  is_latest: boolean
}

export interface AttributeMapping {
  column: string
  property_id: string
}

export interface EntityMapping {
  key: string
  class_id: string | null
  class_column: string | null
  id_column: string
  label_column: string | null
  alias_columns: string[]
  alias_separator: string
  key_namespace: string
  reference_only: boolean
  attributes: AttributeMapping[]
}

export interface RelationshipMapping {
  subject: string
  object: string
  predicate_id: string | null
  predicate_column: string | null
}

export interface MappingSpec {
  entities: EntityMapping[]
  relationships: RelationshipMapping[]
}

export interface MappingIssue {
  severity: 'error' | 'warning'
  code: string
  message: string
  path: string
}

export interface SourceMapping {
  id: string
  project_id: string
  document_id: string
  document_name: string
  ontology_id: string
  ontology_version_id: string | null
  ontology_version: string | null
  name: string
  description: string
  spec: MappingSpec
  updated_by: string
  created_at: string
  updated_at: string
  issues: MappingIssue[]
}

export interface MappingSuggestion {
  spec: MappingSpec | null
  notes: string[]
  issues: MappingIssue[]
}

export type BuildStatus = 'configured' | 'queued' | 'running' | 'completed' | 'failed'
export type StageStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
export type FactStatus = 'accepted' | 'rejected' | 'quarantined'
export type FactKind = 'type' | 'relationship' | 'attribute'

export interface BuildSettings {
  max_chunks: number
  batch_chars: number
  extract_attributes: boolean
  instructions: string
  /** Validation policy id (Phase 4); builds before Phase 4 report the default. */
  validation_policy?: string
  /** Registered configurations (Settings); null = the project's default. */
  llm_config_id?: string | null
  graph_connection_id?: string | null
}

export interface ValidationPolicy {
  id: string
  name: string
  description: string
  signature: 'reject' | 'shacl' | 'infer_and_flag'
  use_signature_shapes: boolean
  entailment: boolean
  shacl: Record<string, string>
  default: boolean
}

export interface BuildStage {
  key: string
  label: string
  status: StageStatus
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  summary: string
  counts: Record<string, number | string>
}

export interface ReadinessIssue {
  severity: 'error' | 'warning'
  code: string
  message: string
  details: Record<string, unknown>
}

export interface BuildSource {
  id: string
  filename: string
  media_type: string
  kind: 'table' | 'text'
  available: boolean
  mapping_id: string | null
  mapping_name: string | null
}

export interface BuildStats {
  sources?: { structured: number; records: number; documents: number; chunks_total: number; chunks_analyzed: number }
  extraction?: { batches: number; batches_completed: number; batches_failed: number; prompt_tokens: number; completion_tokens: number }
  resolution?: Record<string, number>
  facts?: { by_status: Partial<Record<FactStatus, number>>; by_evidence: Record<string, number>; conflicts: number }
  graph?: { nodes: number; edges: number; store: string; graph_id: string }
  gaps?: number
}

export interface BuildSummary {
  id: string
  project_id: string
  number: number
  name: string
  status: BuildStatus
  ontology_id: string
  ontology_name: string
  ontology_version_id: string
  ontology_version: string
  parent_build_id: string | null
  current_stage: string | null
  stages_completed: number
  stage_count: number
  stats: BuildStats
  graph_store: string | null
  provider: string | null
  model: string | null
  requested_by: string
  error: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
}

export interface BuildDetail extends BuildSummary {
  sources: BuildSource[]
  mapping_ids: string[]
  settings: BuildSettings
  stages: BuildStage[]
  readiness: { ready: boolean; issues: ReadinessIssue[] } | null
  prompt_version: string | null
  gap_count: number
}

export interface BuildCreate {
  name?: string | null
  ontology_version_id: string
  source_document_ids: string[]
  mapping_ids: string[]
  settings: BuildSettings
  requested_by: string
  start?: boolean
}

export interface BuildLog {
  id: number
  stage: string
  level: 'info' | 'warning' | 'error'
  message: string
  details: Record<string, unknown>
  created_at: string
}

export interface Check {
  code: string
  passed: boolean
  message: string
}

export interface FactSummary {
  id: string
  sequence: number
  kind: FactKind
  origin: 'structured' | 'llm'
  status: FactStatus
  subject_entity_id: string | null
  subject_label: string
  subject_class_id: string | null
  subject_class_label: string | null
  predicate_id: string | null
  predicate_ref: string
  predicate_label: string
  object_entity_id: string | null
  object_label: string
  object_class_id: string | null
  object_class_label: string | null
  value: string | null
  datatype: string | null
  structural_passed: boolean
  evidence_status: 'supported' | 'weak' | 'unlocated' | 'missing'
  resolution_passed: boolean
  reasons: string[]
  document_ids: string[]
  source_label: string
  graph_element_id: string | null
  /** Most severe SHACL result; null for builds evaluated before Phase 4. */
  shacl_status: 'conforms' | 'Violation' | 'Warning' | 'Info' | null
  policy_id: string | null
}

export type LaneOutcome = 'reject' | 'quarantine' | 'warn' | 'info'

export interface ShaclResultRead {
  focus: string
  path: string | null
  value: string | null
  severity: 'Violation' | 'Warning' | 'Info'
  component: string
  source_shape: string
  shape_label: string | null
  shape_origin: 'generated' | 'authored' | 'preserved'
  shape_role: 'constraint' | 'signature'
  message: string
  outcome?: LaneOutcome
}

export interface FactLanes {
  policy: { id: string; name: string; relaxed_checks: Check[] }
  shacl: { conforms: boolean; results: ShaclResultRead[] }
  entailment: { ran: boolean; passed: boolean; checks: Check[]; inferred_types: string[] }
}

export interface FactSourceRef {
  kind: 'record' | 'text'
  document_id: string
  document_name: string
  mapping_name?: string
  row_number?: number
  record?: Record<string, string>
  raw?: string
  chunk_id?: string
  chunk_index?: number
  page?: number
  quote?: string
  llm_quote?: string
  context?: string
  located?: boolean
}

export interface SourceExcerpt {
  document_id: string
  document_name: string
  available: boolean
  page: number | null
  chunk_index: number | null
  text: string | null
  row_number: number | null
  record: Record<string, string> | null
  columns: string[] | null
}

export interface FactDetail extends FactSummary {
  structural: { passed: boolean; checks: Check[] }
  evidence: { status: string; checks: Check[] }
  resolution: { passed: boolean; checks: Check[] }
  sources: FactSourceRef[]
  excerpts: SourceExcerpt[]
  lanes: FactLanes | null
  subject_vertex_id: string | null
  object_vertex_id: string | null
  build_id: string
  build_number: number
  ontology_version: string
  ontology_version_id: string
}

export interface FactPage {
  items: FactSummary[]
  total: number
  status_counts: Partial<Record<FactStatus, number>>
  kind_counts: Partial<Record<FactKind, number>>
}

export interface EntitySummary {
  id: string
  vertex_id: string
  class_id: string | null
  class_label: string
  label: string
  identifier: string | null
  resolution_method: string
  ambiguous: boolean
  has_master_record: boolean
  mention_count: number
  status: string
}

export interface EntityDetail extends EntitySummary {
  aliases: string[]
  candidates: { vertex_id: string; label: string; identifier: string | null }[]
  notes: string[]
  type_fact_id: string | null
  mentions: {
    id: string
    origin: string
    class_ref: string
    identifier: string | null
    label: string | null
    reference_only: boolean
    resolution_method: string
    document_id: string | null
    source: FactSourceRef
  }[]
}

export interface GraphNode {
  id: string
  label: string
  name: string
  class_id: string
  class_label: string
  identifier: string | null
  entity_id: string | null
  properties: { key: string; label: string; property_id: string | null; values: unknown[] }[]
  fact_count: number
  source_ids: string[]
}

export interface GraphEdge {
  id: string
  label: string
  predicate_id: string
  predicate_label: string
  source: string
  target: string
  fact_count: number
  source_ids: string[]
}

export interface FacetCount {
  id: string
  label: string
  count: number
}

export interface GraphData {
  build_id: string
  build_number: number
  ontology_version: string
  graph_store: string | null
  nodes: GraphNode[]
  edges: GraphEdge[]
  truncated: boolean
  total_nodes: number
  total_edges: number
  classes: FacetCount[]
  predicates: FacetCount[]
  sources: FacetCount[]
  /** Set when the graph was read back from a deployment target. */
  deployment_id?: string | null
  read_warnings?: string[]
}

export interface GraphElementDetail {
  kind: 'node' | 'edge'
  node: GraphNode | null
  edge: GraphEdge | null
  subject: GraphNode | null
  object: GraphNode | null
  relationships: GraphEdge[]
  neighbours: GraphNode[]
  facts: FactDetail[]
  build_id: string
  build_number: number
  ontology_version: string
  ontology_version_id: string
  project_id: string
  deployment_id?: string | null
}

// ---------------------------------------------------------------------------------- graph deployments (Phase 4.4)

export interface CapabilityProfile {
  id: string
  version: number
  target_kind: string
  label: string
  data_model: 'rdf' | 'property-graph'
  query_languages: string[]
  multi_typing: string
  named_graphs: boolean
  language_tags: boolean
  typed_literals: boolean
  multi_valued_properties: boolean
  statement_metadata: string
  stores_ontology: boolean
  reasoning: string
  native_shacl: boolean
  verified: boolean
  notes: string[]
  adapter_available: boolean
}

export interface MappingProfile {
  id: string
  data_model: 'rdf' | 'property-graph'
  label: string
  description: string
  include_ontology: boolean
  include_provenance: boolean
}

export interface GraphCapabilities {
  profiles: CapabilityProfile[]
  mapping_profiles: MappingProfile[]
}

export type CompatibilityOutcome = 'native' | 'transformed' | 'partial' | 'unsupported' | 'semantic_loss'

export interface CompatibilityRow {
  feature: string
  scope: 'data' | 'ontology'
  outcome: CompatibilityOutcome
  detail: string
  recommendation: string
  affected: number
}

export interface CompatibilityReport {
  target_kind: string
  capability_profile: string
  capability_profile_verified: boolean
  mapping_profile: string
  data_model: string
  rows: CompatibilityRow[]
  counts: Partial<Record<CompatibilityOutcome, number>>
  has_semantic_loss: boolean
  summary: string
  data_features: Record<string, number>
}

export interface CompatibilityRead {
  build_id: string
  target_id: string | null
  target_name: string
  target_kind: string
  adapter_available: boolean
  report: CompatibilityReport
}

export type DeploymentStatus = 'running' | 'completed' | 'failed' | 'superseded'

export interface Deployment {
  id: string
  build_id: string
  build_number: number
  project_id: string
  target_id: string
  target_name: string
  target_kind: string
  data_model: string
  mapping_profile: string
  capability_profile: string
  data_namespace: string | null
  graphs: Record<string, string>
  compatibility: CompatibilityReport | null
  acknowledged_loss_by: string | null
  status: DeploymentStatus
  stats: {
    vertices?: number
    edges?: number
    triples?: number
    duration_ms?: number
    expected?: Record<string, number>
    verified?: Record<string, number>
  }
  error: string | null
  origin: 'build' | 'manual' | 'legacy'
  requested_by: string
  created_at: string
  completed_at: string | null
  explorable: boolean
  queryable: boolean
}

export interface DeploymentCreate {
  target_id: string
  mapping_profile?: string | null
  acknowledge_semantic_loss: boolean
  requested_by: string
}

export interface SparqlTerm {
  type: 'uri' | 'literal' | 'bnode' | 'triple'
  value: string
  datatype?: string | null
  lang?: string | null
}

export interface SparqlResult {
  form: 'select' | 'ask' | 'construct' | 'describe'
  variables: string[]
  rows: Record<string, SparqlTerm | null>[]
  boolean: boolean | null
  total: number
  truncated: boolean
  elapsed_ms: number
  target: string
  default_graph: string
}

export interface Metric {
  key: string
  label: string
  value: number
  unit: 'count' | 'ratio'
  numerator: number | null
  denominator: number | null
  definition: string
}

export interface Evaluation {
  build_id: string
  generated_at: string
  ontology_version: string
  disclaimer: string
  sections: { key: string; title: string; metrics: Metric[] }[]
  status_counts: Partial<Record<FactStatus, number>>
  kind_status_counts: Record<string, Partial<Record<FactStatus, number>>>
  failure_reasons: { code: string; label: string; count: number }[]
}

export type GapType = 'unknown_class' | 'unknown_relationship' | 'unknown_attribute' | 'unmapped_field'

export interface OntologyGap {
  id: string
  build_id: string
  gap_type: GapType
  term: string
  label: string
  description: string
  suggestion: {
    domain_ref?: string | null
    domain_id?: string | null
    domain_label?: string | null
    range_ref?: string | null
    range_id?: string | null
    range_label?: string | null
    datatype?: string | null
    column?: string | null
    sample_values?: string[]
    definition?: string
  }
  occurrences: number
  origins: string[]
  evidence: FactSourceRef[]
  fact_ids: string[]
  status: 'open' | 'proposed'
  proposals: { id: string; title: string; status: ProposalStatus; proposal_type: ProposalType }[]
}

export interface GapProposalResult {
  proposals: ProposalSummary[]
  included_gap_ids: string[]
  discarded: { term: string; reason: string }[]
}

export interface ElementDiff {
  added: number
  removed: number
  unchanged: number
  added_items: { id: string; label: string }[]
  removed_items: { id: string; label: string }[]
}

export interface BuildComparison {
  base: BuildSummary
  target: BuildSummary
  nodes: ElementDiff
  edges: ElementDiff
  metrics: { key: string; label: string; unit: string; base: number | null; target: number | null }[]
}

// ------------------------------------------------------------------ semantics (Phase 4)

export type RdfFormat = 'turtle' | 'rdfxml' | 'jsonld' | 'ntriples'

export interface ExtensionAxiom {
  id: string
  scope: 'ontology' | 'shapes'
  kind: string
  summary: string
  ntriples: string
  anchor_ids: string[]
}

export interface ExtensionAxiomRead extends ExtensionAxiom {
  missing_anchor_ids: string[]
  orphaned: boolean
  import_id: string | null
  created_at: string
}

export interface ImportReport {
  rdf_format: RdfFormat
  source_triples: number
  consumed_triples: number
  preserved_triples: number
  superseded_triples: number
  added_triples: number
  classes: number
  object_properties: number
  datatype_properties: number
  preserved_axioms: number
  preserved_by_kind: Record<string, number>
  superseded: string[]
  added: string[]
  warnings: string[]
  lossless: boolean
}

export interface OntologyImport {
  id: string
  project_id: string
  ontology_id: string
  filename: string
  rdf_format: RdfFormat
  sha256: string
  imported_by: string
  created_at: string
  report: ImportReport
}

export interface ImportResponse {
  ontology: Ontology
  import_record: OntologyImport
}

export interface Entailment {
  category: string
  subject: string
  predicate: string
  object: string
  display: string
}

export interface EntailmentReport {
  engine: string
  informational: boolean
  asserted_triples: number
  inferred_triples: number
  entailments: Entailment[]
  by_category: Record<string, number>
  inconsistencies: string[]
  truncated: boolean
  duration_ms: number
}

// ------------------------------------------------------------------ SHACL shapes (Phase 4.2)

export type ShapeSeverity = 'Violation' | 'Warning' | 'Info'
export type NodeKind = 'IRI' | 'Literal' | 'BlankNode' | 'BlankNodeOrIRI' | 'BlankNodeOrLiteral' | 'IRIOrLiteral'

export interface PropertyConstraint {
  id?: string
  path_id: string
  min_count?: number | null
  max_count?: number | null
  datatype?: XsdDatatype | null
  class_id?: string | null
  node_kind?: NodeKind | null
  allowed_values?: string[]
  pattern?: string | null
  min_length?: number | null
  max_length?: number | null
  min_inclusive?: string | null
  max_inclusive?: string | null
  severity?: ShapeSeverity | null
  message?: string
}

export interface NodeShape {
  id: string
  target_class_id: string
  label: string
  description: string
  severity: ShapeSeverity
  message: string
  deactivated: boolean
  properties: PropertyConstraint[]
}

export type NodeShapeInput = Omit<NodeShape, 'id'>

export interface GeneratedConstraint {
  iri: string
  property_id: string
  property_label: string
  kind: 'attribute' | 'relationship'
  datatype: string | null
  min_count: number | null
  max_count: number | null
  class_id: string | null
}

export interface ShapesOverview {
  ontology_id: string
  draft_revision: number
  authored: NodeShape[]
  generated: { iri: string; target_class_id: string; label: string; constraints: GeneratedConstraint[] }[]
  signatures: { iri: string; property_id: string; side: 'domain' | 'range'; class_id: string; label: string }[]
  preserved: { axiom_id: string; kind: string; summary: string; ntriples: string; anchor_ids: string[]; orphaned: boolean }[]
  check: { well_formed: boolean; message: string }
  triple_count: number
}

export interface ShaclValidationReport {
  conforms: boolean
  data_triples: number
  shapes_used: number
  duration_ms: number
  by_severity: Record<string, number>
  results: ShaclResultRead[]
}

// ------------------------------------------------------------------ Settings (Phase 4)

export const ENV_DEFAULT_LLM = 'env-default'
export const LOCAL_SQL_GRAPH = 'local-sql'

export interface ConnectionTest {
  ok: boolean
  message: string
  latency_ms: number
  tested_at: string | null
  details: Record<string, unknown>
}

export interface LlmConfig {
  id: string
  name: string
  builtin: boolean
  provider: 'openai' | 'anthropic' | 'azure-foundry' | 'ollama' | 'openai-compatible'
  base_url: string | null
  model: string | null
  api_key_env: string | null
  api_key_present: boolean | null
  provider_config: Record<string, unknown>
  structured_output: string
  temperature: number
  timeout_seconds: number
  max_output_tokens: number
  description: string
  configured: boolean
  enabled: boolean
  last_test: ConnectionTest | null
  used_by_projects: string[]
  updated_by: string
  updated_at: string | null
}

export interface LlmConfigInput {
  name: string
  provider: LlmConfig['provider']
  base_url?: string | null
  model: string
  api_key_env?: string | null
  provider_config: Record<string, unknown>
  structured_output: 'json_schema' | 'json_object' | 'prompt'
  temperature: number
  timeout_seconds: number
  max_output_tokens: number
  description: string
}

export interface GraphKindField {
  key: string
  label: string
  required: boolean
  secret: boolean
  placeholder: string
}

export interface GraphKind {
  id: string
  label: string
  model: 'rdf' | 'property-graph'
  builtin: boolean
  registrable: boolean
  available: boolean
  description: string
  unavailable_reason: string
  fields: GraphKindField[]
}

export interface GraphConnection {
  id: string
  name: string
  builtin: boolean
  kind: string
  kind_label: string
  model: 'rdf' | 'property-graph'
  config: Record<string, string>
  secret_env: string | null
  secret_present: boolean | null
  description: string
  last_test: ConnectionTest | null
  used_by_projects: string[]
  updated_by: string
  updated_at: string | null
}

export interface GraphConnectionInput {
  name: string
  kind: string
  config: Record<string, string>
  secret_env?: string | null
  description: string
}

export interface ProjectDefaults {
  project_id: string
  default_llm_config_id: string
  default_discovery_llm_config_id: string
  default_kg_llm_config_id: string
  default_graph_connection_id: string
  data_namespace: string | null
  effective_llm: LlmConfig
  effective_discovery_llm: LlmConfig
  effective_kg_llm: LlmConfig
  effective_graph: GraphConnection
}

export interface ProjectDefaultsUpdate {
  default_llm_config_id?: string | null
  default_discovery_llm_config_id?: string | null
  default_kg_llm_config_id?: string | null
  default_graph_connection_id?: string | null
  data_namespace?: string | null
}

// ---------------------------------------------------------------------------------- project lifecycle (Phase 4)

export type LifecycleStageKey =
  | 'sources'
  | 'discovery'
  | 'review'
  | 'validation'
  | 'publication'
  | 'mapping'
  | 'kg_build'
  | 'deployment'
  | 'evaluation'

export type LifecycleStatus = 'completed' | 'reused' | 'in_progress' | 'pending' | 'blocked' | 'outdated'

export interface LifecycleStageDefinition {
  key: LifecycleStageKey
  label: string
  group: 'governance' | 'knowledge-graph'
  description: string
  optional: boolean
}

export interface LifecycleStage {
  key: LifecycleStageKey
  label: string
  status: LifecycleStatus
  summary: string
  details: string[]
  updated_at: string | null
  reused: { from_iteration: number; summary: string; refs: Record<string, unknown> } | null
  link: { area: 'ontology' | 'knowledge-graph'; tab: string; build_id: string | null }
}

export interface IterationSummary {
  id: string
  number: number
  name: string
  goal: string
  start_stage: LifecycleStageKey
  status: 'active' | 'closed'
  ontology_id: string | null
  base_iteration_number: number | null
  created_by: string
  started_at: string
  closed_at: string | null
  counts: Partial<Record<LifecycleStatus, number>>
}

export interface IterationDetail extends IterationSummary {
  frozen: boolean
  stages: LifecycleStage[]
}

export interface IterationStartOption {
  stage: LifecycleStageKey
  allowed: boolean
  reason: string
  reuses: string[]
}

export interface Lifecycle {
  project_id: string
  ontology_id: string | null
  ontology_name: string | null
  stages: LifecycleStageDefinition[]
  iterations: IterationSummary[]
  iteration: IterationDetail
  start_options: IterationStartOption[]
}

export interface IterationCreate {
  start_stage: LifecycleStageKey
  name?: string
  goal?: string
  ontology_id?: string | null
  created_by: string
}
