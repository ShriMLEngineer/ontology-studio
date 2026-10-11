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
  llmStatus: ['llm-status'] as const,
  projects: ['projects'] as const,
  ontologies: (projectId: string) => ['projects', projectId, 'ontologies'] as const,
  activity: (projectId: string) => ['projects', projectId, 'activity'] as const,
  sources: (projectId: string) => ['projects', projectId, 'sources'] as const,
  draft: (ontologyId: string) => ['ontologies', ontologyId, 'draft'] as const,
  latestValidation: (ontologyId: string) => ['ontologies', ontologyId, 'validation', 'latest'] as const,
  discoveryRuns: (ontologyId: string) => ['ontologies', ontologyId, 'discovery-runs'] as const,
  proposals: (ontologyId: string) => ['ontologies', ontologyId, 'proposals'] as const,
  proposalStats: (ontologyId: string) => ['ontologies', ontologyId, 'proposals', 'stats'] as const,
  proposal: (proposalId: string) => ['proposals', proposalId] as const,
  versions: (ontologyId: string) => ['ontologies', ontologyId, 'versions'] as const,
  publishPreview: (ontologyId: string) => ['ontologies', ontologyId, 'publish-preview'] as const,
  compare: (ontologyId: string, base: string, target: string) =>
    ['ontologies', ontologyId, 'compare', base, target] as const,
}
