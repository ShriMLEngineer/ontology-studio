import { useQuery } from '@tanstack/react-query'

import { projectsApi, settingsApi } from '@/lib/api/endpoints'
import { queryKeys } from '@/lib/query'

export function useLlmConfigs() {
  return useQuery({ queryKey: queryKeys.llmConfigs, queryFn: settingsApi.llmConfigs })
}

export function useGraphConnections() {
  return useQuery({ queryKey: queryKeys.graphConnections, queryFn: settingsApi.graphConnections })
}

export function useGraphKinds() {
  return useQuery({ queryKey: queryKeys.graphKinds, queryFn: settingsApi.graphKinds, staleTime: Infinity })
}

export function useProjectDefaults(projectId: string) {
  return useQuery({
    queryKey: queryKeys.projectDefaults(projectId),
    queryFn: () => projectsApi.defaults(projectId),
    enabled: Boolean(projectId),
  })
}
