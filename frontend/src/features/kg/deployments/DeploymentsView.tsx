import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Database, Loader2, Play, Rocket, Search, ShieldAlert, Telescope, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from 'cn'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { kgApi } from '@/lib/api/endpoints'
import type {
  BuildDetail,
  CompatibilityOutcome,
  CompatibilityReport,
  Deployment,
  DeploymentStatus,
  SparqlResult,
  SparqlTerm,
} from '@/lib/api/types'
import { relativeTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import { useReviewerName } from '@/features/ontology/governance/reviewer'
import { useGraphConnections } from '@/features/settings/hooks'
import { GraphCapabilityChips, GraphStatusBadge } from '@/features/settings/GraphCapabilities'
import { GraphTargetSelect } from '@/features/settings/selectors'
import { FormField, NativeSelect } from '../fields'
import { useDeployments, useGraphCapabilities } from '../hooks'

const OUTCOME: Record<CompatibilityOutcome, { label: string; className: string }> = {
  native: { label: 'Native', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  transformed: { label: 'Transformed', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  partial: { label: 'Partial', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  unsupported: { label: 'Not stored', className: 'border-slate-200 bg-slate-50 text-slate-700' },
  semantic_loss: { label: 'Semantic loss', className: 'border-red-200 bg-red-50 text-red-800' },
}

const STATUS: Record<DeploymentStatus, { label: string; className: string }> = {
  running: { label: 'Running', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  completed: { label: 'Verified', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  failed: { label: 'Failed', className: 'border-red-200 bg-red-50 text-red-800' },
  superseded: { label: 'Superseded', className: 'border-slate-200 bg-slate-50 text-slate-600' },
}

const ORIGIN: Record<Deployment['origin'], string> = {
  build: 'by the build',
  manual: 'manual',
  legacy: 'recorded at upgrade',
}

function CompatibilityTable({ report }: { report: CompatibilityReport }) {
  return (
    <div className="space-y-2" data-testid="compatibility-report">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {(Object.keys(OUTCOME) as CompatibilityOutcome[]).map((outcome) =>
          report.counts[outcome] ? (
            <Badge key={outcome} variant="outline" className={OUTCOME[outcome].className}>
              {report.counts[outcome]} {OUTCOME[outcome].label.toLowerCase()}
            </Badge>
          ) : null,
        )}
        <span className="text-muted-foreground">
          · capability profile <span className="font-mono">{report.capability_profile}</span>
          {report.capability_profile_verified ? ' (verified)' : ' (documented assumption, not verified)'} · mapping{' '}
          <span className="font-mono">{report.mapping_profile}</span>
        </span>
      </div>
      <table className="w-full text-xs">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="py-1 pr-2 font-medium">Feature</th>
            <th className="py-1 pr-2 font-medium">Scope</th>
            <th className="py-1 pr-2 font-medium">Outcome</th>
            <th className="py-1 pr-2 text-right font-medium">Affected</th>
            <th className="py-1 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row) => (
            <tr key={row.feature} className="border-t align-top" data-outcome={row.outcome}>
              <td className="py-1.5 pr-2 font-medium">{row.feature}</td>
              <td className="py-1.5 pr-2 text-muted-foreground">{row.scope}</td>
              <td className="py-1.5 pr-2">
                <Badge variant="outline" className={OUTCOME[row.outcome].className}>
                  {OUTCOME[row.outcome].label}
                </Badge>
              </td>
              <td className="py-1.5 pr-2 text-right tabular-nums">{row.affected || '—'}</td>
              <td className="py-1.5 text-muted-foreground">
                {row.detail}
                {row.recommendation && <span className="block text-foreground/80">→ {row.recommendation}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DeployPanel({ build, deployments }: { build: BuildDetail; deployments: Deployment[] }) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const connections = useGraphConnections()
  const capabilities = useGraphCapabilities()
  const [targetId, setTargetId] = useState<string>('oxigraph-embedded')
  const [mapping, setMapping] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [previewKind, setPreviewKind] = useState('')

  const target = connections.data?.find((c) => c.id === targetId)
  const model = target?.model === 'rdf' ? 'rdf' : 'property-graph'
  const mappings = (capabilities.data?.mapping_profiles ?? []).filter((m) => m.data_model === model)
  const effectiveMapping = mappings.some((m) => m.id === mapping) ? mapping : ''
  const report = useQuery({
    queryKey: queryKeys.kgCompatibility(build.id, targetId, effectiveMapping),
    queryFn: () => kgApi.compatibility(build.id, { target_id: targetId, mapping_profile: effectiveMapping || undefined }),
    enabled: Boolean(target),
  })
  const preview = useQuery({
    queryKey: queryKeys.kgCompatibility(build.id, `kind:${previewKind}`, ''),
    queryFn: () => kgApi.compatibility(build.id, { kind: previewKind }),
    enabled: Boolean(previewKind),
  })
  const unavailable = (capabilities.data?.profiles ?? []).filter((p) => !p.adapter_available)
  const loss = report.data?.report.has_semantic_loss ?? false
  const current = deployments.find((d) => d.target_id === targetId && d.status === 'completed')
  const internal = Boolean(target && (target.builtin || target.provider === 'local-sql'))
  // Connection support is not deployment readiness: say precisely what blocks or qualifies a deployment.
  const blockedReason = !target
    ? ''
    : !target.enabled
      ? 'This graph database is disabled in Settings.'
      : !target.capabilities.deployment_supported
        ? 'No deployment adapter exists for this provider.'
        : !target.capabilities.write_configured
          ? 'This registration has no update endpoint, so it is read-only and cannot receive a deployment.'
          : ''

  const deploy = useMutation({
    mutationFn: () =>
      kgApi.deploy(build.id, {
        target_id: targetId,
        mapping_profile: effectiveMapping || null,
        acknowledge_semantic_loss: acknowledged,
        requested_by: reviewer,
      }),
    onSuccess: (row) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.kgDeployments(build.id) })
      // "Deployment verified" is derived from recorded deployments, so the registry view must refresh too.
      void queryClient.invalidateQueries({ queryKey: queryKeys.graphConnections })
      if (row.status === 'completed') toast.success(`Deployed to ${row.target_name}`, { description: 'Counts verified in the target.' })
      else toast.error(`Deployment to ${row.target_name} failed`, { description: row.error ?? undefined })
    },
    onError: (error) => toast.error('Deployment refused', { description: errorMessage(error) }),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Rocket className="size-4" /> Deploy build #{build.number}
        </CardTitle>
        <CardDescription>
          Writes the build's accepted facts to a graph database through a versioned mapping profile, then verifies the
          deployment by counting what the target holds. The canonical graph and the published ontology are never changed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          <FormField label="Graph target" hint="Register Neo4j, Cosmos DB, GraphDB, Fuseki or SPARQL databases in Settings → Graph databases.">
            <GraphTargetSelect
              aria-label="Deployment target"
              value={targetId}
              onChange={(value) => {
                setTargetId(value ?? 'oxigraph-embedded')
                setAcknowledged(false)
              }}
              allowProjectDefault={false}
              data-testid="deploy-target"
            />
          </FormField>
          <FormField label="Mapping profile" hint={mappings.find((m) => m.id === effectiveMapping)?.description}>
            <NativeSelect aria-label="Mapping profile" value={effectiveMapping} onChange={(e) => setMapping(e.target.value)}>
              <option value="">Default for {model === 'rdf' ? 'RDF' : 'property graphs'}</option>
              {mappings.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id} · {m.label}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>

        {target && (
          <div className="space-y-1.5 rounded-lg border bg-muted/30 p-3 text-xs" data-testid="deploy-target-status">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{target.kind_label}</span>
              <GraphStatusBadge status={target.status} />
              {target.last_test && (
                <span className="text-muted-foreground">
                  {target.last_test.message} ({relativeTime(target.last_test.tested_at ?? '')})
                </span>
              )}
            </div>
            <GraphCapabilityChips connection={target} />
            {blockedReason && (
              <p className="text-red-700" data-testid="deploy-blocked">
                {blockedReason}
              </p>
            )}
            {!blockedReason && !internal && target.status !== 'connected' && (
              <p className="text-amber-700">
                The connection has not been verified (Settings → Test). Deploying still attempts the write; if the database is
                unreachable the failure is recorded on the deployment and nothing falls back to another store.
              </p>
            )}
            {!target.capabilities.live_tested && (
              <p className="text-amber-700">Unverified adapter: {target.capabilities.verification_note}</p>
            )}
          </div>
        )}

        {report.isPending && target && <LoadingState label="Analysing compatibility…" />}
        {report.isError && <ErrorState error={report.error} onRetry={() => report.refetch()} />}
        {report.data && <CompatibilityTable report={report.data.report} />}

        {loss && (
          <Alert variant="destructive">
            <ShieldAlert />
            <AlertDescription>
              <p>This target cannot represent part of the build's semantics (rows marked “Semantic loss”).</p>
              <label className="mt-2 flex items-center gap-2 text-foreground">
                <Checkbox
                  checked={acknowledged}
                  onCheckedChange={(value) => setAcknowledged(value === true)}
                  aria-label="Acknowledge semantic loss"
                />
                I acknowledge the loss; it will be recorded on the deployment under my name.
              </label>
            </AlertDescription>
          </Alert>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => deploy.mutate()}
            disabled={!reviewer || !target || deploy.isPending || !report.data || (loss && !acknowledged) || Boolean(blockedReason)}
            data-testid="deploy-button"
          >
            {deploy.isPending ? <Loader2 className="animate-spin" /> : <Rocket />}
            {current ? 'Re-deploy' : 'Deploy'} to {target?.name ?? 'target'}
          </Button>
          {!reviewer && <span className="text-xs text-amber-700">Enter your reviewer name (top right) to deploy.</span>}
          {current && (
            <span className="text-xs text-muted-foreground">
              A verified deployment exists ({relativeTime(current.created_at)}); re-deploying replaces this build's graphs in the
              target.
            </span>
          )}
        </div>

        {unavailable.length > 0 && (
          <details className="rounded-lg border bg-muted/30 p-3 text-xs">
            <summary className="cursor-pointer font-medium">Compatibility preview for targets without an adapter</summary>
            <p className="mt-2 text-muted-foreground">
              No adapter exists for these kinds (no server was available to build and verify one), so they cannot be deployed
              to. Their capability profiles are documented assumptions.
            </p>
            <NativeSelect
              aria-label="Preview kind"
              className="mt-2 max-w-72"
              value={previewKind}
              onChange={(e) => setPreviewKind(e.target.value)}
            >
              <option value="">Choose a target kind…</option>
              {unavailable.map((p) => (
                <option key={p.target_kind} value={p.target_kind}>
                  {p.label}
                </option>
              ))}
            </NativeSelect>
            {preview.data && (
              <div className="mt-3">
                <CompatibilityTable report={preview.data.report} />
              </div>
            )}
          </details>
        )}
      </CardContent>
    </Card>
  )
}

function DeploymentRow({
  deployment,
  onExplore,
  onQuery,
}: {
  deployment: Deployment
  onExplore: (d: Deployment) => void
  onQuery: (d: Deployment) => void
}) {
  const verified = deployment.stats.verified
  return (
    <tr className="border-t align-top" data-testid="deployment-row" data-status={deployment.status} data-kind={deployment.target_kind}>
      <td className="py-2 pr-2">
        <div className="font-medium">{deployment.target_name}</div>
        <div className="text-muted-foreground">
          {deployment.target_kind} · {deployment.mapping_profile}
        </div>
      </td>
      <td className="py-2 pr-2">
        <Badge variant="outline" className={STATUS[deployment.status].className}>
          {deployment.status === 'completed' ? <CheckCircle2 /> : deployment.status === 'failed' ? <XCircle /> : null}
          {STATUS[deployment.status].label}
        </Badge>
        {deployment.acknowledged_loss_by && (
          <div className="mt-1 flex items-center gap-1 text-red-700">
            <AlertTriangle className="size-3" /> loss acknowledged by {deployment.acknowledged_loss_by}
          </div>
        )}
      </td>
      <td className="py-2 pr-2 tabular-nums">
        {deployment.stats.vertices ?? '—'} nodes · {deployment.stats.edges ?? '—'} edges
        {deployment.stats.triples !== undefined && <div className="text-muted-foreground">{deployment.stats.triples} triples</div>}
        {verified && (
          <div className="text-muted-foreground" title="Counted in the target after writing">
            verified:{' '}
            {Object.entries(verified)
              .map(([k, v]) => `${k} ${v}`)
              .join(', ')}
          </div>
        )}
      </td>
      <td className="py-2 pr-2 text-muted-foreground">
        {relativeTime(deployment.created_at)} · {ORIGIN[deployment.origin]}
        {deployment.requested_by && <div>{deployment.requested_by}</div>}
      </td>
      <td className="py-2">
        {deployment.error && <p className="mb-1 max-w-80 text-red-700">{deployment.error}</p>}
        <div className="flex gap-1">
          {deployment.explorable && deployment.target_kind !== 'local-sql' && (
            <Button size="xs" variant="outline" onClick={() => onExplore(deployment)} data-testid="open-explorer">
              <Telescope /> Explore
            </Button>
          )}
          {deployment.queryable && (
            <Button size="xs" variant="outline" onClick={() => onQuery(deployment)} data-testid="open-query">
              <Search /> Query
            </Button>
          )}
        </div>
      </td>
    </tr>
  )
}

const EXAMPLES: { label: string; query: string }[] = [
  {
    label: 'Entities per class',
    query: 'SELECT ?class (COUNT(?entity) AS ?entities)\nWHERE { ?entity a ?class }\nGROUP BY ?class\nORDER BY DESC(?entities)',
  },
  {
    label: 'Relationships with labels',
    query:
      'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nSELECT ?subject ?predicate ?object\nWHERE {\n  ?s ?predicate ?o .\n  ?s rdfs:label ?subject .\n  ?o rdfs:label ?object .\n}\nLIMIT 50',
  },
  {
    label: 'Provenance of relationships',
    query:
      'PREFIX ols: <urn:ols:vocab#>\nSELECT ?relationship ?fact ?source\nWHERE { GRAPH ?g { ?relationship a ols:Relationship ; ols:fact ?fact ; ols:source ?source } }\nLIMIT 50',
  },
  { label: 'Any data?', query: 'ASK { ?s ?p ?o }' },
]

function termText(term: SparqlTerm | null): string {
  if (!term) return ''
  if (term.type === 'literal') return term.lang ? `"${term.value}"@${term.lang}` : term.value
  if (term.type === 'bnode') return `_:${term.value}`
  return term.value
}

function ResultsTable({ result }: { result: SparqlResult }) {
  if (result.form === 'ask') {
    return (
      <p className="text-sm" data-testid="sparql-boolean">
        Answer: <strong>{result.boolean ? 'true' : 'false'}</strong>
      </p>
    )
  }
  if (result.rows.length === 0) return <p className="text-sm text-muted-foreground">No results.</p>
  return (
    <div className="max-h-96 overflow-auto rounded-lg border">
      <table className="w-full text-xs" data-testid="sparql-results">
        <thead className="sticky top-0 bg-muted text-left">
          <tr>
            {result.variables.map((v) => (
              <th key={v} className="px-2 py-1 font-medium">
                ?{v}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, index) => (
            <tr key={index} className="border-t">
              {result.variables.map((v) => (
                <td
                  key={v}
                  className={cn('px-2 py-1 align-top break-all', row[v]?.type === 'uri' && 'font-mono text-[11px]')}
                  title={row[v]?.datatype ?? undefined}
                >
                  {termText(row[v] ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function QueryConsole({
  deployments,
  selectedId,
  onSelect,
}: {
  deployments: Deployment[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  const queryable = deployments.filter((d) => d.queryable)
  const [text, setText] = useState(EXAMPLES[0].query)
  const deployment = queryable.find((d) => d.id === selectedId) ?? queryable[0]
  const run = useMutation({ mutationFn: () => kgApi.queryDeployment(deployment!.id, text) })

  if (!deployment) {
    return (
      <EmptyState
        icon={<Database />}
        title="No queryable deployment"
        description="Deploy this build to an RDF target (embedded Oxigraph or a SPARQL endpoint) to query it with SPARQL."
      />
    )
  }
  return (
    <Card id="sparql-console">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Search className="size-4" /> SPARQL query console
        </CardTitle>
        <CardDescription>
          Read-only: SELECT, ASK, CONSTRUCT and DESCRIBE. Updates and federated SERVICE calls are rejected before the query
          reaches the store. The default graph is this build's data graph; its provenance and ontology graphs are available as
          named graphs. At most 1,000 rows are returned.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <FormField label="Deployment" className="min-w-64">
            <NativeSelect aria-label="Query deployment" value={deployment.id} onChange={(e) => onSelect(e.target.value)}>
              {queryable.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.target_name} · {relativeTime(d.created_at)}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField label="Examples" className="min-w-56">
            <NativeSelect
              aria-label="Example queries"
              value=""
              onChange={(e) => {
                const example = EXAMPLES.find((x) => x.label === e.target.value)
                if (example) setText(example.query)
              }}
            >
              <option value="">Insert an example…</option>
              {EXAMPLES.map((x) => (
                <option key={x.label} value={x.label}>
                  {x.label}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
        <Label htmlFor="sparql-text" className="sr-only">
          SPARQL query
        </Label>
        <Textarea
          id="sparql-text"
          className="min-h-36 font-mono text-xs"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run.mutate()
          }}
          spellCheck={false}
          data-testid="sparql-text"
        />
        <div className="flex items-center gap-3">
          <Button onClick={() => run.mutate()} disabled={!text.trim() || run.isPending} data-testid="sparql-run">
            {run.isPending ? <Loader2 className="animate-spin" /> : <Play />} Run query
          </Button>
          <span className="text-xs text-muted-foreground">Ctrl+Enter to run</span>
          {run.data && (
            <span className="ml-auto text-xs text-muted-foreground" data-testid="sparql-summary">
              {run.data.form.toUpperCase()} · {run.data.form === 'ask' ? 'boolean' : `${run.data.rows.length} row(s)`}
              {run.data.truncated ? ' (truncated)' : ''} · {run.data.elapsed_ms} ms · {run.data.target}
            </span>
          )}
        </div>
        {run.isError && (
          <Alert variant="destructive">
            <AlertDescription data-testid="sparql-error">{errorMessage(run.error)}</AlertDescription>
          </Alert>
        )}
        {run.data && <ResultsTable result={run.data} />}
      </CardContent>
    </Card>
  )
}

export function DeploymentsView({ build, onExplore }: { build: BuildDetail; onExplore: (deploymentId: string) => void }) {
  const deployments = useDeployments(build.id)
  const [queryId, setQueryId] = useState('')
  const rows = useMemo(() => deployments.data ?? [], [deployments.data])

  if (deployments.isPending) return <LoadingState label="Loading deployments…" />
  if (deployments.isError) return <ErrorState className="m-6" error={deployments.error} onRetry={() => deployments.refetch()} />

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <DeployPanel build={build} deployments={rows} />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="size-4" /> Deployments of build #{build.number}
          </CardTitle>
          <CardDescription>
            Every write to a graph target, with the mapping and capability profiles used, the compatibility report and the counts
            verified in the target. The local SQL property graph is the build's canonical graph.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <table className="w-full text-xs" data-testid="deployments-table">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="py-1 pr-2 font-medium">Target</th>
                <th className="py-1 pr-2 font-medium">Status</th>
                <th className="py-1 pr-2 font-medium">Content</th>
                <th className="py-1 pr-2 font-medium">When</th>
                <th className="py-1 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <DeploymentRow
                  key={d.id}
                  deployment={d}
                  onExplore={(x) => onExplore(x.id)}
                  onQuery={(x) => {
                    setQueryId(x.id)
                    document.getElementById('sparql-console')?.scrollIntoView({ behavior: 'smooth' })
                  }}
                />
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <p className="py-4 text-center text-sm text-muted-foreground">No deployments recorded.</p>}
        </CardContent>
      </Card>
      <QueryConsole deployments={rows} selectedId={queryId} onSelect={setQueryId} />
    </div>
  )
}
