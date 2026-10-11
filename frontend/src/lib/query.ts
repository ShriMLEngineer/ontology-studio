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
  version: (ontologyId: string, versionId: string) => ['ontologies', ontologyId, 'versions', versionId] as const,
  kgVersions: (projectId: string) => ['projects', projectId, 'kg', 'versions'] as const,
  kgMappings: (projectId: string) => ['projects', projectId, 'kg', 'mappings'] as const,
  kgBuilds: (projectId: string) => ['projects', projectId, 'kg', 'builds'] as const,
  kgBuild: (buildId: string) => ['kg-builds', buildId] as const,
  kgLogs: (buildId: string) => ['kg-builds', buildId, 'logs'] as const,
  kgFacts: (buildId: string, params: Record<string, string | undefined>) => ['kg-builds', buildId, 'facts', params] as const,
  kgFact: (factId: string) => ['kg-facts', factId] as const,
  kgGraph: (buildId: string, params: Record<string, string[] | undefined>) => ['kg-builds', buildId, 'graph', params] as const,
  kgElement: (buildId: string, elementId: string) => ['kg-builds', buildId, 'element', elementId] as const,
  kgEvaluation: (buildId: string) => ['kg-builds', buildId, 'evaluation'] as const,
  kgGaps: (buildId: string) => ['kg-builds', buildId, 'gaps'] as const,
  kgCompare: (base: string, target: string) => ['kg-compare', base, target] as const,
  sourcePreview: (documentId: string) => ['sources', documentId, 'preview'] as const,
  draftRdf: (ontologyId: string, format: string, revision: number) =>
    ['ontologies', ontologyId, 'rdf', format, revision] as const,
  axioms: (ontologyId: string) => ['ontologies', ontologyId, 'axioms'] as const,
  imports: (ontologyId: string) => ['ontologies', ontologyId, 'imports'] as const,
  entailments: (ontologyId: string, revision: number) => ['ontologies', ontologyId, 'entailments', revision] as const,
}
