import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import type { ProposalStatus, ProposalType } from '@/lib/api/types'
import { PROPOSAL_TYPE_META, STATUS_META } from './meta'

export function ProposalTypeBadge({ type, className }: { type: ProposalType; className?: string }) {
  const meta = PROPOSAL_TYPE_META[type]
  return (
    <Badge variant="outline" className={cn('uppercase tracking-wide', meta.className, className)}>
      {meta.label}
    </Badge>
  )
}

export function ProposalStatusBadge({ status }: { status: ProposalStatus }) {
  const meta = STATUS_META[status]
  return (
    <Badge variant="outline" className={meta.className}>
      {meta.label}
    </Badge>
  )
}
