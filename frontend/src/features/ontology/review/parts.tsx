import { AlertCircle, CheckCircle2, FileText, ShieldCheck } from 'lucide-react'
import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import type { ProposalEvidence, ProposalImpact } from '@/lib/api/types'
import { SEVERITY_META } from '../designer/presentation'
import type { LabelResolver } from './labels'

const REFERENCE_FIELDS = new Set(['domain_id', 'range_id'])

export function FieldValue({ field, value, labelOf }: { field: string; value: unknown; labelOf: LabelResolver }) {
  if (value === null || value === undefined || value === '') return <span className="text-muted-foreground italic">empty</span>
  if (field === 'parent_ids' && Array.isArray(value)) {
    return value.length ? <span>{value.map((id) => labelOf(String(id))).join(', ')}</span> : <span className="text-muted-foreground italic">none</span>
  }
  if (REFERENCE_FIELDS.has(field)) return <span>{labelOf(String(value))}</span>
  if (Array.isArray(value)) {
    return value.length ? (
      <span className="flex flex-wrap gap-1">
        {value.map((item) => (
          <Badge key={String(item)} variant="secondary">
            {String(item)}
          </Badge>
        ))}
      </span>
    ) : (
      <span className="text-muted-foreground italic">none</span>
    )
  }
  if (typeof value === 'boolean') return <span>{value ? 'Yes' : 'No'}</span>
  if (field === 'datatype') return <span className="font-mono text-xs">xsd:{String(value)}</span>
  if (field === 'local_name') return <span className="font-mono text-xs">{String(value)}</span>
  return <span className="whitespace-pre-wrap">{String(value)}</span>
}

export function EvidenceCard({ evidence }: { evidence: ProposalEvidence }) {
  const context = evidence.context || evidence.quote
  const index = context.indexOf(evidence.quote)
  return (
    <figure className="rounded-lg border bg-muted/30 p-3" data-testid="proposal-evidence">
      <blockquote className="text-sm leading-relaxed">
        {index >= 0 ? (
          <>
            <span className="text-muted-foreground">{context.slice(0, index)}</span>
            <mark className="rounded bg-amber-100 px-0.5 text-foreground">{evidence.quote}</mark>
            <span className="text-muted-foreground">{context.slice(index + evidence.quote.length)}</span>
          </>
        ) : (
          <mark className="rounded bg-amber-100 px-0.5">{evidence.quote}</mark>
        )}
      </blockquote>
      <figcaption className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <FileText className="size-3.5" />
        <span className="font-medium text-foreground">{evidence.document_name}</span>
        {evidence.page && <span>page {evidence.page}</span>}
        {evidence.start_offset !== null && <span>characters {evidence.start_offset}-{evidence.end_offset}</span>}
        {evidence.verified && (
          <Badge variant="outline" className="border-emerald-300 text-emerald-700">
            <ShieldCheck /> Verified in source
          </Badge>
        )}
        {!evidence.document_id && <span>(source document deleted; quote retained)</span>}
      </figcaption>
    </figure>
  )
}

export function ImpactPanel({ impact }: { impact: ProposalImpact }) {
  if (!impact.applicable) {
    return (
      <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
        <AlertCircle className="mt-0.5 size-4 shrink-0" />
        <div>
          <p className="font-medium">Cannot be applied to the current draft</p>
          <p>{impact.reason}</p>
        </div>
      </div>
    )
  }
  const quiet = impact.introduced_issues.length === 0 && impact.resolved_issues.length === 0
  return (
    <div
      className={cn(
        'space-y-2 rounded-lg border p-3 text-sm',
        impact.blocking ? 'border-red-200 bg-red-50' : 'border-emerald-200 bg-emerald-50/60',
      )}
      data-testid="proposal-impact"
    >
      <p className="flex items-center gap-2 font-medium">
        {impact.blocking ? <AlertCircle className="size-4 text-red-600" /> : <CheckCircle2 className="size-4 text-emerald-600" />}
        {impact.blocking
          ? 'Applying this proposal would introduce blocking validation errors'
          : quiet
            ? 'Applies cleanly - no validation changes'
            : 'Applies cleanly - validation changes below'}
      </p>
      {impact.introduced_issues.length > 0 && (
        <ul className="space-y-1">
          {impact.introduced_issues.map((issue, i) => {
            const meta = SEVERITY_META[issue.severity]
            return (
              <li key={`${issue.code}-${i}`} className="flex gap-2 text-xs">
                <meta.icon className={cn('mt-0.5 size-3.5 shrink-0', meta.className)} />
                <span>
                  <span className="font-medium">Introduces:</span> {issue.message}
                </span>
              </li>
            )
          })}
        </ul>
      )}
      {impact.resolved_issues.length > 0 && (
        <ul className="space-y-1">
          {impact.resolved_issues.map((issue, i) => (
            <li key={`${issue.code}-${i}`} className="flex gap-2 text-xs">
              <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />
              <span>
                <span className="font-medium">Resolves:</span> {issue.message}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
