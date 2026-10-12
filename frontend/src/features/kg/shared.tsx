import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Circle, CircleSlash, Loader2, ShieldAlert, ShieldCheck, XCircle } from 'lucide-react'
import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import type { BuildStatus, Check, FactStatus, StageStatus } from '@/lib/api/types'
import { EVIDENCE_LABEL, FACT_STATUS_META } from './meta'

export function FactStatusBadge({ status, className }: { status: FactStatus; className?: string }) {
  const meta = FACT_STATUS_META[status]
  return (
    <Badge variant="outline" className={cn(meta.className, className)} data-status={status} title={meta.description}>
      {meta.label}
    </Badge>
  )
}

const BUILD_STATUS: Record<BuildStatus, { label: string; className: string }> = {
  configured: { label: 'Configured', className: 'border-slate-200 bg-slate-50 text-slate-700' },
  queued: { label: 'Queued', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  running: { label: 'Running', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  completed: { label: 'Completed', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  failed: { label: 'Failed', className: 'border-red-200 bg-red-50 text-red-800' },
}

export function BuildStatusBadge({ status }: { status: BuildStatus }) {
  const meta = BUILD_STATUS[status]
  return (
    <Badge variant="outline" className={meta.className} data-build-status={status}>
      {(status === 'running' || status === 'queued') && <Loader2 className="animate-spin" />}
      {meta.label}
    </Badge>
  )
}

export function StageIcon({ status }: { status: StageStatus }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="size-4 text-emerald-600" />
    case 'running':
      return <Loader2 className="size-4 animate-spin text-sky-600" />
    case 'failed':
      return <XCircle className="size-4 text-red-600" />
    case 'skipped':
      return <CircleSlash className="size-4 text-muted-foreground" />
    default:
      return <Circle className="size-4 text-muted-foreground/50" />
  }
}

export function EvidenceBadge({ status }: { status: string }) {
  const supported = status === 'supported'
  return (
    <Badge
      variant="outline"
      className={
        supported
          ? 'border-emerald-200 text-emerald-700'
          : status === 'missing'
            ? 'border-red-200 text-red-700'
            : 'border-amber-200 text-amber-700'
      }
    >
      {supported ? <ShieldCheck /> : <ShieldAlert />}
      {EVIDENCE_LABEL[status] ?? status}
    </Badge>
  )
}

export function CheckList({ checks, empty = 'No checks recorded.' }: { checks: Check[]; empty?: string }) {
  if (checks.length === 0) return <p className="text-xs text-muted-foreground">{empty}</p>
  return (
    <ul className="space-y-1.5">
      {checks.map((check, index) => (
        <li key={`${check.code}-${index}`} className="flex gap-2 text-xs" data-check={check.code} data-passed={check.passed}>
          {check.passed ? (
            <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />
          ) : (
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-red-600" />
          )}
          <span className={check.passed ? 'text-muted-foreground' : 'text-foreground'}>{check.message}</span>
        </li>
      ))}
    </ul>
  )
}

/** Shows ``text`` with the first occurrence of ``quote`` highlighted (whitespace-insensitive). */
export function Highlighted({ text, quote }: { text: string; quote?: string | null }) {
  if (!quote) return <>{text}</>
  const pattern = quote
    .trim()
    .split(/\s+/)
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('\\s+')
  const match = new RegExp(pattern, 'i').exec(text)
  if (!match) return <>{text}</>
  return (
    <>
      {text.slice(0, match.index)}
      <mark className="rounded bg-amber-200/70 px-0.5 text-foreground">{match[0]}</mark>
      {text.slice(match.index + match[0].length)}
    </>
  )
}

export function Stat({
  label,
  value,
  hint,
  tone,
  testId,
}: {
  label: string
  value: ReactNode
  hint?: string
  tone?: 'good' | 'bad' | 'warn'
  testId?: string
}) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2" title={hint} data-testid={testId}>
      <p className="text-[11px] font-medium text-muted-foreground">{label}</p>
      <p
        className={cn(
          'text-lg font-semibold tabular-nums',
          tone === 'good' && 'text-emerald-700',
          tone === 'bad' && 'text-red-700',
          tone === 'warn' && 'text-amber-700',
        )}
      >
        {value}
      </p>
    </div>
  )
}

const SHACL_BADGE: Record<string, { label: string; className: string }> = {
  conforms: { label: 'Conforms', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  Violation: { label: 'Violation', className: 'border-red-200 bg-red-50 text-red-700' },
  Warning: { label: 'Warning', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  Info: { label: 'Info', className: 'border-sky-200 bg-sky-50 text-sky-700' },
}

/** Most severe SHACL result of a fact; builds evaluated before SHACL validation existed show "not run". */
export function ShaclBadge({ status }: { status: string | null }) {
  if (!status) {
    return (
      <span className="text-[11px] text-muted-foreground" title="Build evaluated before SHACL validation existed">
        not run
      </span>
    )
  }
  const meta = SHACL_BADGE[status]
  return (
    <Badge variant="outline" className={cn('text-[10px]', meta.className)} data-testid="shacl-badge">
      {meta.label}
    </Badge>
  )
}

