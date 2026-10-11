import { BaseEdge, EdgeLabelRenderer, useInternalNode, type EdgeProps } from '@xyflow/react'
import { cn } from 'cn'

import type { OntologyFlowEdge } from './flow'
import { floatingEdge, rectOf, selfLoop } from './geometry'

export function FloatingEdge({ id, source, target, markerEnd, data }: EdgeProps<OntologyFlowEdge>) {
  const sourceNode = useInternalNode(source)
  const targetNode = useInternalNode(target)
  if (!sourceNode || !targetNode || !data) return null
  const sourceRect = rectOf(sourceNode)
  const targetRect = rectOf(targetNode)
  if (!sourceRect || !targetRect) return null

  const geometry =
    source === target ? selfLoop(sourceRect, data.loopIndex) : floatingEdge(sourceRect, targetRect, data.offset)

  return (
    <>
      <BaseEdge id={id} path={geometry.path} markerEnd={markerEnd} interactionWidth={18} />
      {data.kind === 'relation' && (
        <EdgeLabelRenderer>
          <button
            type="button"
            className={cn(
              'nodrag nopan absolute rounded-md border bg-background px-1.5 py-0.5 text-[11px] font-medium shadow-xs transition-colors hover:border-primary hover:text-primary',
              data.isSelected && 'border-primary bg-primary text-primary-foreground hover:text-primary-foreground',
              !data.isSelected && data.severity === 'error' && 'border-red-300 text-red-700',
            )}
            style={{
              transform: `translate(-50%, -50%) translate(${geometry.labelX}px, ${geometry.labelY}px)`,
              pointerEvents: 'all',
            }}
            onClick={(event) => {
              event.stopPropagation()
              data.onSelect()
            }}
          >
            {data.label}
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
