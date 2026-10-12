import { useCallback, useState } from 'react'
import { Network, Waypoints } from 'lucide-react'
import { useSearchParams } from 'react-router'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useProjectScope } from '@/features/projects/hooks'
import { ReviewerControl } from '@/features/ontology/governance/ReviewerControl'
import { DeploymentsView } from './deployments/DeploymentsView'
import { EvaluationView } from './evaluation/EvaluationView'
import { GraphExplorerView } from './explorer/GraphExplorerView'
import { FactValidationView } from './facts/FactValidationView'
import { NativeSelect } from './fields'
import { useBuild, useBuilds, useKgVersions } from './hooks'
import { PipelineView } from './pipeline/PipelineView'
import { BuildStatusBadge } from './shared'

const TABS = ['pipeline', 'explorer', 'facts', 'evaluation', 'deployments'] as const
type KgTab = (typeof TABS)[number]

export function KnowledgeGraphStudioPage() {
  const { projectId, project } = useProjectScope()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab') as KgTab | null
  const tab: KgTab = requestedTab && TABS.includes(requestedTab) ? requestedTab : 'pipeline'
  const [creating, setCreating] = useState(false)

  const versions = useKgVersions(projectId)
  const builds = useBuilds(projectId)
  const selectedId = searchParams.get('build') ?? builds.data?.[0]?.id
  const selected = useBuild(selectedId)

  const update = useCallback(
    (changes: Record<string, string | null>) =>
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          for (const [key, value] of Object.entries(changes)) {
            if (value === null) params.delete(key)
            else params.set(key, value)
          }
          return params
        },
        { replace: true },
      ),
    [setSearchParams],
  )
  const selectBuild = useCallback(
    (buildId: string) => {
      setCreating(false)
      update({ build: buildId, deployment: null })
    },
    [update],
  )
  const openTab = useCallback((next: string) => update({ tab: next }), [update])

  if (builds.isPending || versions.isPending) return <LoadingState label="Loading Knowledge Graph Studio…" />
  if (builds.isError) return <ErrorState className="m-6" title="Unable to load builds" error={builds.error} onRetry={() => builds.refetch()} />
  if (versions.isError)
    return <ErrorState className="m-6" title="Unable to load ontology versions" error={versions.error} onRetry={() => versions.refetch()} />

  const build = selected.data
  const completed = build?.status === 'completed' && !creating ? build : undefined
  const needsCompleted = (
    <EmptyState
      className="m-6"
      icon={<Waypoints />}
      title={build && !creating ? `Build #${build.number} has not completed` : 'No completed build selected'}
      description="Graph exploration, fact validation and evaluation use the persisted results of a completed build. Configure and start a build in the Pipeline tab."
    />
  )

  return (
    <Tabs value={tab} onValueChange={openTab} className="flex h-full min-h-0 flex-col gap-0">
      <div className="shrink-0 border-b bg-background px-6 pt-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Network className="size-5 text-primary" />
          <h1 className="text-xl font-semibold tracking-tight">Knowledge Graph Studio</h1>
          {project && <Badge variant="secondary">{project.name}</Badge>}
          {builds.data.length > 0 && (
            <NativeSelect
              aria-label="Selected build"
              className="h-7 w-auto max-w-80 text-xs"
              value={creating ? '' : (selectedId ?? '')}
              onChange={(e) => e.target.value && selectBuild(e.target.value)}
              data-testid="build-selector"
            >
              {creating && <option value="">New build (not saved)</option>}
              {builds.data.map((b) => (
                <option key={b.id} value={b.id}>
                  #{b.number} {b.name} · v{b.ontology_version} · {b.status}
                </option>
              ))}
            </NativeSelect>
          )}
          {build && !creating && (
            <>
              <BuildStatusBadge status={build.status} />
              <Badge variant="outline" className="font-mono" data-testid="build-version">
                {build.ontology_name} v{build.ontology_version}
              </Badge>
            </>
          )}
          <div className="ml-auto">
            <ReviewerControl />
          </div>
        </div>
        <TabsList variant="line" className="mt-3 h-10">
          <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
          <TabsTrigger value="explorer">Graph Explorer</TabsTrigger>
          <TabsTrigger value="facts">
            Fact Validation
            {completed?.stats.facts && (
              <span className="ml-1 rounded-full bg-amber-100 px-1.5 text-[10px] font-semibold text-amber-800">
                {(completed.stats.facts.by_status.quarantined ?? 0) + (completed.stats.facts.by_status.rejected ?? 0)}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="evaluation">Evaluation & Feedback</TabsTrigger>
          <TabsTrigger value="deployments">Deployments</TabsTrigger>
        </TabsList>
      </div>

      <TabsContent value="pipeline" className="min-h-0 flex-1 overflow-y-auto">
        <PipelineView
          projectId={projectId}
          versions={versions.data}
          builds={builds.data}
          selectedId={selectedId}
          creating={creating || builds.data.length === 0}
          onSelect={selectBuild}
          onNew={() => setCreating(true)}
          onOpenTab={openTab}
        />
      </TabsContent>
      <TabsContent value="explorer" className="min-h-0 flex-1">
        {completed ? (
          <GraphExplorerView
            key={`${completed.id}:${searchParams.get('deployment') ?? ''}`}
            build={completed}
            deploymentId={searchParams.get('deployment') ?? undefined}
            onDeploymentChange={(deploymentId) => update({ deployment: deploymentId })}
          />
        ) : (
          needsCompleted
        )}
      </TabsContent>
      <TabsContent value="facts" className="min-h-0 flex-1">
        {completed ? <FactValidationView key={completed.id} build={completed} /> : needsCompleted}
      </TabsContent>
      <TabsContent value="evaluation" className="min-h-0 flex-1 overflow-y-auto">
        {completed ? <EvaluationView key={completed.id} build={completed} projectId={projectId} /> : needsCompleted}
      </TabsContent>
      <TabsContent value="deployments" className="min-h-0 flex-1 overflow-y-auto">
        {completed ? (
          <DeploymentsView
            key={completed.id}
            build={completed}
            onExplore={(deploymentId) => update({ tab: 'explorer', deployment: deploymentId })}
          />
        ) : (
          needsCompleted
        )}
      </TabsContent>
    </Tabs>
  )
}
