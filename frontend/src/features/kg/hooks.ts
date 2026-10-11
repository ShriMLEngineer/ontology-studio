import { useQuery } from '@tanstack/react-query'

import { kgApi, registryApi, sourcesApi, systemApi } from '@/lib/api/endpoints'
import type { BuildDetail, BuildSummary } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'

const ACTIVE = new Set(['queued', 'running'])

export const isActive = (build: Pick<BuildSummary, 'status'> | undefined | null) => Boolean(build && ACTIVE.has(build.status))

export function useKgVersions(projectId: string) {
  return useQuery({ queryKey: queryKeys.kgVersions(projectId), queryFn: () => kgApi.versions(projectId), enabled: Boolean(projectId) })
}

export function useVersionSnapshot(ontologyId: string | undefined, versionId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.version(ontologyId ?? '', versionId ?? ''),
    queryFn: () => registryApi.get(ontologyId!, versionId!),
    enabled: Boolean(ontologyId && versionId),
    staleTime: Infinity, // published versions are immutable
  })
}

export function useBuilds(projectId: string) {
  return useQuery({
    queryKey: queryKeys.kgBuilds(projectId),
    queryFn: () => kgApi.builds(projectId),
    enabled: Boolean(projectId),
    refetchInterval: (query) => ((query.state.data ?? []).some(isActive) ? 2000 : false),
  })
}

export function useBuild(buildId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.kgBuild(buildId ?? ''),
    queryFn: () => kgApi.build(buildId!),
    enabled: Boolean(buildId),
    refetchInterval: (query) => (isActive(query.state.data as BuildDetail | undefined) ? 1500 : false),
  })
}

export function useMappings(projectId: string) {
  return useQuery({ queryKey: queryKeys.kgMappings(projectId), queryFn: () => kgApi.mappings(projectId), enabled: Boolean(projectId) })
}

export function useSources(projectId: string) {
  return useQuery({ queryKey: queryKeys.sources(projectId), queryFn: () => sourcesApi.list(projectId), enabled: Boolean(projectId) })
}

export function useLlmStatus(projectId?: string, configId: string | null = null) {
  return useQuery({
    queryKey: projectId ? queryKeys.llmStatusFor(projectId, configId) : queryKeys.llmStatus,
    queryFn: () => systemApi.llmStatus(false, projectId ? { projectId, configId } : {}),
    staleTime: 60_000,
  })
}

export function isTabular(mediaType: string): boolean {
  return mediaType === 'text/csv' || mediaType === 'text/tab-separated-values'
}

export function useValidationPolicies() {
  return useQuery({ queryKey: queryKeys.validationPolicies, queryFn: kgApi.policies, staleTime: Infinity })
}

