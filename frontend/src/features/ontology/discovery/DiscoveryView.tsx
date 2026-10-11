import { useEffect, useRef, useState, type DragEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  FileText,
  Loader2,
  PlayCircle,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from 'cn'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { discoveryApi, registryApi, sourcesApi, systemApi } from '@/lib/api/endpoints'
import type { DiscoveryRun, ProposalType, SourceDocument } from '@/lib/api/types'
import { dateTime, plural, relativeTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import { ProposalTypeBadge } from '../governance/badges'
import { useReviewerName } from '../governance/reviewer'

const ACCEPT = '.txt,.md,.markdown,.csv,.tsv,.json,.pdf'
const DRAFT_BASELINE = 'draft'

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return now
}

function duration(fromIso: string | null, to: number): string {
  if (!fromIso) return '0s'
  const seconds = Math.max(0, Math.round((to - new Date(fromIso).getTime()) / 1000))
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function ProviderCard() {
  const status = useQuery({
    queryKey: queryKeys.llmStatus,
    queryFn: () => systemApi.llmStatus(true),
    staleTime: 60_000,
    retry: false,
  })
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bot className="size-4" /> AI provider
        </CardTitle>
        <CardAction>
          <Button variant="ghost" size="icon-sm" aria-label="Re-check provider" onClick={() => status.refetch()}>
            <RefreshCw className={cn(status.isFetching && 'animate-spin')} />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {status.isPending ? (
          <LoadingState label="Checking provider…" className="min-h-12" />
        ) : status.isError ? (
          <p className="text-destructive">{errorMessage(status.error)}</p>
        ) : !status.data.configured ? (
          <Alert>
            <AlertTriangle />
            <AlertTitle>AI discovery is disabled</AlertTitle>
            <AlertDescription>{status.data.detail}</AlertDescription>
          </Alert>
        ) : (
          <>
            <div className="flex items-center gap-2">
              {status.data.reachable ? (
                <CheckCircle2 className="size-4 text-emerald-600" />
              ) : (
                <XCircle className="size-4 text-red-600" />
              )}
              <span className="font-medium">{status.data.model}</span>
              <span className="text-muted-foreground">via {status.data.endpoint_host}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              {status.data.detail} · structured output: {status.data.structured_output}. Results are suggestions only;
              every proposal requires SME approval.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function SourcesCard({
  projectId,
  selected,
  onToggle,
  onUploaded,
}: {
  projectId: string
  selected: Set<string>
  onToggle: (id: string, checked: boolean) => void
  onUploaded: (document: SourceDocument) => void
}) {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [deleting, setDeleting] = useState<SourceDocument | null>(null)
  const [reviewer] = useReviewerName()
  const sources = useQuery({ queryKey: queryKeys.sources(projectId), queryFn: () => sourcesApi.list(projectId) })

  const upload = useMutation({
    mutationFn: (file: File) => sourcesApi.upload(projectId, file, reviewer),
    onSuccess: (document) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity(projectId) })
      toast.success(`Uploaded ${document.filename}`, { description: `${plural(document.chunk_count, 'chunk')} ready for analysis` })
      onUploaded(document)
    },
    onError: (error) => toast.error('Upload failed', { description: errorMessage(error) }),
  })
  const remove = useMutation({
    mutationFn: (id: string) => sourcesApi.remove(id),
    onSuccess: (_, id) => {
      onToggle(id, false)
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources(projectId) })
    },
    onError: (error) => toast.error('Could not delete document', { description: errorMessage(error) }),
  })

  const handleFiles = (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) upload.mutate(file)
  }
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    handleFiles(event.dataTransfer.files)
  }

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileText className="size-4" /> Source documents
        </CardTitle>
        <CardDescription>PDF, Markdown, text, CSV or JSON - up to 10 MB each.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload source documents"
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'flex cursor-pointer flex-col items-center gap-1 rounded-lg border border-dashed px-4 py-5 text-center text-sm transition-colors hover:bg-muted/50',
            dragging && 'border-primary bg-primary/5',
          )}
        >
          {upload.isPending ? <Loader2 className="size-5 animate-spin text-primary" /> : <Upload className="size-5 text-muted-foreground" />}
          <span className="font-medium">{upload.isPending ? 'Uploading and extracting text…' : 'Drop files or click to upload'}</span>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            multiple
            className="hidden"
            data-testid="source-upload-input"
            onChange={(e) => {
              handleFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </div>

        {sources.isPending ? (
          <LoadingState className="min-h-16" />
        ) : sources.isError ? (
          <ErrorState error={sources.error} onRetry={() => sources.refetch()} />
        ) : sources.data.length === 0 ? (
          <p className="text-center text-xs text-muted-foreground">No documents uploaded for this project yet.</p>
        ) : (
          <ul className="divide-y rounded-lg border" aria-label="Source documents">
            {sources.data.map((doc) => (
              <li key={doc.id} className="flex items-center gap-3 px-3 py-2">
                <Checkbox
                  id={`doc-${doc.id}`}
                  checked={selected.has(doc.id)}
                  onCheckedChange={(checked) => onToggle(doc.id, checked === true)}
                  aria-label={`Use ${doc.filename}`}
                />
                <label htmlFor={`doc-${doc.id}`} className="min-w-0 flex-1 cursor-pointer">
                  <p className="truncate text-sm font-medium">{doc.filename}</p>
                  <p className="text-xs text-muted-foreground">
                    {fileSize(doc.size_bytes)} · {doc.page_count ? `${plural(doc.page_count, 'page')} · ` : ''}
                    {plural(doc.chunk_count, 'chunk')} · {relativeTime(doc.created_at)}
                  </p>
                </label>
                <Button variant="ghost" size="icon-xs" aria-label={`Delete ${doc.filename}`} onClick={() => setDeleting(doc)}>
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete "{deleting?.filename}"?</AlertDialogTitle>
            <AlertDialogDescription>
              The document is removed from the project. Evidence quotes already attached to proposals are retained.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => deleting && remove.mutate(deleting.id)}>
              Delete document
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

function RunCard({ run, onReview }: { run: DiscoveryRun; onReview: (runId: string) => void }) {
  const active = run.status === 'queued' || run.status === 'running'
  const now = useNow(active)
  const total = run.progress.total_batches ?? 0
  const done = run.progress.completed_batches ?? 0
  const byType = Object.entries(run.stats.by_type ?? {}) as [ProposalType, number][]

  return (
    <li className="rounded-xl border bg-card p-4" data-testid="discovery-run" data-status={run.status}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="mt-0.5">
          {active ? (
            <Loader2 className="size-5 animate-spin text-primary" />
          ) : run.status === 'completed' ? (
            <CheckCircle2 className="size-5 text-emerald-600" />
          ) : (
            <XCircle className="size-5 text-red-600" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {run.status === 'queued'
              ? 'Queued'
              : run.status === 'running'
                ? `Analysing… batch ${Math.min(done + 1, Math.max(total, 1))} of ${Math.max(total, 1)}`
                : run.status === 'completed'
                  ? `${plural(run.stats.proposals ?? 0, 'proposal')} for review`
                  : 'Discovery failed'}
          </p>
          <p className="text-xs text-muted-foreground">
            {run.documents.map((d) => d.filename ?? 'deleted document').join(', ')} · against {run.baseline_label} ·{' '}
            {run.model}
            {run.requested_by ? ` · by ${run.requested_by}` : ''}
          </p>
          <p className="text-xs text-muted-foreground" title={dateTime(run.created_at)}>
            Started {relativeTime(run.created_at)}
            {active
              ? ` · running for ${duration(run.started_at ?? run.created_at, now)}`
              : run.completed_at
                ? ` · took ${duration(run.started_at ?? run.created_at, new Date(run.completed_at).getTime())}`
                : ''}
            {run.usage.prompt_tokens ? ` · ${run.usage.prompt_tokens + (run.usage.completion_tokens ?? 0)} tokens` : ''}
          </p>
        </div>
        {run.status === 'completed' && (run.stats.proposals ?? 0) > 0 && (
          <Button size="sm" onClick={() => onReview(run.id)}>
            Review proposals <ChevronRight />
          </Button>
        )}
      </div>

      {active && total > 0 && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={done} aria-valuemax={total}>
          <div className="h-full bg-primary transition-all" style={{ width: `${Math.max(5, (done / total) * 100)}%` }} />
        </div>
      )}
      {active && (
        <p className="mt-2 text-xs text-muted-foreground">
          Local models can take several minutes per batch. You can keep working; this list updates automatically.
        </p>
      )}
      {run.status === 'failed' && run.error && (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      )}
      {run.status === 'completed' && (
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {byType.map(([type, count]) => (
              <span key={type} className="flex items-center gap-1 text-xs">
                <ProposalTypeBadge type={type} /> {count}
              </span>
            ))}
            {(run.stats.failed_batches ?? 0) > 0 && (
              <Badge variant="outline" className="border-amber-300 text-amber-800">
                {plural(run.stats.failed_batches ?? 0, 'batch', 'batches')} returned invalid output
              </Badge>
            )}
          </div>
          {run.discarded.length > 0 && (
            <details className="rounded-lg bg-muted/40 px-3 py-2 text-xs">
              <summary className="cursor-pointer font-medium">
                {plural(run.discarded.length, 'finding')} discarded by grounding or alignment
              </summary>
              <ul className="mt-2 space-y-1.5">
                {run.discarded.map((d, i) => (
                  <li key={i}>
                    <span className="font-medium">{d.term}</span>{' '}
                    <span className="text-muted-foreground">
                      ({d.action} {d.element_kind.replace('_', ' ')})
                    </span>
                    : {d.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </li>
  )
}

export function DiscoveryView({
  projectId,
  ontologyId,
  draftRevision,
  onReviewRun,
}: {
  projectId: string
  ontologyId: string
  draftRevision: number | undefined
  onReviewRun: (runId: string) => void
}) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [baseline, setBaseline] = useState(DRAFT_BASELINE)
  const [instructions, setInstructions] = useState('')

  const llm = useQuery({ queryKey: queryKeys.llmStatus, queryFn: () => systemApi.llmStatus(true), staleTime: 60_000, retry: false })
  const versions = useQuery({ queryKey: queryKeys.versions(ontologyId), queryFn: () => registryApi.versions(ontologyId) })
  const runs = useQuery({
    queryKey: queryKeys.discoveryRuns(ontologyId),
    queryFn: () => discoveryApi.list(ontologyId),
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === 'queued' || r.status === 'running') ? 2000 : false,
  })

  const previous = useRef<Map<string, string>>(new Map())
  useEffect(() => {
    if (!runs.data) return
    for (const run of runs.data) {
      const before = previous.current.get(run.id)
      if (before && before !== run.status && (run.status === 'completed' || run.status === 'failed')) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.proposals(ontologyId) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.proposalStats(ontologyId) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.activity(projectId) })
        if (run.status === 'completed') toast.success('AI discovery finished', { description: `${plural(run.stats.proposals ?? 0, 'proposal')} ready for SME review` })
        else toast.error('AI discovery failed', { description: run.error ?? undefined })
      }
      previous.current.set(run.id, run.status)
    }
  }, [runs.data, queryClient, ontologyId, projectId])

  const activeRun = runs.data?.find((r) => r.status === 'queued' || r.status === 'running')
  const start = useMutation({
    mutationFn: () =>
      discoveryApi.start(ontologyId, {
        document_ids: [...selected],
        baseline_version_id: baseline === DRAFT_BASELINE ? null : baseline,
        instructions,
        requested_by: reviewer,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.discoveryRuns(ontologyId) })
      toast.info('Discovery started', { description: 'The model is analysing the selected documents.' })
    },
  })

  const toggle = (id: string, checked: boolean) =>
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })

  const disabledReason = !llm.data?.configured
    ? 'Configure an LLM provider to enable discovery.'
    : selected.size === 0
      ? 'Select at least one source document.'
      : activeRun
        ? 'A discovery run is already in progress.'
        : null

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-6 p-6 lg:grid-cols-[400px_1fr]">
      <div className="space-y-4">
        <ProviderCard />
        <SourcesCard projectId={projectId} selected={selected} onToggle={toggle} onUploaded={(doc) => toggle(doc.id, true)} />
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="size-4" /> New discovery run
            </CardTitle>
            <CardDescription>The model compares the documents with the ontology and proposes changes with evidence.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-1.5">
              <Label htmlFor="discovery-baseline" className="text-xs">
                Compare against
              </Label>
              <Select value={baseline} onValueChange={setBaseline}>
                <SelectTrigger id="discovery-baseline" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DRAFT_BASELINE}>Current draft{draftRevision ? ` (revision ${draftRevision})` : ''}</SelectItem>
                  {versions.data?.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      Published version {v.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">Approved proposals are always applied to the editable draft.</p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="discovery-focus" className="text-xs">
                SME focus (optional)
              </Label>
              <Textarea
                id="discovery-focus"
                rows={2}
                value={instructions}
                placeholder="e.g. Focus on quality management concepts"
                onChange={(e) => setInstructions(e.target.value)}
              />
            </div>
            {start.isError && (
              <Alert variant="destructive">
                <AlertDescription>{errorMessage(start.error)}</AlertDescription>
              </Alert>
            )}
            <Button className="w-full" onClick={() => start.mutate()} disabled={Boolean(disabledReason) || start.isPending}>
              {start.isPending ? <Loader2 className="animate-spin" /> : <PlayCircle />}
              Analyse {selected.size ? plural(selected.size, 'document') : 'documents'}
            </Button>
            {disabledReason && <p className="text-center text-xs text-muted-foreground">{disabledReason}</p>}
          </CardContent>
        </Card>
      </div>

      <section className="min-w-0 space-y-3" aria-label="Discovery runs">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Discovery runs</h2>
          {runs.isFetching && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
        </div>
        {runs.isPending ? (
          <LoadingState />
        ) : runs.isError ? (
          <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
        ) : runs.data.length === 0 ? (
          <EmptyState
            icon={<Sparkles />}
            title="No discovery runs yet"
            description="Upload source documents, select them and start a run. Proposals appear in SME Review."
          />
        ) : (
          <ul className="space-y-3">
            {runs.data.map((run) => (
              <RunCard key={run.id} run={run} onReview={onReviewRun} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
