import { useQuery } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'

import { DrawerSection, RightDrawer } from '@/components/common/RightDrawer'
import { ErrorState, LoadingState } from '@/components/common/states'
import { Badge } from '@/components/ui/badge'
import { kgApi } from '@/lib/api/endpoints'
import type { GraphNode } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import { FactProvenance } from '../facts/FactProvenance'
import { FactStatusBadge } from '../shared'

function NodeChip({ node, color, onSelect }: { node: GraphNode; color: string; onSelect: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(node.id)}
      className="inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-left text-xs hover:bg-muted"
    >
      <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      <span className="truncate font-medium">{node.name}</span>
      <span className="text-muted-foreground">{node.class_label}</span>
    </button>
  )
}

export function GraphDetailsDrawer({
  buildId,
  elementId,
  colors,
  onSelect,
  onClose,
}: {
  buildId: string
  elementId: string
  colors: Record<string, string>
  onSelect: (id: string) => void
  onClose: () => void
}) {
  const detail = useQuery({
    queryKey: queryKeys.kgElement(buildId, elementId),
    queryFn: () => kgApi.element(buildId, elementId),
  })
  const data = detail.data
  const title =
    data?.kind === 'edge' && data.edge
      ? `${data.subject?.name ?? '?'} → ${data.edge.predicate_label} → ${data.object?.name ?? '?'}`
      : (data?.node?.name ?? 'Graph element')
  const color = (classId: string | undefined) => (classId ? (colors[classId] ?? '#64748b') : '#64748b')

  return (
    <RightDrawer
      title={title}
      subtitle={elementId}
      badge={
        data && (
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary">{data.kind === 'edge' ? 'Relationship' : (data.node?.class_label ?? 'Entity')}</Badge>
            <FactStatusBadge status="accepted" />
          </div>
        )
      }
      onClose={onClose}
      className="w-[440px]"
    >
      {detail.isPending ? (
        <LoadingState />
      ) : detail.isError ? (
        <ErrorState error={detail.error} />
      ) : (
        <div className="space-y-5" data-testid="graph-details" data-kind={data!.kind}>
          <DrawerSection title="Traceability">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">Build run</dt>
              <dd>#{data!.build_number}</dd>
              <dt className="text-muted-foreground">Ontology version</dt>
              <dd className="font-mono" data-testid="details-version">
                v{data!.ontology_version}
              </dd>
              <dt className="text-muted-foreground">Validation</dt>
              <dd>Accepted - only accepted facts are stored in the graph</dd>
              <dt className="text-muted-foreground">Supporting facts</dt>
              <dd>{data!.facts.length}</dd>
            </dl>
          </DrawerSection>

          {data!.kind === 'edge' && data!.edge && (
            <DrawerSection title="Relationship">
              <div className="space-y-2">
                {data!.subject && <NodeChip node={data!.subject} color={color(data!.subject.class_id)} onSelect={onSelect} />}
                <p className="flex items-center gap-1.5 pl-2 text-xs">
                  <ArrowRight className="size-3.5" />
                  <strong>{data!.edge.predicate_label}</strong>
                  <span className="font-mono text-muted-foreground">{data!.edge.predicate_id}</span>
                </p>
                {data!.object && <NodeChip node={data!.object} color={color(data!.object.class_id)} onSelect={onSelect} />}
              </div>
            </DrawerSection>
          )}

          {data!.kind === 'node' && data!.node && (
            <>
              <DrawerSection title="Entity">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                  <dt className="text-muted-foreground">Class</dt>
                  <dd>
                    {data!.node.class_label} <span className="font-mono text-muted-foreground">{data!.node.class_id}</span>
                  </dd>
                  {data!.node.identifier && (
                    <>
                      <dt className="text-muted-foreground">Identifier</dt>
                      <dd className="font-mono">{data!.node.identifier}</dd>
                    </>
                  )}
                  {data!.node.properties.map((property) => (
                    <div key={property.key} className="contents">
                      <dt className="text-muted-foreground">{property.label}</dt>
                      <dd>{property.values.map(String).join(', ')}</dd>
                    </div>
                  ))}
                </dl>
              </DrawerSection>
              {data!.relationships.length > 0 && (
                <DrawerSection title={`Relationships (${data!.relationships.length})`}>
                  <ul className="space-y-1 text-xs">
                    {data!.relationships.map((edge) => {
                      const outgoing = edge.source === data!.node!.id
                      const other = data!.neighbours.find((n) => n.id === (outgoing ? edge.target : edge.source))
                      return (
                        <li key={edge.id}>
                          <button
                            type="button"
                            className="w-full rounded px-1.5 py-1 text-left hover:bg-muted"
                            onClick={() => onSelect(edge.id)}
                          >
                            {outgoing ? (
                              <>
                                <strong>{edge.predicate_label}</strong> → {other?.name ?? edge.target}
                              </>
                            ) : (
                              <>
                                {other?.name ?? edge.source} → <strong>{edge.predicate_label}</strong>
                              </>
                            )}
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </DrawerSection>
              )}
            </>
          )}

          <DrawerSection title="Provenance and evidence">
            <ul className="space-y-4">
              {data!.facts.map((fact) => (
                <li key={fact.id} className="rounded-lg border p-3">
                  <FactProvenance fact={fact} />
                </li>
              ))}
            </ul>
          </DrawerSection>
        </div>
      )}
    </RightDrawer>
  )
}
