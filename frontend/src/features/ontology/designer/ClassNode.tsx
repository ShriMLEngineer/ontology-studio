import { memo } from 'react'
import { Handle, Position, useConnection, type NodeProps } from '@xyflow/react'
import { AlertCircle, AlertTriangle, Box, Flag, Info, Lock } from 'lucide-react'
import { cn } from 'cn'

import type { Severity } from '@/lib/api/types'
import type { ClassFlowNode } from './flow'
import { useDesignerSemantics } from './semanticContext'

const SEVERITY_ICON: Record<Severity, { icon: typeof AlertCircle; className: string; label: string }> = {
  error: { icon: AlertCircle, className: 'text-red-600', label: 'Has validation errors' },
  warning: { icon: AlertTriangle, className: 'text-amber-600', label: 'Has validation warnings' },
  info: { icon: Info, className: 'text-sky-600', label: 'Has validation hints' },
}

function ClassNodeComponent({ data }: NodeProps<ClassFlowNode>) {
  const connection = useConnection()
  const { cls, attributes, prefix, isSelected, severity, selectedAttributeId, onSelectAttribute } = data
  const issue = severity ? SEVERITY_ICON[severity] : null
  const { lockedIds, axiomCounts } = useDesignerSemantics()
  const semantics = cls.semantics ?? {}
  const marks = [
    semantics.equivalent_ids?.length ? { text: '≡', title: `Equivalent to ${semantics.equivalent_ids.length} class(es)` } : null,
    semantics.disjoint_ids?.length ? { text: '⊥', title: `Disjoint with ${semantics.disjoint_ids.length} class(es)` } : null,
    semantics.restrictions?.length ? { text: `∃${semantics.restrictions.length}`, title: `${semantics.restrictions.length} OWL restriction(s)` } : null,
  ].filter((m): m is { text: string; title: string } => m !== null)
  const axioms = axiomCounts.get(cls.id) ?? 0

  return (
    <div
      className={cn(
        'w-[232px] rounded-xl border bg-card text-card-foreground shadow-sm transition-shadow',
        isSelected ? 'border-primary shadow-md ring-3 ring-primary/20' : 'hover:shadow-md',
        !isSelected && severity === 'error' && 'border-red-300',
      )}
      data-testid={`class-node-${cls.local_name}`}
    >
      <div className="flex items-start gap-2 rounded-t-xl border-b bg-primary/[0.04] px-3 py-2">
        <div className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Box className="size-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div
            className={cn('truncate text-sm font-semibold', semantics.deprecated && 'text-muted-foreground line-through')}
            title={semantics.deprecated ? `${cls.label} (deprecated)` : cls.label}
          >
            {cls.label}
          </div>
          <div className="flex items-center gap-1 font-mono text-[10.5px] text-muted-foreground">
            <span className="truncate">
              {prefix}:{cls.local_name}
            </span>
            {lockedIds.has(cls.id) && <Lock className="size-2.5 shrink-0" aria-label="IRI locked (published)" />}
          </div>
          {(marks.length > 0 || axioms > 0) && (
            <div className="mt-0.5 flex flex-wrap gap-1" data-testid="semantic-marks">
              {marks.map((m) => (
                <span key={m.text} className="rounded bg-primary/10 px-1 font-mono text-[10px] text-primary" title={m.title}>
                  {m.text}
                </span>
              ))}
              {axioms > 0 && (
                <span className="inline-flex items-center gap-0.5 rounded bg-violet-100 px-1 text-[10px] text-violet-800" title={`${axioms} preserved axiom(s)`}>
                  <Flag className="size-2.5" />
                  {axioms}
                </span>
              )}
            </div>
          )}
        </div>
        {issue && <issue.icon className={cn('mt-1 size-4 shrink-0', issue.className)} aria-label={issue.label} />}
      </div>

      {attributes.length > 0 ? (
        <ul className="py-1.5">
          {attributes.map((attr) => (
            <li key={attr.id}>
              <button
                type="button"
                className={cn(
                  'nodrag flex w-full items-center justify-between gap-2 px-3 py-0.5 text-left text-xs hover:bg-muted/70',
                  attr.id === selectedAttributeId && 'bg-primary/10',
                )}
                onClick={(event) => {
                  event.stopPropagation()
                  onSelectAttribute(attr.id)
                }}
              >
                <span className="truncate">
                  {attr.label}
                  {attr.required && <span className="ml-0.5 text-red-500">*</span>}
                </span>
                <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">
                  {attr.datatype}
                  {attr.multi_valued && '[]'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-3 py-2 text-xs text-muted-foreground italic">No attributes</p>
      )}

      <Handle
        type="target"
        position={Position.Left}
        isConnectableStart={false}
        className={cn('target-handle', connection.inProgress && 'is-connecting')}
      />
      <Handle
        type="source"
        position={Position.Right}
        className="connect-handle"
        title="Drag onto a class to create a relationship"
      />
    </div>
  )
}

export const ClassNode = memo(ClassNodeComponent)
