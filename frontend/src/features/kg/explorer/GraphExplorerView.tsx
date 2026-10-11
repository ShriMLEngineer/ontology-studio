import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LayoutGrid, Network, RefreshCw, Search, Table2 } from 'lucide-react'
import { cn } from 'cn'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { kgApi } from '@/lib/api/endpoints'
import type { BuildDetail, FacetCount, GraphData } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import { NativeSelect } from '../fields'
import { classColor } from '../meta'
import { GraphCanvas } from './GraphCanvas'
import { GraphDetailsDrawer } from './GraphDetailsDrawer'

function FacetChips({
  label,
  facets,
  selected,
  onToggle,
  colors,
}: {
  label: string
  facets: FacetCount[]
  selected: string[]
  onToggle: (id: string) => void
  colors?: Record<string, string>
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {facets.map((facet) => {
          const active = selected.includes(facet.id)
          return (
            <button
              key={facet.id}
              type="button"
              aria-pressed={active}
              onClick={() => onToggle(facet.id)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition-colors',
                active ? 'border-primary bg-primary/10 text-primary' : 'hover:bg-muted',
              )}
              data-testid={`facet-${facet.id}`}
            >
              {colors && <span className="size-2 rounded-full" style={{ backgroundColor: colors[facet.id] }} />}
              {facet.label}
              <span className="text-muted-foreground tabular-nums">{facet.count}</span>
            </button>
          )
        })}
        {facets.length === 0 && <span className="text-xs text-muted-foreground">None</span>}
      </div>
    </div>
  )
}

function GraphTable({ graph, onSelect }: { graph: GraphData; onSelect: (id: string) => void }) {
  const names = Object.fromEntries(graph.nodes.map((n) => [n.id, n.name]))
  return (
    <div className="grid h-full gap-6 overflow-y-auto p-6 xl:grid-cols-2" data-testid="graph-table">
      <section>
        <h3 className="mb-2 text-sm font-semibold">Relationships ({graph.edges.length})</h3>
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 font-medium">Subject</th>
              <th className="py-1 font-medium">Relationship</th>
              <th className="py-1 font-medium">Object</th>
              <th className="py-1 text-right font-medium">Facts</th>
            </tr>
          </thead>
          <tbody>
            {graph.edges.map((edge) => (
              <tr key={edge.id} className="cursor-pointer border-t hover:bg-muted/50" onClick={() => onSelect(edge.id)} data-testid="graph-edge-row">
                <td className="py-1.5">{names[edge.source]}</td>
                <td className="py-1.5 font-medium">{edge.predicate_label}</td>
                <td className="py-1.5">{names[edge.target]}</td>
                <td className="py-1.5 text-right tabular-nums">{edge.fact_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold">Entities ({graph.nodes.length})</h3>
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 font-medium">Name</th>
              <th className="py-1 font-medium">Class</th>
              <th className="py-1 font-medium">Identifier</th>
            </tr>
          </thead>
          <tbody>
            {graph.nodes.map((node) => (
              <tr key={node.id} className="cursor-pointer border-t hover:bg-muted/50" onClick={() => onSelect(node.id)} data-testid="graph-node-row">
                <td className="py-1.5 font-medium">{node.name}</td>
                <td className="py-1.5">{node.class_label}</td>
                <td className="py-1.5 font-mono">{node.identifier ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

export function GraphExplorerView({ build }: { build: BuildDetail }) {
  const [classIds, setClassIds] = useState<string[]>([])
  const [predicateIds, setPredicateIds] = useState<string[]>([])
  const [sourceId, setSourceId] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState<'graph' | 'table'>('graph')
  const [layoutNonce, setLayoutNonce] = useState(0)
  const [search, setSearch] = useState('')

  const params = useMemo(
    () => ({
      class_id: classIds.length ? classIds : undefined,
      predicate_id: predicateIds.length ? predicateIds : undefined,
      source_id: sourceId ? [sourceId] : undefined,
    }),
    [classIds, predicateIds, sourceId],
  )
  const graph = useQuery({
    queryKey: queryKeys.kgGraph(build.id, params),
    queryFn: () => kgApi.graph(build.id, params),
    placeholderData: (previous) => previous,
  })
  const term = search.trim()
  const results = useQuery({
    queryKey: ['kg-builds', build.id, 'search', term],
    queryFn: () => kgApi.search(build.id, term),
    enabled: term.length >= 2,
  })

  const classOrder = useMemo(() => (graph.data?.classes ?? []).map((c) => c.id), [graph.data?.classes])
  const colors = useMemo(() => Object.fromEntries(classOrder.map((id) => [id, classColor(id, classOrder)])), [classOrder])
  const toggle = (list: string[], setter: (value: string[]) => void, id: string) =>
    setter(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])

  if (graph.isPending) return <LoadingState label="Loading graph from the graph store…" />
  if (graph.isError) return <ErrorState className="m-6" error={graph.error} onRetry={() => graph.refetch()} />
  const data = graph.data

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto border-r p-4" aria-label="Graph filters">
        <div className="relative">
          <Search className="absolute top-2 left-2 size-4 text-muted-foreground" />
          <Input
            aria-label="Search entities"
            className="pl-8"
            placeholder="Search entities"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {term.length >= 2 && results.data && (
            <ul className="mt-1 max-h-56 overflow-y-auto rounded-lg border bg-popover text-xs shadow-sm" data-testid="search-results">
              {results.data.length === 0 && <li className="px-2 py-1.5 text-muted-foreground">No matching entity</li>}
              {results.data.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-muted"
                    onClick={() => {
                      setSelected(node.id)
                      setSearch('')
                    }}
                  >
                    <span className="size-2 rounded-full" style={{ backgroundColor: colors[node.class_id] ?? '#64748b' }} />
                    <span className="truncate font-medium">{node.name}</span>
                    <span className="ml-auto text-muted-foreground">{node.class_label}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <FacetChips label="Entity class" facets={data.classes} selected={classIds} onToggle={(id) => toggle(classIds, setClassIds, id)} colors={colors} />
        <FacetChips
          label="Relationship type"
          facets={data.predicates}
          selected={predicateIds}
          onToggle={(id) => toggle(predicateIds, setPredicateIds, id)}
        />
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Source</p>
          <NativeSelect aria-label="Filter by source" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">All sources</option>
            {data.sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label} ({s.count})
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="mt-auto space-y-1 rounded-lg bg-muted/40 p-3 text-xs text-muted-foreground" data-testid="graph-summary">
          <p>
            Showing <strong className="text-foreground">{data.nodes.length}</strong> of {data.total_nodes} nodes and{' '}
            <strong className="text-foreground">{data.edges.length}</strong> of {data.total_edges} edges
          </p>
          <p>
            Build #{data.build_number} · ontology v{data.ontology_version} · {data.graph_store ?? 'graph'} store
          </p>
          {data.truncated && <p className="text-amber-700">Large graph truncated; use filters to narrow it down.</p>}
        </div>
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b px-4 py-2">
          <div className="flex rounded-lg border p-0.5" role="group" aria-label="View">
            <Button variant={view === 'graph' ? 'secondary' : 'ghost'} size="xs" onClick={() => setView('graph')} aria-pressed={view === 'graph'}>
              <Network /> Graph
            </Button>
            <Button variant={view === 'table' ? 'secondary' : 'ghost'} size="xs" onClick={() => setView('table')} aria-pressed={view === 'table'}>
              <Table2 /> Table
            </Button>
          </div>
          {view === 'graph' && (
            <Button variant="ghost" size="xs" onClick={() => setLayoutNonce((n) => n + 1)}>
              <RefreshCw /> Re-run layout
            </Button>
          )}
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            <LayoutGrid className="size-3.5" /> Drag to pan · scroll to zoom · click a node or relationship for provenance
          </span>
        </div>
        <div className="min-h-0 flex-1">
          {data.nodes.length === 0 ? (
            <EmptyState className="m-6" icon={<Network />} title="No graph elements match the filters" />
          ) : view === 'graph' ? (
            <GraphCanvas
              nodes={data.nodes}
              edges={data.edges}
              colors={colors}
              selectedId={selected}
              layoutNonce={layoutNonce}
              onSelect={setSelected}
            />
          ) : (
            <GraphTable graph={data} onSelect={setSelected} />
          )}
        </div>
      </div>

      {selected && (
        <GraphDetailsDrawer
          key={selected}
          buildId={build.id}
          elementId={selected}
          colors={colors}
          onSelect={setSelected}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
