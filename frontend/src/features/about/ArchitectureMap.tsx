import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useStore,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  appHref,
  ARCH_EDGES,
  ARCH_LANES,
  ARCH_NODES,
  TECHNOLOGIES,
  type ArchLane,
  type ArchNode,
} from './content'

const NODE_WIDTH = 236
const LANE_STEP = 352
const LANE_PADDING = 20
const FIRST_ROW_Y = 46
const ROW_STEP = 104
const LANE_HEIGHT = 372
const ACTIVE_COLOR = 'oklch(0.488 0.217 264)'
const LANE_ORDER: ArchLane[] = ['client', 'backend', 'infra']

type ArchNodeData = { arch: ArchNode; selected: boolean; dimmed: boolean }
type LaneNodeData = { title: string }
type FlowNode = Node<ArchNodeData, 'arch'> | Node<LaneNodeData, 'lane'>

function ArchNodeCard({ data }: NodeProps<Node<ArchNodeData, 'arch'>>) {
  const { arch, selected, dimmed } = data
  const Icon = arch.icon
  const handle = '!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-transparent'
  return (
    <div
      className={cn(
        'cursor-pointer rounded-xl border-2 bg-card p-2.5 text-left shadow-sm transition',
        selected ? 'border-primary ring-2 ring-primary/25' : 'hover:border-primary/50 hover:shadow-md',
        dimmed && 'opacity-65',
      )}
      style={{ width: NODE_WIDTH }}
      data-testid={`about-arch-node-${arch.id}`}
    >
      {(['Left', 'Right', 'Top', 'Bottom'] as const).map((side) => (
        <span key={side}>
          <Handle type="target" id={`t-${side}`} position={Position[side]} className={handle} isConnectable={false} />
          <Handle type="source" id={`s-${side}`} position={Position[side]} className={handle} isConnectable={false} />
        </span>
      ))}
      <div className="flex items-center gap-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Icon className="size-4" />
        </span>
        <span className="truncate text-sm font-semibold">{arch.title}</span>
      </div>
      <p className="mt-1.5 truncate text-[11px] leading-snug text-muted-foreground">{arch.subtitle}</p>
    </div>
  )
}

function LaneNode({ data }: NodeProps<Node<LaneNodeData, 'lane'>>) {
  return (
    <div className="h-full w-full rounded-2xl border border-dashed bg-muted/30">
      <span className="absolute top-3 left-4 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{data.title}</span>
    </div>
  )
}

const NODE_TYPES = { arch: ArchNodeCard, lane: LaneNode }

function neighbours(id: string): Set<string> {
  const related = new Set<string>([id])
  for (const edge of ARCH_EDGES) {
    if (edge.source === id) related.add(edge.target)
    if (edge.target === id) related.add(edge.source)
  }
  return related
}

/** Re-fits the diagram when its container is resized (for example when the sidebar collapses). */
function FitOnResize() {
  const { fitView } = useReactFlow()
  const width = useStore((state) => state.width)
  useEffect(() => {
    void fitView({ padding: 0.05, duration: 200 })
  }, [width, fitView])
  return null
}

function ArchitectureFlow({ selected, onSelect }: { selected: string; onSelect: (id: string) => void }) {
  const related = useMemo(() => neighbours(selected), [selected])

  const nodes = useMemo<FlowNode[]>(
    () => [
      ...LANE_ORDER.map(
        (lane, column): FlowNode => ({
          id: `lane-${lane}`,
          type: 'lane',
          position: { x: column * LANE_STEP - LANE_PADDING, y: 0 },
          data: { title: ARCH_LANES[lane].label },
          style: { width: NODE_WIDTH + LANE_PADDING * 2, height: LANE_HEIGHT },
          selectable: false,
          draggable: false,
          focusable: false,
          zIndex: -1,
        }),
      ),
      ...ARCH_NODES.map(
        (arch): FlowNode => ({
          id: arch.id,
          type: 'arch',
          position: { x: LANE_ORDER.indexOf(arch.lane) * LANE_STEP, y: FIRST_ROW_Y + arch.row * ROW_STEP },
          data: { arch, selected: arch.id === selected, dimmed: !related.has(arch.id) },
          draggable: false,
          connectable: false,
          focusable: false,
        }),
      ),
    ],
    [selected, related],
  )

  const edges = useMemo<Edge[]>(
    () =>
      ARCH_EDGES.map((edge): Edge => {
        const active = edge.source === selected || edge.target === selected
        return {
          id: `${edge.source}-${edge.target}`,
          source: edge.source,
          target: edge.target,
          sourceHandle: `s-${edge.from}`,
          targetHandle: `t-${edge.to}`,
          type: 'smoothstep',
          label: edge.label,
          animated: active,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: active ? ACTIVE_COLOR : '#a1a1aa' },
          style: { strokeWidth: active ? 2.2 : 1.3, stroke: active ? ACTIVE_COLOR : '#a1a1aa', opacity: active ? 1 : 0.7 },
          labelStyle: { fontSize: 10, fill: active ? ACTIVE_COLOR : '#71717a', fontWeight: 600 },
          labelBgPadding: [4, 2],
          labelBgBorderRadius: 4,
          selectable: false,
          focusable: false,
        }
      }),
    [selected],
  )

  return (
    <div className="about-map hidden h-[400px] w-full rounded-xl border bg-card md:block" data-testid="about-arch-flow">
      <ReactFlow<FlowNode, Edge>
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.05 }}
        minZoom={0.3}
        maxZoom={1.3}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => node.type === 'arch' && onSelect(node.id)}
      >
        <Background gap={24} size={1} />
        <FitOnResize />
      </ReactFlow>
    </div>
  )
}

function NodeDetail({
  node,
  projectId,
  onTechnology,
}: {
  node: ArchNode
  projectId: string
  onTechnology: (technologyName: string) => void
}) {
  const Icon = node.icon
  return (
    <Card aria-live="polite" data-testid="about-arch-detail" data-node={node.id}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <span className="flex size-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Icon className="size-4" />
          </span>
          {node.title}
          <Badge variant="outline">{ARCH_LANES[node.lane].label}</Badge>
        </CardTitle>
        <CardDescription className="text-sm">{node.description}</CardDescription>
        {node.link && (
          <CardAction>
            <Button variant="outline" size="sm" asChild>
              <Link to={appHref(projectId, node.link)}>
                {node.link.label} <ArrowRight />
              </Link>
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="grid gap-6 md:grid-cols-2">
        <div>
          <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Responsibilities</h4>
          <ul className="mt-2 space-y-1.5 text-sm">
            {node.responsibilities.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary/60" />
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Technologies</h4>
          <p className="mt-1 text-xs text-muted-foreground">Select one to see what it is used for.</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {node.technologies.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => onTechnology(TECHNOLOGIES[id].name)}
                className="rounded-full border bg-background px-2.5 py-1 text-xs font-medium transition outline-none hover:border-primary/50 hover:bg-primary/5 focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {TECHNOLOGIES[id].name}
              </button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/** Clickable system map built with React Flow, with a button row as a keyboard- and touch-friendly alternative. */
export function ArchitectureMap({
  projectId,
  onTechnology,
}: {
  projectId: string
  onTechnology: (technologyName: string) => void
}) {
  const [selectedId, setSelectedId] = useState('governance')
  const selected = ARCH_NODES.find((node) => node.id === selectedId) ?? ARCH_NODES[0]

  return (
    <div className="space-y-4" data-testid="about-architecture">
      <div role="group" aria-label="Select a component" className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-muted-foreground">Component:</span>
        {ARCH_NODES.map((node) => (
          <button
            key={node.id}
            type="button"
            aria-pressed={node.id === selectedId}
            data-testid={`about-arch-pick-${node.id}`}
            onClick={() => setSelectedId(node.id)}
            className={cn(
              'rounded-full border bg-background px-2.5 py-1 text-xs font-medium transition outline-none hover:border-primary/50 focus-visible:ring-3 focus-visible:ring-ring/50',
              node.id === selectedId && 'border-primary bg-primary/10 text-primary',
            )}
          >
            {node.title}
          </button>
        ))}
      </div>
      <ReactFlowProvider>
        <ArchitectureFlow selected={selectedId} onSelect={setSelectedId} />
      </ReactFlowProvider>
      <NodeDetail node={selected} projectId={projectId} onTechnology={onTechnology} />
    </div>
  )
}
