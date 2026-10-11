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

export interface Ontology extends OntologyMetadata {
  id: string
  project_id: string
  draft_revision: number
  stats: OntologyStats
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
