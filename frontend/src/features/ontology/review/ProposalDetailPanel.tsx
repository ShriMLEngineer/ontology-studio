import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Check, ExternalLink, GitPullRequestArrow, Loader2, MessageSquare, Pencil, RotateCcw, ThumbsDown, Undo2, Wand2 } from 'lucide-react'
import { toast } from 'sonner'

import { ErrorState, LoadingState } from '@/components/common/states'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ApiError, errorMessage } from '@/lib/api/client'
import { governanceApi } from '@/lib/api/endpoints'
import type { Decision, ProposalDetail } from '@/lib/api/types'
import { dateTime, relativeTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import type { DraftDoc } from '../draft/model'
import { ProposalStatusBadge, ProposalTypeBadge } from '../governance/badges'
import { EVENT_LABEL, FIELD_LABEL, KIND_LABEL, PROPOSAL_TYPE_META } from '../governance/meta'
import type { LabelResolver } from './labels'
import { EvidenceCard, FieldValue, ImpactPanel } from './parts'
import { ProposalEditor } from './ProposalEditor'

const ADD_FIELDS = ['label', 'local_name', 'description', 'aliases', 'parent_ids', 'domain_id', 'range_id', 'datatype', 'required', 'multi_valued']

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      {children}
    </section>
  )
}

function ChangeView({ proposal, labelOf }: { proposal: ProposalDetail; labelOf: LabelResolver }) {
  if (proposal.proposal_type === 'add' && proposal.new_element) {
    const element = proposal.new_element
    return (
      <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 rounded-lg border p-3 text-sm">
        {ADD_FIELDS.filter((f) => f in element).map((field) => (
          <div key={field} className="contents">
            <dt className="text-muted-foreground">{FIELD_LABEL[field] ?? field}</dt>
            <dd>
              <FieldValue field={field} value={element[field]} labelOf={labelOf} />
            </dd>
          </div>
        ))}
      </dl>
    )
  }
  const entries = Object.entries(proposal.changes)
  if (entries.length === 0) {
    return (
      <p className="rounded-lg border bg-muted/30 p-3 text-sm">
        {proposal.proposal_type === 'reuse'
          ? `The source term "${proposal.term}" is already covered by ${KIND_LABEL[proposal.element_kind].toLowerCase()} "${proposal.target_label}". Approving records this coverage; the draft is not changed.`
          : 'No automatic change is proposed. Edit the proposal to define a resolution, or approve to acknowledge the conflict without changing the ontology.'}
      </p>
    )
  }
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">Field</th>
            <th className="px-3 py-2 font-medium">Current</th>
            <th className="px-3 py-2 font-medium">Proposed</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {entries.map(([field, change]) => (
            <tr key={field} className="align-top">
              <td className="px-3 py-2 text-muted-foreground">{FIELD_LABEL[field] ?? field}</td>
              <td className="px-3 py-2 text-red-800/80 line-through decoration-red-300">
                <FieldValue field={field} value={change.before} labelOf={labelOf} />
              </td>
              <td className="bg-emerald-50/50 px-3 py-2 text-emerald-900">
                <FieldValue field={field} value={change.after} labelOf={labelOf} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ProposalDetailPanel({
  proposalId,
  ontologyId,
  projectId,
  doc,
  reviewer,
  labelOf,
  onOpenInDesigner,
}: {
  proposalId: string
  ontologyId: string
  projectId: string
  doc: DraftDoc | undefined
  reviewer: string
  labelOf: LabelResolver
  onOpenInDesigner: (elementId: string, kind: ProposalDetail['element_kind']) => void
}) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [comment, setComment] = useState('')
  const [note, setNote] = useState('')
  const [commentError, setCommentError] = useState<string | null>(null)
  const detail = useQuery({ queryKey: queryKeys.proposal(proposalId), queryFn: () => governanceApi.get(proposalId) })

  const refresh = (updated: ProposalDetail) => {
    queryClient.setQueryData(queryKeys.proposal(proposalId), updated)
    void queryClient.invalidateQueries({ queryKey: queryKeys.proposals(ontologyId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.activity(projectId) })
  }
  const decide = useMutation({
    mutationFn: (decision: Decision) => governanceApi.decide(proposalId, decision, reviewer, comment.trim()),
    onSuccess: (updated) => {
      refresh(updated)
      setComment('')
      toast.success(`Proposal ${updated.status === 'needs_refinement' ? 'sent back for refinement' : updated.status}`)
    },
  })
  const addComment = useMutation({
    mutationFn: () => governanceApi.comment(proposalId, reviewer, note.trim()),
    onSuccess: () => {
      setNote('')
      void queryClient.invalidateQueries({ queryKey: queryKeys.proposal(proposalId) })
    },
    onError: (error) => toast.error('Comment not saved', { description: errorMessage(error) }),
  })

  if (detail.isPending) return <LoadingState label="Loading proposal…" />
  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
  const proposal = detail.data
  const status = proposal.status
  const requestDecision = (decision: Decision) => {
    if ((decision === 'reject' || decision === 'request_refinement') && !comment.trim()) {
      setCommentError('Please record a comment explaining this decision.')
      return
    }
    setCommentError(null)
    decide.mutate(decision)
  }
  const canEdit = status === 'pending' || status === 'needs_refinement'
  const decideError = decide.error instanceof ApiError ? decide.error : null
  const errorIssues = (decideError?.details.issues as { message: string }[] | undefined) ?? []
  const llmAction = proposal.alignment.llm_action
  const elementId = proposal.target_element_id ?? (proposal.new_element?.id as string | undefined)

  return (
    <div className="space-y-6 p-6" data-testid="proposal-detail" data-proposal-id={proposal.id} data-status={status}>
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <ProposalTypeBadge type={proposal.proposal_type} />
          <Badge variant="outline">{KIND_LABEL[proposal.element_kind]}</Badge>
          <ProposalStatusBadge status={status} />
          {proposal.edited && <Badge variant="secondary">Edited by SME</Badge>}
        </div>
        <h2 className="text-xl font-semibold" data-testid="proposal-title">
          {proposal.title}
        </h2>
        <p className="text-sm text-muted-foreground">
          Source term <span className="font-medium text-foreground">"{proposal.term}"</span>
          {proposal.confidence !== null && <> · model confidence {Math.round(proposal.confidence * 100)}%</>} · proposed{' '}
          {relativeTime(proposal.created_at)}
        </p>
        <p className="text-xs text-muted-foreground">{PROPOSAL_TYPE_META[proposal.proposal_type].description}</p>
      </header>

      {status === 'applied' ? (
        <Alert>
          <GitPullRequestArrow />
          <AlertTitle>Applied to draft revision {proposal.applied_draft_revision}</AlertTitle>
          <AlertDescription>The change is part of the editable draft. Publish a version in the Registry to release it.</AlertDescription>
        </Alert>
      ) : (
        proposal.impact && <ImpactPanel impact={proposal.impact} />
      )}
      {proposal.apply_error && status === 'approved' && (
        <Alert variant="destructive">
          <AlertTitle>Last apply attempt failed</AlertTitle>
          <AlertDescription>{proposal.apply_error}</AlertDescription>
        </Alert>
      )}

      {editing && doc ? (
        <ProposalEditor
          proposal={proposal}
          doc={doc}
          reviewer={reviewer}
          onCancel={() => setEditing(false)}
          onSaved={(updated) => {
            refresh(updated)
            setEditing(false)
            toast.success('Proposal updated')
          }}
        />
      ) : (
        <Section title="Proposed change">
          <ChangeView proposal={proposal} labelOf={labelOf} />
          {proposal.target && (
            <details className="text-sm">
              <summary className="cursor-pointer text-xs text-muted-foreground">Current definition of "{String(proposal.target.label)}"</summary>
              <p className="mt-2 rounded-lg bg-muted/30 p-3 whitespace-pre-wrap">{String(proposal.target.description || 'No definition.')}</p>
            </details>
          )}
          {elementId && (status === 'applied' || proposal.proposal_type !== 'add') && (
            <Button variant="link" size="sm" className="px-0" onClick={() => onOpenInDesigner(elementId, proposal.element_kind)}>
              <ExternalLink /> Show in designer
            </Button>
          )}
        </Section>
      )}

      {((proposal.alignment.notes?.length ?? 0) > 0 || (llmAction && llmAction !== proposal.proposal_type)) && (
        <Section title="Ontology alignment">
          {llmAction && llmAction !== proposal.proposal_type && (
            <p className="flex items-center gap-2 text-sm">
              <Wand2 className="size-4 text-primary" /> The model suggested
              <ProposalTypeBadge type={llmAction} /> <ArrowRight className="size-3.5" /> alignment changed it to
              <ProposalTypeBadge type={proposal.proposal_type} />
            </p>
          )}
          <ul className="list-disc space-y-1 pl-5 text-sm" data-testid="alignment-notes">
            {proposal.alignment.notes?.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
          {(proposal.alignment.matches?.length ?? 0) > 0 && (
            <p className="text-xs text-muted-foreground">
              Closest existing elements:{' '}
              {proposal.alignment.matches?.map((m) => `${m.label} (${m.match_type}, ${Math.round(m.score * 100)}%)`).join(' · ')}
            </p>
          )}
        </Section>
      )}

      {proposal.rationale && (
        <Section title="Model rationale">
          <p className="text-sm">{proposal.rationale}</p>
        </Section>
      )}

      <Section title={`Evidence (${proposal.evidence.length})`}>
        {proposal.evidence.length === 0 ? (
          <p className="text-sm text-muted-foreground">No evidence recorded.</p>
        ) : (
          proposal.evidence.map((e) => <EvidenceCard key={e.id} evidence={e} />)
        )}
      </Section>

      {status !== 'applied' && !editing && (
        <Section title="Decision">
          {!reviewer && (
            <Alert>
              <AlertDescription>Set your reviewer name (top right of the studio) to record decisions.</AlertDescription>
            </Alert>
          )}
          <Textarea
            aria-label="Decision comment"
            rows={2}
            placeholder="Comment (required to reject or request refinement)"
            value={comment}
            aria-invalid={Boolean(commentError)}
            onChange={(e) => {
              setComment(e.target.value)
              if (e.target.value.trim()) setCommentError(null)
            }}
          />
          {commentError && (
            <p className="text-sm text-destructive" role="alert">
              {commentError}
            </p>
          )}
          {decide.isError && (
            <Alert variant="destructive">
              <AlertDescription>
                {errorMessage(decide.error)}
                {errorIssues.length > 0 && (
                  <ul className="mt-1 list-disc pl-4">
                    {errorIssues.map((issue, i) => (
                      <li key={i}>{issue.message}</li>
                    ))}
                  </ul>
                )}
              </AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap gap-2">
            {(status === 'pending' || status === 'needs_refinement') && (
              <Button onClick={() => requestDecision('approve')} disabled={!reviewer || decide.isPending}>
                {decide.isPending ? <Loader2 className="animate-spin" /> : <Check />} Approve
              </Button>
            )}
            {(status === 'pending' || status === 'approved') && (
              <Button variant="outline" onClick={() => requestDecision('request_refinement')} disabled={!reviewer || decide.isPending}>
                <RotateCcw /> Request refinement
              </Button>
            )}
            {status !== 'rejected' && (
              <Button variant="destructive" onClick={() => requestDecision('reject')} disabled={!reviewer || decide.isPending}>
                <ThumbsDown /> Reject
              </Button>
            )}
            {(status === 'rejected' || status === 'approved' || status === 'needs_refinement') && (
              <Button variant="ghost" onClick={() => requestDecision('reopen')} disabled={!reviewer || decide.isPending}>
                <Undo2 /> Reopen
              </Button>
            )}
            {canEdit && (
              <Button variant="ghost" onClick={() => setEditing(true)} disabled={!doc}>
                <Pencil /> Edit
              </Button>
            )}
          </div>
        </Section>
      )}

      <Section title="Review trail">
        <ol className="space-y-3 border-l pl-4" aria-label="Review trail">
          {proposal.events.map((event) => (
            <li key={event.id} className="relative text-sm">
              <span className="absolute top-1.5 -left-[21px] size-2 rounded-full bg-primary/60" />
              <p>
                <span className="font-medium">{event.actor || 'Unknown'}</span>{' '}
                <span className="text-muted-foreground">{EVENT_LABEL[event.event_type] ?? event.event_type}</span>{' '}
                <span className="text-xs text-muted-foreground" title={dateTime(event.created_at)}>
                  · {relativeTime(event.created_at)}
                </span>
              </p>
              {event.comment && <p className="mt-0.5 rounded-md bg-muted/40 px-2 py-1">{event.comment}</p>}
            </li>
          ))}
        </ol>
        <div className="flex gap-2">
          <Textarea
            aria-label="Add a comment"
            rows={1}
            placeholder="Add a comment for other reviewers"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <Button variant="outline" onClick={() => addComment.mutate()} disabled={!reviewer || !note.trim() || addComment.isPending}>
            <MessageSquare /> Comment
          </Button>
        </div>
      </Section>
    </div>
  )
}
