import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Background,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import {
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  Flag,
  History,
  Loader2,
  OctagonX,
  Play,
  Recycle,
  RefreshCcw,
  TriangleAlert,
} from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { cn } from 'cn'

import { ErrorState, LoadingState } from '@/components/common/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { lifecycleApi } from '@/lib/api/endpoints'
import type { Lifecycle, LifecycleStage, LifecycleStageKey, LifecycleStatus } from '@/lib/api/types'
import { dateTime, relativeTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import { useReviewerName } from '@/features/ontology/governance/reviewer'
import { ReviewerControl } from '@/features/ontology/governance/ReviewerControl'

const STATUS_META: Record<LifecycleStatus, { label: string; className: string; dot: string; icon: typeof CheckCircle2 }> = {
  completed: { label: 'Completed', className: 'border-emerald-300 bg-emerald-50 text-emerald-800', dot: 'bg-emerald-500', icon: CheckCircle2 },
  reused: { label: 'Reused', className: 'border-violet-300 bg-violet-50 text-violet-800', dot: 'bg-violet-500', icon: Recycle },
  in_progress: { label: 'In progress', className: 'border-sky-300 bg-sky-50 text-sky-800', dot: 'bg-sky-500', icon: Loader2 },
  pending: { label: 'Pending', className: 'border-slate-200 bg-white text-slate-600', dot: 'bg-slate-300', icon: CircleDashed },
  blocked: { label: 'Blocked', className: 'border-red-300 bg-red-50 text-red-800', dot: 'bg-red-500', icon: OctagonX },
  outdated: { label: 'Outdated', className: 'border-amber-300 bg-amber-50 text-amber-800', dot: 'bg-amber-500', icon: TriangleAlert },
}
const STATUS_ORDER: LifecycleStatus[] = ['completed', 'reused', 'in_progress', 'pending', 'blocked', 'outdated']

// Snake layout: governance left to right, knowledge graph right to left, feedback back to SME review.
const STEP = 230
const POSITIONS: Record<LifecycleStageKey, { x: number; y: number }> = {
  sources: { x: 0, y: 0 },
  discovery: { x: STEP, y: 0 },
  review: { x: STEP * 2, y: 0 },
  validation: { x: STEP * 3, y: 0 },
  publication: { x: STEP * 4, y: 0 },
  mapping: { x: STEP * 4, y: 200 },
  kg_build: { x: STEP * 3, y: 200 },
  deployment: { x: STEP * 2, y: 200 },
  evaluation: { x: STEP, y: 200 },
}
const NODE_WIDTH = 200

type StageNodeData = { stage: LifecycleStage; optional: boolean; isStart: boolean; selected: boolean }
type LaneNodeData = { title: string }
type FlowNode = Node<StageNodeData, 'stage'> | Node<LaneNodeData, 'lane'>

function StageNode({ data }: NodeProps<Node<StageNodeData, 'stage'>>) {
  const meta = STATUS_META[data.stage.status]
  const Icon = meta.icon
  const handle = '!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-transparent'
  return (
    <div
      className={cn(
        'relative rounded-xl border-2 bg-card p-2.5 text-left shadow-sm transition-shadow',
        meta.className,
        data.selected && 'ring-2 ring-primary ring-offset-2',
      )}
      style={{ width: NODE_WIDTH }}
      data-testid={`lifecycle-stage-${data.stage.key}`}
      data-status={data.stage.status}
    >
      {(['Left', 'Right', 'Top', 'Bottom'] as const).map((side) => (
        <span key={side}>
          <Handle type="target" id={`t-${side}`} position={Position[side]} className={handle} isConnectable={false} />
          <Handle type="source" id={`s-${side}`} position={Position[side]} className={handle} isConnectable={false} />
        </span>
      ))}
      <div className="flex items-center gap-1.5">
        <Icon className={cn('size-4 shrink-0', data.stage.status === 'in_progress' && 'animate-spin')} />
        <span className="truncate text-sm font-semibold text-foreground">{data.stage.label}</span>
        {data.isStart && (
          <span className="ml-auto inline-flex items-center gap-0.5 rounded bg-primary px-1 text-[10px] font-semibold text-primary-foreground" title="This iteration starts here">
            <Flag className="size-2.5" /> start
          </span>
        )}
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[11px] font-medium">
        {meta.label}
        {data.optional && <span className="font-normal text-muted-foreground">· optional</span>}
      </div>
      <p className="mt-1 line-clamp-3 text-[11px] leading-snug text-foreground/75">{data.stage.summary}</p>
    </div>
  )
}

function LaneNode({ data }: NodeProps<Node<LaneNodeData, 'lane'>>) {
  return (
    <div className="h-full w-full rounded-2xl border border-dashed bg-muted/30">
      <span className="absolute -top-2.5 left-4 bg-background px-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        {data.title}
      </span>
    </div>
  )
}

const NODE_TYPES = { stage: StageNode, lane: LaneNode }

function edge(source: LifecycleStageKey, target: LifecycleStageKey, from: string, to: string, extra: Partial<Edge> = {}): Edge {
  return {
    id: `${source}-${target}`,
    source,
    target,
    sourceHandle: `s-${from}`,
    targetHandle: `t-${to}`,
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    style: { strokeWidth: 1.5 },
    selectable: false,
    ...extra,
  }
}

const EDGES: Edge[] = [
  edge('sources', 'discovery', 'Right', 'Left'),
  edge('discovery', 'review', 'Right', 'Left'),
  edge('review', 'validation', 'Right', 'Left'),
  edge('validation', 'publication', 'Right', 'Left'),
  edge('publication', 'mapping', 'Bottom', 'Top', { label: 'published version' }),
  edge('mapping', 'kg_build', 'Left', 'Right'),
  edge('kg_build', 'deployment', 'Left', 'Right'),
  edge('deployment', 'evaluation', 'Left', 'Right'),
  edge('evaluation', 'review', 'Top', 'Bottom', {
    label: 'ontology gaps → proposals',
    animated: true,
    style: { strokeWidth: 1.5, strokeDasharray: '6 4' },
  }),
]

function LifecycleFlow({
  lifecycle,
  selected,
  onSelect,
}: {
  lifecycle: Lifecycle
  selected: LifecycleStageKey | null
  onSelect: (key: LifecycleStageKey) => void
}) {
  const optional = useMemo(() => new Set(lifecycle.stages.filter((s) => s.optional).map((s) => s.key)), [lifecycle.stages])
  const nodes = useMemo<FlowNode[]>(
    () => [
      {
        id: 'lane-governance',
        type: 'lane',
        position: { x: -24, y: -26 },
        data: { title: 'Ontology governance' },
        style: { width: STEP * 4 + NODE_WIDTH + 48, height: 168 },
        selectable: false,
        draggable: false,
        zIndex: -1,
      },
      {
        id: 'lane-kg',
        type: 'lane',
        position: { x: STEP - 24, y: 174 },
        data: { title: 'Knowledge graph' },
        style: { width: STEP * 3 + NODE_WIDTH + 48, height: 168 },
        selectable: false,
        draggable: false,
        zIndex: -1,
      },
      ...lifecycle.iteration.stages.map(
        (stage): FlowNode => ({
          id: stage.key,
          type: 'stage',
          position: POSITIONS[stage.key],
          data: {
            stage,
            optional: optional.has(stage.key),
            isStart: stage.key === lifecycle.iteration.start_stage,
            selected: stage.key === selected,
          },
          draggable: false,
          connectable: false,
        }),
      ),
    ],
    [lifecycle.iteration, optional, selected],
  )
  return (
    <div className="h-[380px] w-full" data-testid="lifecycle-flow">
      <ReactFlow<FlowNode, Edge>
        nodes={nodes}
        edges={EDGES}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.08 }}
        minZoom={0.4}
        maxZoom={1.2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => node.type === 'stage' && onSelect(node.id as LifecycleStageKey)}
      >
        <Background gap={24} size={1} />
      </ReactFlow>
    </div>
  )
}

function stageHref(projectId: string, lifecycle: Lifecycle, stage: LifecycleStage): string {
  if (stage.link.area === 'ontology') {
    const params = new URLSearchParams({ ...(lifecycle.ontology_id ? { ontology: lifecycle.ontology_id } : {}), tab: stage.link.tab })
    return `/projects/${projectId}/ontology?${params.toString()}`
  }
  const params = new URLSearchParams({ tab: stage.link.tab, ...(stage.link.build_id ? { build: stage.link.build_id } : {}) })
  return `/projects/${projectId}/knowledge-graph?${params.toString()}`
}

function StageDetail({ projectId, lifecycle, stage }: { projectId: string; lifecycle: Lifecycle; stage: LifecycleStage }) {
  const meta = STATUS_META[stage.status]
  const definition = lifecycle.stages.find((s) => s.key === stage.key)
  return (
    <div className="rounded-xl border p-4" data-testid="lifecycle-stage-detail" data-stage={stage.key}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">{stage.label}</h3>
        <Badge variant="outline" className={meta.className}>
          {meta.label}
        </Badge>
        {stage.updated_at && <span className="text-xs text-muted-foreground">last activity {relativeTime(stage.updated_at)}</span>}
        {!lifecycle.iteration.frozen && (
          <Button size="xs" variant="outline" className="ml-auto" asChild>
            <Link to={stageHref(projectId, lifecycle, stage)}>
              Open <ArrowRight />
            </Link>
          </Button>
        )}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{definition?.description}</p>
      <p className="mt-2 text-sm" data-testid="lifecycle-stage-summary">
        {stage.summary}
      </p>
      {stage.details.length > 0 && (
        <ul className="mt-2 list-inside list-disc text-xs text-muted-foreground">
          {stage.details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
      {stage.reused && (
        <p className="mt-2 rounded-lg bg-violet-50 px-2 py-1.5 text-xs text-violet-900">
          <Recycle className="mr-1 inline size-3" />
          Output of iteration #{stage.reused.from_iteration}: {stage.reused.summary}
        </p>
      )}
    </div>
  )
}

function StartIterationDialog({
  projectId,
  lifecycle,
  open,
  onOpenChange,
  onStarted,
}: {
  projectId: string
  lifecycle: Lifecycle
  open: boolean
  onOpenChange: (open: boolean) => void
  onStarted: (iterationId: string) => void
}) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const [stage, setStage] = useState<LifecycleStageKey>('sources')
  const [name, setName] = useState('')
  const [goal, setGoal] = useState('')
  const option = lifecycle.start_options.find((o) => o.stage === stage)
  const active = lifecycle.iterations.find((i) => i.status === 'active')
  const start = useMutation({
    mutationFn: () => lifecycleApi.start(projectId, { start_stage: stage, name, goal, created_by: reviewer }),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.lifecycle(projectId), result)
      void queryClient.invalidateQueries({ queryKey: ['projects', projectId] })
      toast.success(`Iteration #${result.iteration.number} started`, {
        description: `Iteration #${active?.number} is closed; its statuses are kept as they were.`,
      })
      onStarted(result.iteration.id)
      onOpenChange(false)
    },
    onError: (error) => toast.error('Cannot start the iteration', { description: errorMessage(error) }),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl" data-testid="iteration-dialog">
        <DialogHeader>
          <DialogTitle>Start a new iteration</DialogTitle>
          <DialogDescription>
            Iteration #{active?.number} will be closed and its stage statuses frozen. Choose where the new iteration starts;
            the latest outputs of the earlier stages are reused.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 md:grid-cols-[1fr_1.2fr]">
          <fieldset className="space-y-1" aria-label="Start stage">
            <legend className="mb-1 text-xs font-medium">Start at</legend>
            {lifecycle.start_options.map((o) => {
              const label = lifecycle.stages.find((s) => s.key === o.stage)?.label ?? o.stage
              return (
                <label
                  key={o.stage}
                  className={cn(
                    'flex cursor-pointer items-start gap-2 rounded-lg border px-2 py-1.5 text-sm',
                    stage === o.stage && 'border-primary bg-primary/5',
                    !o.allowed && 'cursor-not-allowed opacity-50',
                  )}
                  title={o.reason || undefined}
                >
                  <input
                    type="radio"
                    name="start-stage"
                    value={o.stage}
                    checked={stage === o.stage}
                    disabled={!o.allowed}
                    onChange={() => setStage(o.stage)}
                    className="mt-1"
                    aria-label={label}
                  />
                  <span>
                    {label}
                    {!o.allowed && <span className="block text-[11px] text-muted-foreground">{o.reason}</span>}
                  </span>
                </label>
              )
            })}
          </fieldset>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="iteration-name" className="text-xs">
                Name
              </Label>
              <Input
                id="iteration-name"
                placeholder={`Iteration ${(lifecycle.iterations.at(-1)?.number ?? 0) + 1}`}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="iteration-goal" className="text-xs">
                Goal
              </Label>
              <Textarea
                id="iteration-goal"
                className="min-h-16"
                placeholder="What should this iteration achieve?"
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
              />
            </div>
            <div className="rounded-lg bg-muted/40 p-2.5 text-xs" data-testid="iteration-reuses">
              <p className="mb-1 font-medium">Reused from iteration #{active?.number}</p>
              {option && option.reuses.length > 0 ? (
                <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
                  {option.reuses.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">Nothing - the iteration starts from the first stage.</p>
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          {!reviewer && <span className="mr-auto text-xs text-amber-700">Set your reviewer name (Project lifecycle header) first.</span>}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => start.mutate()} disabled={!reviewer || !option?.allowed || start.isPending} data-testid="iteration-start">
            {start.isPending ? <Loader2 className="animate-spin" /> : <Play />} Start iteration
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function LifecycleNavigator({ projectId }: { projectId: string }) {
  const [iterationId, setIterationId] = useState<string | undefined>(undefined)
  const [selected, setSelected] = useState<LifecycleStageKey | null>(null)
  const [starting, setStarting] = useState(false)
  const lifecycle = useQuery({
    queryKey: queryKeys.lifecycle(projectId, iterationId),
    queryFn: () => lifecycleApi.get(projectId, iterationId),
    enabled: Boolean(projectId),
    staleTime: 0,
    placeholderData: (previous) => previous,
    refetchInterval: (query) => (query.state.data?.iteration.stages.some((s) => s.status === 'in_progress') ? 5000 : false),
  })

  if (lifecycle.isPending) return <LoadingState label="Loading the project lifecycle…" className="min-h-40" />
  if (lifecycle.isError) return <ErrorState title="Unable to load the lifecycle" error={lifecycle.error} onRetry={() => lifecycle.refetch()} />
  const data = lifecycle.data
  const iteration = data.iteration
  const stage = iteration.stages.find((s) => s.key === selected) ?? null

  return (
    <Card data-testid="lifecycle-navigator">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <RefreshCcw className="size-4" /> Project lifecycle
        </CardTitle>
        <CardDescription>
          Where every iteration stands, derived from the project's records{data.ontology_name ? ` (ontology ${data.ontology_name})` : ''}. Click a
          stage for details.
        </CardDescription>
        <CardAction className="flex items-center gap-2">
          <ReviewerControl />
          <Button size="sm" onClick={() => setStarting(true)} data-testid="new-iteration">
            <Play /> New iteration
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Iterations">
          {data.iterations.map((it) => (
            <button
              key={it.id}
              type="button"
              role="tab"
              aria-selected={it.id === iteration.id}
              onClick={() => {
                setIterationId(it.status === 'active' ? undefined : it.id)
                setSelected(null)
              }}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors',
                it.id === iteration.id ? 'border-primary bg-primary/10 text-primary' : 'hover:bg-muted',
              )}
              data-testid={`iteration-${it.number}`}
            >
              {it.status === 'closed' ? <History className="size-3" /> : <span className="size-2 rounded-full bg-emerald-500" />}
              #{it.number} {it.name}
              <span className="text-muted-foreground">· {it.status}</span>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="iteration-meta">
          <span>
            Started {dateTime(iteration.started_at)}
            {iteration.created_by && ` by ${iteration.created_by}`} at <strong className="text-foreground">{data.stages.find((s) => s.key === iteration.start_stage)?.label}</strong>
            {iteration.base_iteration_number && ` · continues iteration #${iteration.base_iteration_number}`}
          </span>
          {iteration.goal && <span>Goal: {iteration.goal}</span>}
          {iteration.frozen && (
            <span className="text-amber-700" data-testid="iteration-frozen">
              Closed {iteration.closed_at && dateTime(iteration.closed_at)}: statuses as they were when the iteration ended.
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5" aria-label="Status legend">
          {STATUS_ORDER.map((status) => (
            <span key={status} className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]', STATUS_META[status].className)}>
              <span className={cn('size-1.5 rounded-full', STATUS_META[status].dot)} />
              {STATUS_META[status].label}
              <span className="tabular-nums">{iteration.counts[status] ?? 0}</span>
            </span>
          ))}
        </div>

        <ReactFlowProvider>
          <LifecycleFlow lifecycle={data} selected={selected} onSelect={setSelected} />
        </ReactFlowProvider>

        {stage ? (
          <StageDetail projectId={projectId} lifecycle={data} stage={stage} />
        ) : (
          <p className="text-xs text-muted-foreground">Select a stage to see its evidence and open the place where the work happens.</p>
        )}
      </CardContent>
      {starting && (
        <StartIterationDialog
          projectId={projectId}
          lifecycle={data}
          open={starting}
          onOpenChange={setStarting}
          onStarted={() => {
            setIterationId(undefined)
            setSelected(null)
          }}
        />
      )}
    </Card>
  )
}
