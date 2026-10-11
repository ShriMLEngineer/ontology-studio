import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Info, Lightbulb, Loader2, Send } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { kgApi } from '@/lib/api/endpoints'
import type { BuildDetail, GapProposalResult, Metric, OntologyGap } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import { ProposalStatusBadge } from '@/features/ontology/governance/badges'
import { useReviewerName } from '@/features/ontology/governance/reviewer'
import { GAP_TYPE_LABEL, percent } from '../meta'

function MetricCard({ metric }: { metric: Metric }) {
  const ratio = metric.unit === 'ratio'
  return (
    <div className="rounded-lg border bg-card p-3" data-testid={`metric-${metric.key}`}>
      <p className="text-xs font-medium text-muted-foreground">{metric.label}</p>
      <p className="mt-0.5 text-xl font-semibold tabular-nums">{ratio ? percent(metric.value) : metric.value}</p>
      {metric.denominator !== null && (
        <p className="text-[11px] text-muted-foreground tabular-nums">
          {metric.numerator} / {metric.denominator}
        </p>
      )}
      <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">{metric.definition}</p>
    </div>
  )
}

function gapShape(gap: OntologyGap): string {
  const s = gap.suggestion
  if (gap.gap_type === 'unknown_relationship')
    return `${s.domain_label || s.domain_ref || '?'} → ${gap.label} → ${s.range_label || s.range_ref || '?'}`
  if (gap.gap_type === 'unknown_class') return `class ${gap.label}`
  return `${s.domain_label || s.domain_ref || '?'} · ${gap.label}${s.datatype ? ` (${s.datatype})` : ''}`
}

function gapEvidence(gap: OntologyGap): string {
  const first = gap.evidence[0]
  if (!first) return '—'
  if (first.kind === 'record') return `${first.document_name} row ${first.row_number}: ${first.raw ?? ''}`
  return `${first.document_name}${first.page ? ` p.${first.page}` : ''}: “${first.quote ?? ''}”`
}

function GapsCard({ build, projectId }: { build: BuildDetail; projectId: string }) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState(false)
  const [comment, setComment] = useState('')
  const [result, setResult] = useState<GapProposalResult | null>(null)
  const gaps = useQuery({ queryKey: queryKeys.kgGaps(build.id), queryFn: () => kgApi.gaps(build.id) })

  const propose = useMutation({
    mutationFn: () => kgApi.proposeGaps(build.id, [...selected], reviewer, comment),
    onSuccess: (created) => {
      setResult(created)
      setSelected(new Set())
      setConfirming(false)
      setComment('')
      void queryClient.invalidateQueries({ queryKey: queryKeys.kgGaps(build.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposals(build.ontology_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposalStats(build.ontology_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity(projectId) })
      toast.success(`${created.proposals.length} change proposal(s) sent to SME review`)
    },
    onError: (error) => toast.error('Could not create proposals', { description: errorMessage(error) }),
  })

  const toggle = (id: string, checked: boolean) =>
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })

  return (
    <Card size="sm" data-testid="gaps-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Lightbulb className="size-4" /> Ontology gaps and feedback
        </CardTitle>
        <CardDescription>
          Concepts in the sources that {build.ontology_name} v{build.ontology_version} cannot represent. Converting a gap creates a
          pending proposal in Ontology Studio's SME review; nothing is changed or published automatically.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {gaps.isPending ? (
          <LoadingState className="min-h-20" />
        ) : gaps.isError ? (
          <ErrorState error={gaps.error} />
        ) : gaps.data.length === 0 ? (
          <EmptyState title="No ontology gaps detected" description="Every source concept mapped to the ontology version." />
        ) : (
          <table className="w-full text-xs" data-testid="gap-table">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="w-8 py-1" />
                <th className="py-1 font-medium">Gap</th>
                <th className="py-1 font-medium">Suggested shape</th>
                <th className="py-1 pr-4 text-right font-medium">Seen</th>
                <th className="py-1 font-medium">Evidence</th>
                <th className="py-1 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {gaps.data.map((gap) => {
                const proposal = gap.proposals[gap.proposals.length - 1]
                const blocked = gap.proposals.some((p) => p.status !== 'rejected')
                return (
                  <tr key={gap.id} className="border-t align-top" data-testid="gap-row" data-gap-label={gap.label} data-gap-type={gap.gap_type}>
                    <td className="py-2">
                      <Checkbox
                        checked={selected.has(gap.id)}
                        disabled={blocked}
                        onCheckedChange={(checked) => toggle(gap.id, checked === true)}
                        aria-label={`Select gap ${gap.label}`}
                      />
                    </td>
                    <td className="py-2 pr-2">
                      <p className="font-medium">{gap.label}</p>
                      <p className="text-muted-foreground">{GAP_TYPE_LABEL[gap.gap_type]}</p>
                    </td>
                    <td className="py-2 pr-2">{gapShape(gap)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{gap.occurrences}</td>
                    <td className="max-w-xs py-2 pr-2 text-muted-foreground">
                      <span className="line-clamp-2">{gapEvidence(gap)}</span>
                      <span className="text-[10px]">{gap.origins.join(', ')}</span>
                    </td>
                    <td className="py-2">
                      {proposal ? (
                        <div className="space-y-1">
                          <ProposalStatusBadge status={proposal.status} />
                          <p className="text-[10px] text-muted-foreground">{proposal.title}</p>
                        </div>
                      ) : (
                        <Badge variant="outline">Open</Badge>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => setConfirming(true)} disabled={selected.size === 0 || !reviewer}>
            <Send /> Create change proposals ({selected.size})
          </Button>
          {!reviewer && <span className="text-xs text-amber-700">Set your reviewer name first.</span>}
          <span className="text-xs text-muted-foreground">
            Relationship gaps automatically include the unknown classes they depend on.
          </span>
        </div>
        {result && (
          <Alert data-testid="proposal-result">
            <AlertTitle>{result.proposals.length} proposal(s) awaiting SME review</AlertTitle>
            <AlertDescription className="space-y-1">
              <ul className="list-disc pl-4">
                {result.proposals.map((p) => (
                  <li key={p.id}>{p.title}</li>
                ))}
                {result.discarded.map((d) => (
                  <li key={d.term} className="text-amber-800">
                    {d.term}: {d.reason}
                  </li>
                ))}
              </ul>
              <Button variant="link" size="xs" className="px-0" asChild>
                <Link to={`/projects/${projectId}/ontology?tab=review&ontology=${build.ontology_id}`}>
                  Open SME Review in Ontology Studio <ArrowUpRight />
                </Link>
              </Button>
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send {selected.size} gap(s) to SME review?</DialogTitle>
            <DialogDescription>
              Pending ADD proposals are created for {build.ontology_name}'s draft, with the source records and quotes as evidence.
              Reviewers can edit, approve or reject them; published versions are never modified.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            aria-label="Comment for reviewers"
            placeholder="Optional comment for the reviewers"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button onClick={() => propose.mutate()} disabled={propose.isPending}>
              {propose.isPending && <Loader2 className="animate-spin" />}
              Create proposals
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

export function EvaluationView({ build, projectId }: { build: BuildDetail; projectId: string }) {
  const evaluation = useQuery({ queryKey: queryKeys.kgEvaluation(build.id), queryFn: () => kgApi.evaluation(build.id) })

  return (
    <div className="mx-auto w-full max-w-7xl space-y-5 p-6">
      {evaluation.isPending ? (
        <LoadingState />
      ) : evaluation.isError ? (
        <ErrorState error={evaluation.error} onRetry={() => evaluation.refetch()} />
      ) : (
        <>
          <Alert>
            <Info />
            <AlertTitle>How to read these indicators</AlertTitle>
            <AlertDescription>{evaluation.data.disclaimer}</AlertDescription>
          </Alert>
          {evaluation.data.sections.map((section) => (
            <section key={section.key} className="space-y-2" aria-label={section.title}>
              <h2 className="text-sm font-semibold">{section.title}</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
                {section.metrics.map((metric) => (
                  <MetricCard key={metric.key} metric={metric} />
                ))}
              </div>
            </section>
          ))}
          {evaluation.data.failure_reasons.length > 0 && (
            <section className="space-y-2" aria-label="Why facts were not accepted">
              <h2 className="text-sm font-semibold">Why facts were rejected or quarantined</h2>
              <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="failure-reasons">
                {evaluation.data.failure_reasons.map((reason) => (
                  <li key={reason.code} className="flex items-center justify-between rounded-lg border px-3 py-2 text-xs">
                    <span>{reason.label}</span>
                    <span className="font-semibold tabular-nums">{reason.count}</span>
                  </li>
                ))}
              </ul>
              <p className="text-[11px] text-muted-foreground">Counts are failed checks; one fact can fail several checks.</p>
            </section>
          )}
        </>
      )}
      <GapsCard build={build} projectId={projectId} />
    </div>
  )
}
