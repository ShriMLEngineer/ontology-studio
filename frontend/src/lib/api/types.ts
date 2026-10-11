export type XsdDatatype =
  | 'string'
  | 'integer'
  | 'decimal'
  | 'boolean'
  | 'date'
  | 'dateTime'
  | 'anyURI'

export const XSD_DATATYPES: readonly XsdDatatype[] = [
  'string',
  'integer',
  'decimal',
  'boolean',
  'date',
  'dateTime',
  'anyURI',
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
  created_at: string
  updated_at: string
}

export interface OntologyMetadata {
  name: string
  namespace: string
  prefix: string
  description: string
}

export interface ProjectCreate {
  name: string
  description?: string
  business_domain?: string
  initial_ontology?: OntologyMetadata | null
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
  draft_revision: number
  stats: OntologyStats
  latest_version: PublishedVersionRef | null
  created_at: string
  updated_at: string
}

export interface ClassDefinition {
  id: string
  local_name: string
  label: string
  description: string
  aliases: string[]
  parent_ids: string[]
}

export interface ObjectPropertyDefinition {
  id: string
  local_name: string
  label: string
  description: string
  aliases: string[]
  domain_id: string | null
  range_id: string | null
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

export interface VersionArtifact {
  format: 'json' | 'turtle'
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