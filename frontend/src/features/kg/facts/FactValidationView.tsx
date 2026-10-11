import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ListChecks, Search } from 'lucide-react'
import { cn } from 'cn'

import { RightDrawer } from '@/components/common/RightDrawer'
import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Input } from '@/components/ui/input'
import { kgApi } from '@/lib/api/endpoints'
import type { BuildDetail, FactKind, FactStatus } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import { NativeSelect } from '../fields'
import { FACT_STATUS_META, factStatement } from '../meta'
import { EvidenceBadge, FactStatusBadge } from '../shared'
import { FactProvenance } from './FactProvenance'

const STATUS_FILTERS: { value: FactStatus | ''; label: string }[] = [
  { value: '', label: 'All candidate facts' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'quarantined', label: 'Quarantined' },
]
const KIND_LABEL: Record<FactKind, string> = { relationship: 'Relationships', attribute: 'Attributes', type: 'Entities' }

function FactDrawer({ factId, onClose }: { factId: string; onClose: () => void }) {
  const fact = useQuery({ queryKey: queryKeys.kgFact(factId), queryFn: () => kgApi.fact(factId) })
  return (
    <RightDrawer
      title={fact.data ? factStatement(fact.data) : 'Fact'}
      subtitle={fact.data?.id}
      onClose={onClose}
      className="w-[440px]"
    >
      {fact.isPending ? <LoadingState /> : fact.isError ? <ErrorState error={fact.error} /> : <FactProvenance fact={fact.data} showStatement={false} />}
    </RightDrawer>
  )
}

export function FactValidationView({ build }: { build: BuildDetail }) {
  const [status, setStatus] = useState<FactStatus | ''>('')
  const [kind, setKind] = useState<FactKind | ''>('relationship')
  const [source, setSource] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  const params = useMemo(
    () => ({ status: status || undefined, kind: kind || undefined, source_id: source || undefined, q: search.trim() || undefined }),
    [status, kind, source, search],
  )
  const facts = useQuery({
    queryKey: queryKeys.kgFacts(build.id, params),
    queryFn: () => kgApi.facts(build.id, params),
    placeholderData: (previous) => previous,
  })
  const totals = build.stats.facts?.by_status ?? {}

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="space-y-3 border-b px-6 py-3">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Fact status">
            {STATUS_FILTERS.map((filter) => {
              const count =
                filter.value === ''
                  ? Object.values(totals).reduce((sum, n) => sum + (n ?? 0), 0)
                  : (totals[filter.value] ?? 0)
              return (
                <button
                  key={filter.value || 'all'}
                  type="button"
                  role="tab"
                  aria-selected={status === filter.value}
                  onClick={() => setStatus(filter.value)}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                    status === filter.value ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted',
                  )}
                  title={filter.value ? FACT_STATUS_META[filter.value].description : undefined}
                  data-testid={`fact-filter-${filter.value || 'all'}`}
                >
                  {filter.label} <span className="tabular-nums opacity-80">({count})</span>
                </button>
              )
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect aria-label="Fact kind" className="h-8 w-auto" value={kind} onChange={(e) => setKind(e.target.value as FactKind | '')}>
              <option value="">All kinds</option>
              {(Object.keys(KIND_LABEL) as FactKind[]).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]} {facts.data?.kind_counts[k] !== undefined ? `(${facts.data.kind_counts[k]})` : ''}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect aria-label="Source" className="h-8 w-auto" value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">All sources</option>
              {build.sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.filename}
                </option>
              ))}
            </NativeSelect>
            <div className="relative min-w-56 flex-1">
              <Search className="absolute top-2 left-2 size-4 text-muted-foreground" />
              <Input
                aria-label="Search facts"
                className="pl-8"
                placeholder="Search subject, relationship, object or value"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-3">
          {facts.isPending ? (
            <LoadingState />
          ) : facts.isError ? (
            <ErrorState error={facts.error} onRetry={() => facts.refetch()} />
          ) : facts.data.items.length === 0 ? (
            <EmptyState icon={<ListChecks />} title="No facts match these filters" />
          ) : (
            <table className="w-full text-sm" data-testid="fact-table">
              <thead className="sticky top-0 z-10 bg-background text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Candidate fact</th>
                  <th className="py-2 pr-3 font-medium">Evidence</th>
                  <th className="py-2 pr-3 font-medium">Reason</th>
                  <th className="py-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {facts.data.items.map((fact) => (
                  <tr
                    key={fact.id}
                    onClick={() => setSelected(fact.id)}
                    className={cn('cursor-pointer border-t align-top hover:bg-muted/40', selected === fact.id && 'bg-primary/5')}
                    data-testid="fact-row"
                    data-fact-status={fact.status}
                  >
                    <td className="py-2 pr-3">
                      <FactStatusBadge status={fact.status} />
                    </td>
                    <td className="py-2 pr-3">
                      <button type="button" className="text-left font-medium hover:underline" onClick={() => setSelected(fact.id)}>
                        {factStatement(fact)}
                      </button>
                      <p className="text-xs text-muted-foreground">
                        {fact.kind} · {fact.origin === 'llm' ? 'LLM extraction' : 'structured mapping'}
                        {fact.predicate_id ? ` · ${fact.predicate_id}` : ''}
                      </p>
                    </td>
                    <td className="py-2 pr-3">
                      <EvidenceBadge status={fact.evidence_status} />
                    </td>
                    <td className="max-w-md py-2 pr-3 text-xs text-muted-foreground">
                      {fact.status === 'accepted' ? '—' : (fact.reasons[0] ?? '—')}
                      {fact.reasons.length > 1 && <span className="ml-1 text-[10px]">(+{fact.reasons.length - 1})</span>}
                    </td>
                    <td className="py-2 text-xs whitespace-nowrap text-muted-foreground">{fact.source_label}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {facts.data && facts.data.total > facts.data.items.length && (
            <p className="py-2 text-xs text-muted-foreground">
              Showing {facts.data.items.length} of {facts.data.total}; refine the filters to see more.
            </p>
          )}
        </div>
      </div>
      {selected && <FactDrawer key={selected} factId={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
