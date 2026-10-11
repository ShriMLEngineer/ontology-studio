import { memo } from 'react'
import { Handle, Position, useConnection, type NodeProps } from '@xyflow/react'
import { AlertCircle, AlertTriangle, Box, Info } from 'lucide-react'
import { cn } from 'cn'

import type { Severity } from '@/lib/api/types'
import type { ClassFlowNode } from './flow'

const SEVERITY_ICON: Record<Severity, { icon: typeof AlertCircle; className: string; label: string }> = {
  error: { icon: AlertCircle, className: 'text-red-600', label: 'Has validation errors' },
  warning: { icon: AlertTriangle, className: 'text-amber-600', label: 'Has validation warnings' },
  info: { icon: Info, className: 'text-sky-600', label: 'Has validation hints' },
}

function ClassNodeComponent({ data }: NodeProps<ClassFlowNode>) {
  const connection = useConnection()
  const { cls, attributes, prefix, isSelected, severity, selectedAttributeId, onSelectAttribute } = data
  const issue = severity ? SEVERITY_ICON[severity] : null

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
          <div className="truncate text-sm font-semibold" title={cls.label}>
            {cls.label}
          </div>
          <div className="truncate font-mono text-[10.5px] text-muted-foreground">
            {prefix}:{cls.local_name}
          </div>
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
