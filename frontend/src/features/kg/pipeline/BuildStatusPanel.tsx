import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock, GitBranch, Loader2, RefreshCw, ScrollText, Waypoints } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from 'cn'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { errorMessage } from '@/lib/api/client'
import { kgApi } from '@/lib/api/endpoints'
import type { BuildDetail, BuildLog, PublishedVersionOption } from '@/lib/api/types'
import { dateTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import { useReviewerName } from '@/features/ontology/governance/reviewer'
import { NativeSelect } from '../fields'
import { isActive } from '../hooks'
import { duration } from '../meta'
import { BuildStatusBadge, StageIcon, Stat } from '../shared'

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const handle = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(handle)
  }, [active])
  return now
}

function BuildLogs({ build }: { build: BuildDetail }) {
  const active = isActive(build)
  const logs = useQuery({
    queryKey: queryKeys.kgLogs(build.id),
    queryFn: () => kgApi.logs(build.id),
    refetchInterval: active ? 1500 : false,
  })
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (active) endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [logs.data?.length, active])
  const items: BuildLog[] = logs.data ?? []
  return (
    <div className="max-h-64 overflow-y-auto rounded-lg border bg-muted/20 p-2 font-mono text-[11px] leading-relaxed" data-testid="build-logs">
      {items.length === 0 && <p className="text-muted-foreground">No log lines yet.</p>}
      {items.map((line) => (
        <p key={line.id} className={cn(line.level === 'error' && 'text-red-700', line.level === 'warning' && 'text-amber-700')}>
          <span className="text-muted-foreground">{new Date(line.created_at).toLocaleTimeString()} </span>
          <span className="text-muted-foreground">[{line.stage}]</span> {line.message}
        </p>
      ))}
      <div ref={endRef} />
    </div>
  )
}

export function BuildStatusPanel({
  build,
  versions,
  onOpenTab,
  onSelectBuild,
}: {
  build: BuildDetail
  versions: PublishedVersionOption[]
  onOpenTab: (tab: string) => void
  onSelectBuild: (buildId: string) => void
}) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const active = isActive(build)
  const now = useNow(active)
  const sameOntology = versions.filter((v) => v.ontology_id === build.ontology_id)
  const [rebuildVersion, setRebuildVersion] = useState(
    sameOntology.find((v) => v.is_latest)?.version_id ?? build.ontology_version_id,
  )

  const rebuild = useMutation({
    mutationFn: () => kgApi.rebuild(build.id, rebuildVersion, reviewer),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.kgBuilds(build.project_id) })
      queryClient.setQueryData(queryKeys.kgBuild(created.id), created)
      toast.success(`Build #${created.number} configured from #${build.number}`, {
        description: `Uses ${created.ontology_name} v${created.ontology_version}. Review the sources and mappings, then start it.`,
      })
      onSelectBuild(created.id)
    },
    onError: (error) => toast.error('Rebuild failed', { description: errorMessage(error) }),
  })

  const facts = build.stats.facts?.by_status ?? {}
  const resolution = build.stats.resolution ?? {}
  const relationshipStage = build.stages.find((s) => s.key === 'relationship_extraction')
  const elapsed = build.duration_ms ?? (build.started_at ? now - new Date(build.started_at).getTime() : null)
  const current = build.stages.find((s) => s.status === 'running')

  return (
    <Card size="sm" data-testid="build-status">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Waypoints className="size-4" />
          Build #{build.number} · {build.name}
          <BuildStatusBadge status={build.status} />
        </CardTitle>
        <CardDescription className="flex flex-wrap gap-x-3 gap-y-1">
          <span>
            {build.ontology_name} <strong className="font-mono">v{build.ontology_version}</strong>
          </span>
          {build.model && <span>LLM {build.model}</span>}
          {build.started_at && <span>Started {dateTime(build.started_at)}</span>}
          <span className="flex items-center gap-1">
            <Clock className="size-3" /> {duration(elapsed)}
          </span>
          {build.parent_build_id && (
            <span className="flex items-center gap-1">
              <GitBranch className="size-3" /> rebuild
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {build.status === 'configured' && (
          <p className="text-sm text-muted-foreground">This build is configured but has not been started.</p>
        )}
        {build.status !== 'configured' && (
          <p className="text-xs text-muted-foreground" data-testid="stage-progress">
            {build.stages_completed} of {build.stage_count} stages completed
            {current ? ` · current stage: ${current.label}` : ''}
            {current?.counts.batches_total
              ? ` (LLM batch ${Number(current.counts.batches_completed) + 1} of ${current.counts.batches_total})`
              : ''}
          </p>
        )}

        <ol className="space-y-1" aria-label="Pipeline stages">
          {build.stages.map((stage, index) => (
            <li
              key={stage.key}
              className={cn('flex gap-3 rounded-md px-2 py-1.5', stage.status === 'running' && 'bg-sky-50')}
              data-stage={stage.key}
              data-stage-status={stage.status}
            >
              <StageIcon status={stage.status} />
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium">
                  <span className="text-xs text-muted-foreground tabular-nums">{index + 1}.</span>
                  {stage.label}
                  {stage.duration_ms !== null && (
                    <span className="ml-auto text-[11px] font-normal text-muted-foreground tabular-nums">{duration(stage.duration_ms)}</span>
                  )}
                </p>
                {stage.summary && <p className="text-xs text-muted-foreground">{stage.summary}</p>}
              </div>
            </li>
          ))}
        </ol>

        {build.status === 'failed' && build.error && (
          <Alert variant="destructive">
            <AlertTitle>Build failed</AlertTitle>
            <AlertDescription>{build.error}</AlertDescription>
          </Alert>
        )}

        {(build.status === 'completed' || build.stages_completed > 4) && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="build-counts">
            <Stat label="Entity mentions" value={resolution.mentions ?? '—'} />
            <Stat label="Resolved entities" value={resolution.entities ?? '—'} />
            <Stat label="Candidate relationships" value={relationshipStage?.counts.relationship_candidates ?? '—'} />
            <Stat label="Graph nodes / edges" value={build.stats.graph ? `${build.stats.graph.nodes} / ${build.stats.graph.edges}` : '—'} />
            <Stat label="Accepted facts" value={facts.accepted ?? 0} tone="good" testId="count-accepted" />
            <Stat label="Rejected facts" value={facts.rejected ?? 0} tone="bad" testId="count-rejected" />
            <Stat label="Quarantined facts" value={facts.quarantined ?? 0} tone="warn" testId="count-quarantined" />
            <Stat label="Ontology gaps" value={build.gap_count} />
          </div>
        )}

        {build.status === 'completed' && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => onOpenTab('explorer')}>
              Explore graph
            </Button>
            <Button size="sm" variant="outline" onClick={() => onOpenTab('facts')}>
              Review facts
            </Button>
            <Button size="sm" variant="outline" onClick={() => onOpenTab('evaluation')}>
              Evaluation & feedback
            </Button>
          </div>
        )}

        {(build.status === 'completed' || build.status === 'failed') && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2" data-testid="rebuild">
            <RefreshCw className="size-4 text-muted-foreground" />
            <span className="text-xs">Rebuild with</span>
            <NativeSelect
              aria-label="Rebuild version"
              className="h-7 w-auto text-xs"
              value={rebuildVersion}
              onChange={(e) => setRebuildVersion(e.target.value)}
            >
              {sameOntology.map((v) => (
                <option key={v.version_id} value={v.version_id}>
                  v{v.version}
                  {v.is_latest ? ' (latest)' : ''}
                </option>
              ))}
            </NativeSelect>
            <Button size="xs" variant="outline" onClick={() => rebuild.mutate()} disabled={rebuild.isPending || !reviewer}>
              {rebuild.isPending && <Loader2 className="animate-spin" />}
              Configure rebuild
            </Button>
            <span className="text-[11px] text-muted-foreground">The earlier build and its graph are kept unchanged.</span>
          </div>
        )}

        {build.status !== 'configured' && (
          <section className="space-y-2">
            <h3 className="flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              <ScrollText className="size-3.5" /> Execution log
            </h3>
            <BuildLogs build={build} />
          </section>
        )}
      </CardContent>
    </Card>
  )
}
