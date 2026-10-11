import { useQuery } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router'

import { ontologiesApi, projectsApi } from '@/lib/api/endpoints'
import { queryKeys } from '@/lib/query'

const LAST_PROJECT_KEY = 'ols.lastProjectId'

export function rememberProject(projectId: string) {
  try {
    localStorage.setItem(LAST_PROJECT_KEY, projectId)
  } catch {
    /* storage unavailable (private mode) - non-critical */
  }
}

export function lastProjectId(): string | null {
  try {
    return localStorage.getItem(LAST_PROJECT_KEY)
  } catch {
    return null
  }
}

export function useProjects() {
  return useQuery({ queryKey: queryKeys.projects, queryFn: projectsApi.list })
}

export function useProjectOntologies(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.ontologies(projectId ?? ''),
    queryFn: () => ontologiesApi.listForProject(projectId!),
    enabled: Boolean(projectId),
  })
}

/** Current project (from the route) and its active ontology (from ?ontology= or the first one). */
export function useProjectScope() {
  const { projectId } = useParams<{ projectId: string }>()
  const [searchParams] = useSearchParams()
  const projects = useProjects()
  const ontologies = useProjectOntologies(projectId)

  const project = projects.data?.find((p) => p.id === projectId)
  const requestedOntologyId = searchParams.get('ontology')
  const activeOntology =
    ontologies.data?.find((o) => o.id === requestedOntologyId) ?? ontologies.data?.[0] ?? undefined

  return {
    projectId: projectId ?? '',
    project,
    projects,
    ontologies,
    activeOntology,
    projectMissing: projects.isSuccess && !project,
  }
}
