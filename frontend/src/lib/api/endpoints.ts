import { apiUrl, http } from '@/lib/api/client'
import type {
  ActivityEvent,
  ApplyResult,
  Decision,
  DiscoveryRun,
  DiscoveryRunCreate,
  DraftSaveRequest,
  DraftSaveResponse,
  Health,
  LLMStatus,
  Ontology,
  OntologyDraft,
  Project,
  ProjectCreate,
  ProposalDetail,
  ProposalEvent,
  ProposalStats,
  ProposalSummary,
  ProposalUpdate,
  PublishPreview,
  PublishRequest,
  SchemaDiff,
  SourceDocument,
  ValidationReport,
  VersionBump,
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
  preview: (ontologyId: string, bump?: VersionBump) =>
    http.get<PublishPreview>(`/ontologies/${enc(ontologyId)}/publish-preview${bump ? `?bump=${bump}` : ''}`),
  publish: (ontologyId: string, body: PublishRequest) =>
    http.post<VersionSummary>(`/ontologies/${enc(ontologyId)}/versions`, body),
  compare: (ontologyId: string, base: string, target: string) =>
    http.get<SchemaDiff>(`/ontologies/${enc(ontologyId)}/compare?base=${enc(base)}&target=${enc(target)}`),
  exportUrl: (ontologyId: string, versionId: string, format: 'turtle' | 'json') =>
    apiUrl(`/ontologies/${enc(ontologyId)}/versions/${enc(versionId)}/export?format=${format}`),
}
