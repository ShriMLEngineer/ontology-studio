import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, GitCompareArrows, History } from 'lucide-react'
import { cn } from 'cn'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ErrorState, LoadingState } from '@/components/common/states'
import { kgApi } from '@/lib/api/endpoints'
import type { BuildSummary } from '@/lib/api/types'
import { relativeTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import { NativeSelect } from '../fields'
import { duration, percent } from '../meta'
import { BuildStatusBadge } from '../shared'

function formatMetric(value: number | null, unit: string): string {
  if (value === null || value === undefined) return '—'
  return unit === 'ratio' ? percent(value) : String(value)
}

function ComparisonDialog({ base, target, onClose }: { base: BuildSummary; target: BuildSummary; onClose: () => void }) {
  const comparison = useQuery({
    queryKey: queryKeys.kgCompare(base.id, target.id),
    queryFn: () => kgApi.compare(base.id, target.id),
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl" data-testid="build-comparison">
        <DialogHeader>
          <DialogTitle>
            Build #{base.number} (v{base.ontology_version}) <ArrowRight className="inline size-4" /> Build #{target.number} (v
            {target.ontology_version})
          </DialogTitle>
          <DialogDescription>Graph elements are compared by their stable identifiers; both builds remain unchanged.</DialogDescription>
        </DialogHeader>
        {comparison.isPending ? (
          <LoadingState />
        ) : comparison.isError ? (
          <ErrorState error={comparison.error} />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              {(['nodes', 'edges'] as const).map((kind) => {
                const diff = comparison.data[kind]
                return (
                  <div key={kind} className="rounded-lg border p-3 text-sm">
                    <p className="font-medium capitalize">{kind}</p>
                    <p className="text-xs text-muted-foreground">
                      <span className="text-emerald-700">+{diff.added} added</span> ·{' '}
                      <span className="text-red-700">−{diff.removed} removed</span> · {diff.unchanged} unchanged
                    </p>
                    <ul className="mt-2 space-y-0.5 text-xs">
                      {diff.added_items.map((item) => (
                        <li key={item.id} className="text-emerald-800">
                          + {item.label}
                        </li>
                      ))}
                      {diff.removed_items.map((item) => (
                        <li key={item.id} className="text-red-800">
                          − {item.label}
                        </li>
                      ))}
                    </ul>
                  </div>
                )
              })}
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1 font-medium">Metric</th>
                  <th className="py-1 text-right font-medium">#{base.number}</th>
                  <th className="py-1 text-right font-medium">#{target.number}</th>
                </tr>
              </thead>
              <tbody>
                {comparison.data.metrics.map((metric) => (
                  <tr key={metric.key} className={cn('border-t', metric.base !== metric.target && 'bg-amber-50/60')}>
                    <td className="py-1">{metric.label}</td>
                    <td className="py-1 text-right tabular-nums">{formatMetric(metric.base, metric.unit)}</td>
                    <td className="py-1 text-right tabular-nums">{formatMetric(metric.target, metric.unit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function BuildHistory({
  builds,
  selectedId,
  onSelect,
}: {
  builds: BuildSummary[]
  selectedId: string | undefined
  onSelect: (buildId: string) => void
}) {
  const completed = builds.filter((b) => b.status === 'completed')
  const [base, setBase] = useState<string>('')
  const [target, setTarget] = useState<string>('')
  const [comparing, setComparing] = useState(false)
  const baseBuild = completed.find((b) => b.id === (base || completed[1]?.id))
  const targetBuild = completed.find((b) => b.id === (target || completed[0]?.id))

  return (
    <Card size="sm" data-testid="build-history">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="size-4" /> Build history
        </CardTitle>
        <CardDescription>Every build keeps its ontology version, configuration, results and graph.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <ul className="divide-y rounded-lg border">
          {builds.map((build) => {
            const facts = build.stats.facts?.by_status ?? {}
            return (
              <li key={build.id}>
                <button
                  type="button"
                  onClick={() => onSelect(build.id)}
                  className={cn(
                    'flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-muted/50',
                    build.id === selectedId && 'bg-primary/5',
                  )}
                  data-testid={`history-${build.number}`}
                >
                  <span className="w-8 font-mono text-xs text-muted-foreground">#{build.number}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{build.name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {build.ontology_name} v{build.ontology_version} · {relativeTime(build.created_at)}
                      {build.duration_ms !== null ? ` · ${duration(build.duration_ms)}` : ''}
                    </span>
                  </span>
                  {build.status === 'completed' && (
                    <span className="hidden text-xs tabular-nums sm:block">
                      <span className="text-emerald-700">{facts.accepted ?? 0}</span> /{' '}
                      <span className="text-red-700">{facts.rejected ?? 0}</span> /{' '}
                      <span className="text-amber-700">{facts.quarantined ?? 0}</span>
                    </span>
                  )}
                  <BuildStatusBadge status={build.status} />
                </button>
              </li>
            )
          })}
        </ul>
        {completed.length >= 2 && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <GitCompareArrows className="size-4 text-muted-foreground" />
            Compare
            <NativeSelect aria-label="Base build" className="h-7 w-auto text-xs" value={baseBuild?.id ?? ''} onChange={(e) => setBase(e.target.value)}>
              {completed.map((b) => (
                <option key={b.id} value={b.id}>
                  #{b.number} (v{b.ontology_version})
                </option>
              ))}
            </NativeSelect>
            with
            <NativeSelect aria-label="Target build" className="h-7 w-auto text-xs" value={targetBuild?.id ?? ''} onChange={(e) => setTarget(e.target.value)}>
              {completed.map((b) => (
                <option key={b.id} value={b.id}>
                  #{b.number} (v{b.ontology_version})
                </option>
              ))}
            </NativeSelect>
            <Button size="xs" variant="outline" disabled={!baseBuild || !targetBuild || baseBuild.id === targetBuild.id} onClick={() => setComparing(true)}>
              Compare builds
            </Button>
          </div>
        )}
      </CardContent>
      {comparing && baseBuild && targetBuild && (
        <ComparisonDialog base={baseBuild} target={targetBuild} onClose={() => setComparing(false)} />
      )}
    </Card>
  )
}
