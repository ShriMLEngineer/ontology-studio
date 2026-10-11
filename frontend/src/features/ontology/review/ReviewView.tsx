import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GitMerge, Inbox, Loader2, Search, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from 'cn'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { errorMessage } from '@/lib/api/client'
import { governanceApi } from '@/lib/api/endpoints'
import type { ProposalDetail, ProposalStatus, ProposalSummary, ProposalType } from '@/lib/api/types'
import { plural, relativeTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import type { DraftEditor } from '../draft/useDraftEditor'
import { ProposalStatusBadge, ProposalTypeBadge } from '../governance/badges'
import { KIND_LABEL, PROPOSAL_TYPE_META } from '../governance/meta'
import { useReviewerName } from '../governance/reviewer'
import { describeChanges } from '../designer/presentation'
import { makeLabelResolver } from './labels'
import { ProposalDetailPanel } from './ProposalDetailPanel'

type StatusFilter = 'review' | ProposalStatus | 'all'

const STATUS_FILTERS: { value: StatusFilter; label: string; matches: (s: ProposalStatus) => boolean }[] = [
  { value: 'review', label: 'Awaiting review', matches: (s) => s === 'pending' || s === 'needs_refinement' },
  { value: 'approved', label: 'Approved', matches: (s) => s === 'approved' },
  { value: 'applied', label: 'Applied', matches: (s) => s === 'applied' },
  { value: 'rejected', label: 'Rejected', matches: (s) => s === 'rejected' },
  { value: 'all', label: 'All', matches: () => true },
]

export function ReviewView({
  projectId,
  ontologyId,
  editor,
  runFilter,
  onClearRunFilter,
  onOpenInDesigner,
}: {
  projectId: string
  ontologyId: string
  editor: DraftEditor
  runFilter: string | null
  onClearRunFilter: () => void
  onOpenInDesigner: (elementId: string, kind: ProposalDetail['element_kind']) => void
}) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const [status, setStatus] = useState<StatusFilter>('review')
  const [type, setType] = useState<ProposalType | 'all'>('all')
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const proposals = useQuery({ queryKey: queryKeys.proposals(ontologyId), queryFn: () => governanceApi.list(ontologyId) })
  const labelOf = useMemo(() => makeLabelResolver(editor.doc, proposals.data), [editor.doc, proposals.data])

  const statusFilter = STATUS_FILTERS.find((f) => f.value === status)!
  const q = search.trim().toLowerCase()
  const visible = (proposals.data ?? []).filter(
    (p) =>
      statusFilter.matches(p.status) &&
      (type === 'all' || p.proposal_type === type) &&
      (!runFilter || p.run_id === runFilter) &&
      (!q || p.title.toLowerCase().includes(q) || p.term.toLowerCase().includes(q)),
  )
  const selected = visible.find((p) => p.id === selectedId) ?? visible[0]
  const approved = (proposals.data ?? []).filter((p) => p.status === 'approved')
  const counts = (filter: (typeof STATUS_FILTERS)[number]) => (proposals.data ?? []).filter((p) => filter.matches(p.status)).length

  const apply = useMutation({
    mutationFn: () => governanceApi.apply(ontologyId, reviewer),
    onSuccess: (result) => {
      for (const key of [
        queryKeys.proposals(ontologyId),
        queryKeys.proposalStats(ontologyId),
        queryKeys.draft(ontologyId),
        queryKeys.ontologies(projectId),
        queryKeys.activity(projectId),
        queryKeys.latestValidation(ontologyId),
        queryKeys.publishPreview(ontologyId),
        ['proposals'],
      ]) {
        void queryClient.invalidateQueries({ queryKey: key })
      }
      if (result.applied.length) {
        toast.success(
          result.revision_incremented
            ? `Applied ${plural(result.applied.length, 'proposal')} - draft revision ${result.draft_revision}`
            : `Recorded ${plural(result.applied.length, 'proposal')} (no draft change)`,
          { description: describeChanges(result.changes) },
        )
      }
      for (const failure of result.failed) toast.error(`Not applied: ${failure.title}`, { description: failure.reason })
    },
    onError: (error) => toast.error('Apply failed', { description: errorMessage(error) }),
  })

  const applyBlocked = !reviewer
    ? 'Set your reviewer name first.'
    : editor.dirty
      ? 'Save or discard your unsaved designer changes first.'
      : approved.length === 0
        ? 'Approve proposals to apply them.'
        : null

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b bg-background px-6 py-3">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Status filter">
          {STATUS_FILTERS.map((filter) => (
            <Button
              key={filter.value}
              size="sm"
              variant={status === filter.value ? 'secondary' : 'ghost'}
              aria-pressed={status === filter.value}
              onClick={() => setStatus(filter.value)}
            >
              {filter.label}
              <span className="text-xs text-muted-foreground tabular-nums">{counts(filter)}</span>
            </Button>
          ))}
        </div>
        <Select value={type} onValueChange={(v) => setType(v as ProposalType | 'all')}>
          <SelectTrigger size="sm" className="w-36" aria-label="Proposal type filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            {(Object.keys(PROPOSAL_TYPE_META) as ProposalType[]).map((t) => (
              <SelectItem key={t} value={t}>
                {PROPOSAL_TYPE_META[t].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {runFilter && (
          <Badge variant="secondary" className="gap-1 pr-1">
            From one discovery run
            <button type="button" aria-label="Clear run filter" className="rounded-full p-0.5 hover:bg-foreground/10" onClick={onClearRunFilter}>
              <X className="size-3" />
            </button>
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <Button onClick={() => apply.mutate()} disabled={Boolean(applyBlocked) || apply.isPending}>
                  {apply.isPending ? <Loader2 className="animate-spin" /> : <GitMerge />}
                  Apply {approved.length || ''} approved to draft
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>{applyBlocked ?? 'Apply approved proposals to the editable draft (never to a published version)'}</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {proposals.isPending ? (
        <LoadingState />
      ) : proposals.isError ? (
        <ErrorState className="m-6" error={proposals.error} onRetry={() => proposals.refetch()} />
      ) : proposals.data.length === 0 ? (
        <EmptyState
          className="m-6"
          icon={<Inbox />}
          title="No proposals yet"
          description="Run AI discovery on source documents, or send ontology gaps from a knowledge graph build, to create change proposals for review."
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <aside className="flex w-[380px] shrink-0 flex-col border-r bg-background" aria-label="Proposals">
            <div className="border-b p-3">
              <div className="relative">
                <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="h-8 pl-8 text-xs"
                  placeholder="Search proposals"
                  aria-label="Search proposals"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
            <ul className="flex-1 overflow-y-auto" data-testid="proposal-list">
              {visible.length === 0 && <li className="p-6 text-center text-sm text-muted-foreground">No proposals match.</li>}
              {visible.map((p: ProposalSummary) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(p.id)}
                    className={cn(
                      'flex w-full flex-col gap-1.5 border-b px-4 py-3 text-left hover:bg-muted/50',
                      selected?.id === p.id && 'bg-primary/5 shadow-[inset_3px_0_0_var(--primary)]',
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      <ProposalTypeBadge type={p.proposal_type} />
                      <span className="text-xs text-muted-foreground">{KIND_LABEL[p.element_kind]}</span>
                      {p.origin === 'kg_build' && (
                        <span className="rounded bg-violet-100 px-1.5 text-[10px] font-medium text-violet-800" data-testid="origin-kg">
                          KG feedback
                        </span>
                      )}
                      <span className="ml-auto">
                        <ProposalStatusBadge status={p.status} />
                      </span>
                    </span>
                    <span className="text-sm font-medium">{p.title}</span>
                    <span className="text-xs text-muted-foreground">
                      "{p.term}" · {plural(p.evidence_count, 'quote')}
                      {p.confidence !== null && ` · ${Math.round(p.confidence * 100)}%`} · {relativeTime(p.updated_at)}
                      {p.apply_error && <span className="text-red-600"> · apply failed</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          <div className="min-w-0 flex-1 overflow-y-auto bg-background">
            {selected ? (
              <ProposalDetailPanel
                key={selected.id}
                proposalId={selected.id}
                ontologyId={ontologyId}
                projectId={projectId}
                doc={editor.doc}
                reviewer={reviewer}
                labelOf={labelOf}
                onOpenInDesigner={onOpenInDesigner}
              />
            ) : (
              <EmptyState className="m-6" title="Select a proposal" description="Choose a proposal to review its evidence and impact." />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
