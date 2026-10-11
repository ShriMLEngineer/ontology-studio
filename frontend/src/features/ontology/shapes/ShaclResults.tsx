import { CheckCircle2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { ShaclResultRead, ShaclValidationReport } from '@/lib/api/types'
import { plural } from '@/lib/format'
import { OUTCOME_STYLE, SEVERITY_STYLE } from './severity'

export function ShaclResultList({ results }: { results: ShaclResultRead[] }) {
  return (
    <ul className="divide-y rounded-lg border text-xs" data-testid="shacl-results">
      {results.map((r, i) => (
        <li key={i} className="space-y-0.5 px-3 py-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline" className={SEVERITY_STYLE[r.severity]}>
              {r.severity}
            </Badge>
            {r.outcome && (
              <Badge variant="outline" className={OUTCOME_STYLE[r.outcome]} title="Outcome under the build's validation policy">
                {r.outcome}
              </Badge>
            )}
            <span className="font-mono">{r.component.replace('ConstraintComponent', '')}</span>
            <span className="text-muted-foreground">
              {r.shape_origin} {r.shape_role} shape{r.shape_label ? ` · ${r.shape_label}` : ''}
            </span>
          </div>
          <p>{r.message}</p>
          <p className="font-mono text-[10px] break-all text-muted-foreground">
            focus {r.focus}
            {r.path ? ` · path ${r.path}` : ''}
            {r.value ? ` · value ${r.value}` : ''}
          </p>
        </li>
      ))}
    </ul>
  )
}

export function ShaclResults({ report }: { report: ShaclValidationReport }) {
  return (
    <div className="space-y-2" data-testid="shacl-report">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {report.conforms ? (
          <Badge className="gap-1 bg-emerald-600">
            <CheckCircle2 className="size-3" /> Conforms
          </Badge>
        ) : (
          <Badge variant="destructive">Does not conform</Badge>
        )}
        <span className="text-xs text-muted-foreground">
          {plural(report.data_triples, 'data triple')} · {plural(report.shapes_used, 'shape')} · {report.duration_ms} ms
        </span>
      </div>
      {report.results.length > 0 && <ShaclResultList results={report.results} />}
    </div>
  )
}
