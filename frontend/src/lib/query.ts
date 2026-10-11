import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/lib/api/client'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
        return failureCount < 2
      },
    },
  },
})

export const queryKeys = {
  health: ['health'] as const,
  projects: ['projects'] as const,
  ontologies: (projectId: string) => ['projects', projectId, 'ontologies'] as const,
  activity: (projectId: string) => ['projects', projectId, 'activity'] as const,
  draft: (ontologyId: string) => ['ontologies', ontologyId, 'draft'] as const,
  latestValidation: (ontologyId: string) => ['ontologies', ontologyId, 'validation', 'latest'] as const,
}
