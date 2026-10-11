import { http } from '@/lib/api/client'
import type {
  ActivityEvent,
  DraftSaveRequest,
  DraftSaveResponse,
  Health,
  Ontology,
  OntologyDraft,
  Project,
  ProjectCreate,
  ValidationReport,
} from '@/lib/api/types'

const enc = encodeURIComponent

export const systemApi = {
  health: () => http.get<Health>('/health'),
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
