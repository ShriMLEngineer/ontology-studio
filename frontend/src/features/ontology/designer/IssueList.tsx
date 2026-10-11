import { cn } from 'cn'

import type { ValidationIssue } from '@/lib/api/types'
import { SEVERITY_META } from './presentation'

export function IssueList({ issues, stale }: { issues: ValidationIssue[]; stale?: boolean }) {
  if (issues.length === 0) return null
  return (
    <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
      <p className="text-xs font-medium">
        Validation findings{stale && <span className="font-normal text-muted-foreground"> (from an earlier revision)</span>}
      </p>
      <ul className="space-y-1.5">
        {issues.map((issue, index) => {
          const meta = SEVERITY_META[issue.severity]
          return (
            <li key={`${issue.code}-${index}`} className="flex gap-2 text-xs">
              <meta.icon className={cn('mt-0.5 size-3.5 shrink-0', meta.className)} aria-label={meta.label} />
              <span>{issue.message}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
