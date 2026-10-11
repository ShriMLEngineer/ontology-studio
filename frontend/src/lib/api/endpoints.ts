import { apiUrl, http } from '@/lib/api/client'
import type {
  ActivityEvent,
  ApplyResult,
  ArtifactFormat,
  BuildComparison,
  BuildCreate,
  BuildDetail,
  BuildLog,
  BuildSummary,
  Decision,
  DiscoveryRun,
  DiscoveryRunCreate,
  DraftSaveRequest,
  DraftSaveResponse,
  EntailmentReport,
  EntityDetail,
  ExtensionAxiomRead,
  Evaluation,
  FactDetail,
  FactPage,
  GapProposalResult,
  GraphData,
  GraphElementDetail,
  GraphNode,
  Health,
  ImportResponse,
  LLMStatus,
  MappingIssue,
  MappingSpec,
  MappingSuggestion,
  NodeShape,
  NodeShapeInput,
  Ontology,
  OntologyDraft,
  OntologyGap,
  OntologyImport,
  Project,
  ProjectCreate,
  ProposalDetail,
  ProposalEvent,
  ProposalStats,
  ProposalSummary,
  ProposalUpdate,
  PublishedVersionOption,
  PublishPreview,
  PublishRequest,
  RdfFormat,
  SchemaDiff,
  ShaclValidationReport,
  ShapesOverview,
  SourceDocument,
  SourceMapping,
  SourcePreview,
  ValidationPolicy,
  ValidationReport,
  VersionBump,
  VersionDetail,
  VersionSummary,
} from '@/lib/api/types'

const enc = encodeURIComponent

export const systemApi = {
  health: () => http.get<Health>('/health'),
  llmStatus: (check = false) => http.get<LLMStatus>(`/llm/status${check ? '?check=true' : ''}`),
}

export const projectsApi = {
  list: () => http.get<Project[]>('/projects'),
  create: (body: ProjectCreate) => http.post<Project>('/projects', body),
  activity: (projectId: string, limit = 15) =>
    http.get<ActivityEvent[]>(`/projects/${enc(projectId)}/activity?limit=${limit}`),
}

export const ontologiesApi = {
  listForProject: (projectId: string) => http.get<Ontology[]>(`/projects/${enc(projectId)}/ontologies`),
  getDraft: (ontologyId: string) => http.get<OntologyDraft>(`/ontologies/${enc(ontologyId)}/draft`),
  saveDraft: (ontologyId: string, body: DraftSaveRequest) =>
    http.put<DraftSaveResponse>(`/ontologies/${enc(ontologyId)}/draft`, body),
}

export const validationApi = {
  run: (ontologyId: string) => http.post<ValidationReport>(`/ontologies/${enc(ontologyId)}/validations`),
  /** Returns null when the ontology has never been validated. */
  latest: async (ontologyId: string): Promise<ValidationReport | null> => {
    const [latest] = await http.get<ValidationReport[]>(`/ontologies/${enc(ontologyId)}/validations?limit=1`)
    return latest ?? null
  },
}

export const sourcesApi = {
  list: (projectId: string) => http.get<SourceDocument[]>(`/projects/${enc(projectId)}/sources`),
  upload: (projectId: string, file: File, uploadedBy: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('uploaded_by', uploadedBy)
    return http.upload<SourceDocument>(`/projects/${enc(projectId)}/sources`, form)
  },
  remove: (documentId: string) => http.delete(`/sources/${enc(documentId)}`),
}

export const discoveryApi = {
  list: (ontologyId: string) => http.get<DiscoveryRun[]>(`/ontologies/${enc(ontologyId)}/discovery-runs`),
  start: (ontologyId: string, body: DiscoveryRunCreate) =>
    http.post<DiscoveryRun>(`/ontologies/${enc(ontologyId)}/discovery-runs`, body),
}

export const governanceApi = {
  list: (ontologyId: string) => http.get<ProposalSummary[]>(`/ontologies/${enc(ontologyId)}/proposals`),
  stats: (ontologyId: string) => http.get<ProposalStats>(`/ontologies/${enc(ontologyId)}/proposals/stats`),
  get: (proposalId: string) => http.get<ProposalDetail>(`/proposals/${enc(proposalId)}`),
  update: (proposalId: string, body: ProposalUpdate) => http.patch<ProposalDetail>(`/proposals/${enc(proposalId)}`, body),
  decide: (proposalId: string, decision: Decision, actor: string, comment: string) =>
    http.post<ProposalDetail>(`/proposals/${enc(proposalId)}/decision`, { decision, actor, comment }),
  comment: (proposalId: string, actor: string, body: string) =>
    http.post<ProposalEvent>(`/proposals/${enc(proposalId)}/comments`, { actor, body }),
  apply: (ontologyId: string, actor: string, proposalIds?: string[]) =>
    http.post<ApplyResult>(`/ontologies/${enc(ontologyId)}/proposals/apply`, {
      actor,
      ...(proposalIds ? { proposal_ids: proposalIds } : {}),
    }),
}

export const registryApi = {
  versions: (ontologyId: string) => http.get<VersionSummary[]>(`/ontologies/${enc(ontologyId)}/versions`),
  get: (ontologyId: string, versionId: string) =>
    http.get<VersionDetail>(`/ontologies/${enc(ontologyId)}/versions/${enc(versionId)}`),
  preview: (ontologyId: string, bump?: VersionBump) =>
    http.get<PublishPreview>(`/ontologies/${enc(ontologyId)}/publish-preview${bump ? `?bump=${bump}` : ''}`),
  publish: (ontologyId: string, body: PublishRequest) =>
    http.post<VersionSummary>(`/ontologies/${enc(ontologyId)}/versions`, body),
  compare: (ontologyId: string, base: string, target: string) =>
    http.get<SchemaDiff>(`/ontologies/${enc(ontologyId)}/compare?base=${enc(base)}&target=${enc(target)}`),
  exportUrl: (ontologyId: string, versionId: string, format: ArtifactFormat) =>
    apiUrl(`/ontologies/${enc(ontologyId)}/versions/${enc(versionId)}/export?format=${format}`),
}

export interface RdfImportOptions {
  rdfFormat?: RdfFormat | ''
  name?: string
  namespace?: string
  prefix?: string
  ontologyId?: string
  importedBy: string
}

export const semanticsApi = {
  draftRdf: (ontologyId: string, format: RdfFormat = 'turtle') =>
    http.text(`/ontologies/${enc(ontologyId)}/rdf?format=${format}`),
  draftRdfUrl: (ontologyId: string, format: RdfFormat) =>
    apiUrl(`/ontologies/${enc(ontologyId)}/rdf?format=${format}&download=true`),
  axioms: (ontologyId: string) => http.get<ExtensionAxiomRead[]>(`/ontologies/${enc(ontologyId)}/axioms`),
  deleteAxiom: (ontologyId: string, axiomId: string, actor: string) =>
    http.delete(`/ontologies/${enc(ontologyId)}/axioms/${enc(axiomId)}?deleted_by=${enc(actor)}`),
  imports: (ontologyId: string) => http.get<OntologyImport[]>(`/ontologies/${enc(ontologyId)}/imports`),
  entailments: (ontologyId: string) => http.get<EntailmentReport>(`/ontologies/${enc(ontologyId)}/entailments`),
  importRdf: (projectId: string, file: File, options: RdfImportOptions) => {
    const form = new FormData()
    form.append('file', file)
    form.append('imported_by', options.importedBy)
    if (options.rdfFormat) form.append('rdf_format', options.rdfFormat)
    if (options.name) form.append('name', options.name)
    if (options.namespace) form.append('namespace', options.namespace)
    if (options.prefix) form.append('prefix', options.prefix)
    if (options.ontologyId) form.append('ontology_id', options.ontologyId)
    return http.upload<ImportResponse>(`/projects/${enc(projectId)}/ontologies/import`, form)
  },
}

function query(params: Record<string, string | string[] | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    for (const item of Array.isArray(value) ? value : [value]) search.append(key, String(item))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const kgApi = {
  policies: () => http.get<ValidationPolicy[]>('/kg/validation-policies'),
  preview: (documentId: string) => http.get<SourcePreview>(`/sources/${enc(documentId)}/preview`),
  versions: (projectId: string) => http.get<PublishedVersionOption[]>(`/projects/${enc(projectId)}/kg/ontology-versions`),
  mappings: (projectId: string) => http.get<SourceMapping[]>(`/projects/${enc(projectId)}/kg/mappings`),
  suggestMapping: (documentId: string, versionId: string) =>
    http.get<MappingSuggestion>(`/sources/${enc(documentId)}/mapping-suggestion${query({ ontology_version_id: versionId })}`),
  validateMapping: (projectId: string, body: { document_id: string; ontology_version_id: string; spec: MappingSpec }) =>
    http.post<{ valid: boolean; issues: MappingIssue[] }>(`/projects/${enc(projectId)}/kg/mappings/validate`, body),
  createMapping: (
    projectId: string,
    body: { document_id: string; ontology_version_id: string; name: string; description?: string; spec: MappingSpec; updated_by: string },
  ) => http.post<SourceMapping>(`/projects/${enc(projectId)}/kg/mappings`, body),
  updateMapping: (
    mappingId: string,
    body: { ontology_version_id?: string; name?: string; description?: string; spec?: MappingSpec; updated_by: string },
  ) => http.put<SourceMapping>(`/kg/mappings/${enc(mappingId)}`, body),
  deleteMapping: (mappingId: string) => http.delete(`/kg/mappings/${enc(mappingId)}`),

  builds: (projectId: string) => http.get<BuildSummary[]>(`/projects/${enc(projectId)}/kg/builds`),
  build: (buildId: string) => http.get<BuildDetail>(`/kg/builds/${enc(buildId)}`),
  createBuild: (projectId: string, body: BuildCreate) => http.post<BuildDetail>(`/projects/${enc(projectId)}/kg/builds`, body),
  updateBuild: (buildId: string, body: Partial<Omit<BuildCreate, 'requested_by' | 'start'>>) =>
    http.patch<BuildDetail>(`/kg/builds/${enc(buildId)}`, body),
  deleteBuild: (buildId: string) => http.delete(`/kg/builds/${enc(buildId)}`),
  startBuild: (buildId: string, requestedBy: string) =>
    http.post<BuildDetail>(`/kg/builds/${enc(buildId)}/start`, { requested_by: requestedBy }),
  rebuild: (buildId: string, versionId: string, requestedBy: string) =>
    http.post<BuildDetail>(`/kg/builds/${enc(buildId)}/rebuild`, { ontology_version_id: versionId, requested_by: requestedBy }),
  logs: (buildId: string, after = 0) => http.get<BuildLog[]>(`/kg/builds/${enc(buildId)}/logs${query({ after })}`),
  compare: (base: string, target: string) => http.get<BuildComparison>(`/kg/compare${query({ base, target })}`),

  facts: (buildId: string, params: { status?: string; kind?: string; source_id?: string; q?: string } = {}) =>
    http.get<FactPage>(`/kg/builds/${enc(buildId)}/facts${query(params)}`),
  fact: (factId: string) => http.get<FactDetail>(`/kg/facts/${enc(factId)}`),
  entity: (entityId: string) => http.get<EntityDetail>(`/kg/entities/${enc(entityId)}`),

  graph: (buildId: string, params: { class_id?: string[]; predicate_id?: string[]; source_id?: string[] } = {}) =>
    http.get<GraphData>(`/kg/builds/${enc(buildId)}/graph${query(params)}`),
  search: (buildId: string, q: string) => http.get<GraphNode[]>(`/kg/builds/${enc(buildId)}/graph/search${query({ q })}`),
  element: (buildId: string, elementId: string) =>
    http.get<GraphElementDetail>(`/kg/builds/${enc(buildId)}/graph/elements/${enc(elementId)}`),

  evaluation: (buildId: string) => http.get<Evaluation>(`/kg/builds/${enc(buildId)}/evaluation`),
  gaps: (buildId: string) => http.get<OntologyGap[]>(`/kg/builds/${enc(buildId)}/gaps`),
  proposeGaps: (buildId: string, gapIds: string[], requestedBy: string, comment: string) =>
    http.post<GapProposalResult>(`/kg/builds/${enc(buildId)}/gaps/proposals`, {
      gap_ids: gapIds,
      requested_by: requestedBy,
      comment,
    }),
}

export const shapesApi = {
  overview: (ontologyId: string) => http.get<ShapesOverview>(`/ontologies/${enc(ontologyId)}/shapes`),
  create: (ontologyId: string, body: NodeShapeInput, actor: string) =>
    http.post<NodeShape>(`/ontologies/${enc(ontologyId)}/shapes?actor=${enc(actor)}`, body),
  update: (ontologyId: string, shapeId: string, body: NodeShapeInput, actor: string) =>
    http.put<NodeShape>(`/ontologies/${enc(ontologyId)}/shapes/${enc(shapeId)}?actor=${enc(actor)}`, body),
  remove: (ontologyId: string, shapeId: string, actor: string) =>
    http.delete(`/ontologies/${enc(ontologyId)}/shapes/${enc(shapeId)}?actor=${enc(actor)}`),
  rdfUrl: (ontologyId: string) => apiUrl(`/ontologies/${enc(ontologyId)}/shapes/rdf?format=turtle&download=true`),
  rdf: (ontologyId: string) => http.text(`/ontologies/${enc(ontologyId)}/shapes/rdf?format=turtle`),
  validate: (ontologyId: string, data: string, includeSignatureShapes: boolean) =>
    http.post<ShaclValidationReport>(`/ontologies/${enc(ontologyId)}/shapes/validate`, {
      data,
      rdf_format: 'turtle',
      include_signature_shapes: includeSignatureShapes,
    }),
  importShapes: (ontologyId: string, file: File, actor: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('imported_by', actor)
    return http.upload<{ preserved: ShapesOverview['preserved']; triples: number }>(
      `/ontologies/${enc(ontologyId)}/shapes/import`,
      form,
    )
  },
}
