import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Download,
  FileCode2,
  FileUp,
  Loader2,
  Lock,
  Trash2,
  Unplug,
} from 'lucide-react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { errorMessage } from '@/lib/api/client'
import { semanticsApi } from '@/lib/api/endpoints'
import type { ExtensionAxiomRead, ImportReport, RdfFormat } from '@/lib/api/types'
import { dateTime, plural } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import type { DraftDoc } from '../draft/model'
import type { DraftEditor } from '../draft/useDraftEditor'
import { useReviewerName } from '../governance/reviewer'
import { RDF_FORMATS } from './formats'

const PREVIEW_LINES = 400

function elementLabel(doc: DraftDoc | undefined, id: string): string {
  if (!doc) return id
  const element =
    doc.classes.find((c) => c.id === id) ??
    doc.object_properties.find((p) => p.id === id) ??
    doc.datatype_properties.find((p) => p.id === id)
  return element?.label ?? id
}

// ------------------------------------------------------------------------------------ export

function ExportCard({ ontologyId, editor }: { ontologyId: string; editor: DraftEditor }) {
  const [format, setFormat] = useState<RdfFormat>('turtle')
  const revision = editor.base?.draft_revision ?? 0
  const rdf = useQuery({
    queryKey: queryKeys.draftRdf(ontologyId, format, revision),
    queryFn: () => semanticsApi.draftRdf(ontologyId, format),
  })
  const lines = rdf.data?.split('\n') ?? []
  return (
    <Card data-testid="rdf-export-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileCode2 className="size-4" /> OWL export of the draft
        </CardTitle>
        <CardDescription>
          Generated from saved revision r{revision}: the OLS Semantic Profile plus preserved axioms. The required and
          single-value switches are data constraints (SHACL), not OWL axioms.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {editor.dirty && (
          <Alert>
            <AlertTriangle />
            <AlertDescription>Unsaved designer changes are not included until you save the draft.</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Select value={format} onValueChange={(v) => setFormat(v as RdfFormat)}>
            <SelectTrigger className="w-36" aria-label="Preview format">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RDF_FORMATS.map((f) => (
                <SelectItem key={f.value} value={f.value}>
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {RDF_FORMATS.map((f) => (
            <Button key={f.value} variant="outline" size="xs" asChild>
              <a href={semanticsApi.draftRdfUrl(ontologyId, f.value)} data-testid={`download-${f.value}`}>
                <Download /> {f.label}
              </a>
            </Button>
          ))}
        </div>
        {rdf.isPending ? (
          <LoadingState className="min-h-32" label="Serialising…" />
        ) : rdf.isError ? (
          <ErrorState error={rdf.error} onRetry={() => rdf.refetch()} />
        ) : (
          <>
            <pre
              className="max-h-[420px] overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed"
              data-testid="rdf-preview"
            >
              {lines.slice(0, PREVIEW_LINES).join('\n')}
            </pre>
            {lines.length > PREVIEW_LINES && (
              <p className="text-xs text-muted-foreground">
                Showing the first {PREVIEW_LINES} of {lines.length} lines. Download the file for the full document.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------------------------ import

export function ImportReportView({ report }: { report: ImportReport }) {
  return (
    <div className="space-y-3 text-sm" data-testid="import-report">
      <div className="flex flex-wrap items-center gap-2">
        {report.lossless ? (
          <Badge className="gap-1 bg-emerald-600">
            <CheckCircle2 className="size-3" /> No semantic loss
          </Badge>
        ) : (
          <Badge variant="destructive">Lossy</Badge>
        )}
        <Badge variant="outline">{report.rdf_format}</Badge>
        <span className="text-xs text-muted-foreground">{plural(report.source_triples, 'source triple')}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">Modelled</dt>
          <dd className="font-medium">{report.consumed_triples} triples</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Preserved</dt>
          <dd className="font-medium">
            {report.preserved_triples} triples · {plural(report.preserved_axioms, 'axiom')}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Superseded</dt>
          <dd className="font-medium">{report.superseded_triples} triples</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Added on export</dt>
          <dd className="font-medium">{report.added_triples} triples</dd>
        </div>
      </dl>
      <p className="text-xs text-muted-foreground">
        {plural(report.classes, 'class', 'classes')}, {plural(report.object_properties, 'relationship')},{' '}
        {plural(report.datatype_properties, 'attribute')} modelled.
      </p>
      {Object.keys(report.preserved_by_kind).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(report.preserved_by_kind).map(([kind, count]) => (
            <Badge key={kind} variant="secondary" className="font-normal">
              {kind}: {count}
            </Badge>
          ))}
        </div>
      )}
      {report.warnings.length > 0 && (
        <Alert>
          <AlertTriangle />
          <AlertTitle>Review before publishing</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {report.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {report.superseded.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            Superseded at publication ({report.superseded.length}): version header triples are replaced by the registry
          </summary>
          <pre className="mt-1 overflow-auto rounded border bg-muted/40 p-2 font-mono text-[10px]">{report.superseded.join('\n')}</pre>
        </details>
      )}
      {report.added.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            Added bookkeeping ({report.added_triples}): identifiers, rdfs:isDefinedBy, generated labels
          </summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded border bg-muted/40 p-2 font-mono text-[10px]">
            {report.added.join('\n')}
          </pre>
        </details>
      )}
    </div>
  )
}

function ImportCard({ projectId, ontologyId }: { projectId: string; ontologyId: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [reviewer] = useReviewerName()
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [format, setFormat] = useState<RdfFormat | 'auto'>('auto')
  const [name, setName] = useState('')
  const [namespace, setNamespace] = useState('')
  const [prefix, setPrefix] = useState('')
  const history = useQuery({ queryKey: queryKeys.imports(ontologyId), queryFn: () => semanticsApi.imports(ontologyId) })

  const importRdf = useMutation({
    mutationFn: () =>
      semanticsApi.importRdf(projectId, file!, {
        rdfFormat: format === 'auto' ? '' : format,
        name: name.trim(),
        namespace: namespace.trim(),
        prefix: prefix.trim(),
        importedBy: reviewer,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ontologies(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity(projectId) })
      const report = result.import_record.report
      toast.success(`Imported '${result.ontology.name}'`, {
        description: `${report.consumed_triples} triples modelled, ${plural(report.preserved_axioms, 'preserved axiom')}.`,
      })
    },
  })
  const result = importRdf.data

  return (
    <Card data-testid="rdf-import-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileUp className="size-4" /> Import RDF / OWL
        </CardTitle>
        <CardDescription>
          Creates a new ontology draft in this project. Constructs outside the supported profile are preserved verbatim as
          axioms; nothing is discarded.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-[1fr_150px]">
          <div className="grid gap-1.5">
            <Label htmlFor="rdf-file" className="text-xs">
              RDF document
            </Label>
            <Input
              id="rdf-file"
              ref={fileRef}
              type="file"
              accept=".ttl,.rdf,.owl,.xml,.jsonld,.json,.nt"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                importRdf.reset()
              }}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="rdf-format" className="text-xs">
              Format
            </Label>
            <Select value={format} onValueChange={(v) => setFormat(v as RdfFormat | 'auto')}>
              <SelectTrigger id="rdf-format" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">From file name</SelectItem>
                {RDF_FORMATS.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">Override name, namespace or prefix (optional)</summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            <Input aria-label="Ontology name" placeholder="Name from rdfs:label" value={name} onChange={(e) => setName(e.target.value)} />
            <Input
              aria-label="Namespace"
              className="font-mono text-xs"
              placeholder="Most common namespace"
              value={namespace}
              onChange={(e) => setNamespace(e.target.value)}
            />
            <Input aria-label="Prefix" className="font-mono" placeholder="Declared prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)} />
          </div>
        </details>
        {importRdf.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(importRdf.error)}</AlertDescription>
          </Alert>
        )}
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            {reviewer ? `Recorded as imported by ${reviewer}.` : 'Set your reviewer name to import.'}
          </p>
          <Button onClick={() => importRdf.mutate()} disabled={!file || !reviewer || importRdf.isPending}>
            {importRdf.isPending ? <Loader2 className="animate-spin" /> : <FileUp />}
            Import as new ontology
          </Button>
        </div>
        {result && (
          <div className="space-y-3 rounded-lg border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">'{result.ontology.name}' created</p>
              <Button
                size="sm"
                onClick={() => {
                  if (fileRef.current) fileRef.current.value = ''
                  setFile(null)
                  void navigate(`/projects/${projectId}/ontology?ontology=${result.ontology.id}&tab=semantics`)
                }}
              >
                Open imported ontology
              </Button>
            </div>
            <ImportReportView report={result.import_record.report} />
          </div>
        )}
        {history.data && history.data.length > 0 && (
          <div className="space-y-2 border-t pt-3">
            <p className="text-xs font-medium">Import history of this ontology</p>
            {history.data.map((record) => (
              <details key={record.id} className="rounded-lg border p-2 text-xs" data-testid="import-history-row">
                <summary className="cursor-pointer">
                  {record.filename} · {record.imported_by || 'unknown'} · {dateTime(record.created_at)}
                </summary>
                <div className="mt-2">
                  <p className="mb-2 font-mono text-[10px] text-muted-foreground">sha256 {record.sha256}</p>
                  <ImportReportView report={record.report} />
                </div>
              </details>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------------------------ preserved axioms

function AxiomsCard({ ontologyId, editor }: { ontologyId: string; editor: DraftEditor }) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const [pending, setPending] = useState<ExtensionAxiomRead | null>(null)
  const axioms = useQuery({ queryKey: queryKeys.axioms(ontologyId), queryFn: () => semanticsApi.axioms(ontologyId) })
  const remove = useMutation({
    mutationFn: (axiom: ExtensionAxiomRead) => semanticsApi.deleteAxiom(ontologyId, axiom.id, reviewer),
    onSuccess: () => {
      toast.success('Preserved axiom removed', { description: 'The draft revision was incremented and the removal is audited.' })
      void queryClient.invalidateQueries({ queryKey: ['ontologies', ontologyId] })
      void editor.reload()
    },
    onError: (error) => toast.error('Could not remove the axiom', { description: errorMessage(error) }),
    onSettled: () => setPending(null),
  })
  const disabledReason = !reviewer
    ? 'Set your reviewer name first.'
    : editor.dirty
      ? 'Save or discard designer changes first.'
      : null

  return (
    <Card data-testid="axioms-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Lock className="size-4" /> Preserved axioms
        </CardTitle>
        <CardDescription>
          Imported triples outside the OLS Semantic Profile, kept verbatim and re-exported unchanged. An axiom that refers
          to a deleted element blocks publication until it is resolved.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {axioms.isPending ? (
          <LoadingState className="min-h-20" />
        ) : axioms.isError ? (
          <ErrorState error={axioms.error} onRetry={() => axioms.refetch()} />
        ) : axioms.data.length === 0 ? (
          <EmptyState
            icon={<Lock />}
            title="No preserved axioms"
            description="Everything in this ontology is represented by the typed model."
          />
        ) : (
          <ul className="space-y-2" aria-label="Preserved axioms">
            {axioms.data.map((axiom) => (
              <li key={axiom.id} className="rounded-lg border p-2.5 text-sm" data-testid="axiom-row">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline" className="text-[10px]">
                    {axiom.scope === 'shapes' ? 'SHACL' : 'OWL/RDF'}
                  </Badge>
                  <Badge variant="secondary" className="text-[10px] font-normal">
                    {axiom.kind}
                  </Badge>
                  {axiom.orphaned && (
                    <Badge variant="destructive" className="gap-1 text-[10px]">
                      <Unplug className="size-3" /> Orphaned
                    </Badge>
                  )}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="ml-auto"
                    aria-label={`Remove axiom ${axiom.summary}`}
                    title={disabledReason ?? 'Remove this preserved axiom'}
                    disabled={Boolean(disabledReason)}
                    onClick={() => setPending(axiom)}
                  >
                    <Trash2 />
                  </Button>
                </div>
                <p className="mt-1 font-mono text-xs break-all">{axiom.summary}</p>
                {axiom.anchor_ids.length > 0 && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    About:{' '}
                    {axiom.anchor_ids.map((id, i) => (
                      <span key={id} className={axiom.missing_anchor_ids.includes(id) ? 'text-red-700 line-through' : undefined}>
                        {i > 0 && ', '}
                        {elementLabel(editor.doc, id)}
                      </span>
                    ))}
                  </p>
                )}
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-muted-foreground">N-Triples</summary>
                  <pre className="mt-1 overflow-auto rounded border bg-muted/40 p-2 font-mono text-[10px]">{axiom.ntriples}</pre>
                </details>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <AlertDialog open={Boolean(pending)} onOpenChange={(open) => !open && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove this preserved axiom?</AlertDialogTitle>
            <AlertDialogDescription>
              {pending?.summary}. The triples will no longer be exported or published. The removal is recorded in the
              activity log together with the N-Triples.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => pending && remove.mutate(pending)}>
              Remove axiom
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

// ------------------------------------------------------------------------------------ entailment

function EntailmentCard({ ontologyId, revision }: { ontologyId: string; revision: number }) {
  const [enabled, setEnabled] = useState(false)
  const report = useQuery({
    queryKey: queryKeys.entailments(ontologyId, revision),
    queryFn: () => semanticsApi.entailments(ontologyId),
    enabled,
  })
  return (
    <Card data-testid="entailment-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Brain className="size-4" /> Reasoning preview (OWL 2 RL)
        </CardTitle>
        <CardDescription>
          Informational only: inferred statements are never written to the ontology or a knowledge graph. Reasoning is kept
          separate from structural, SHACL and evidence validation.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!enabled ? (
          <Button variant="outline" onClick={() => setEnabled(true)}>
            <Brain /> Run reasoner on revision r{revision}
          </Button>
        ) : report.isPending ? (
          <LoadingState className="min-h-20" label="Reasoning…" />
        ) : report.isError ? (
          <ErrorState error={report.error} onRetry={() => report.refetch()} />
        ) : (
          <>
            {report.data.inconsistencies.length > 0 ? (
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertTitle>The ontology is inconsistent under OWL 2 RL</AlertTitle>
                <AlertDescription>
                  <ul className="list-disc pl-4">
                    {report.data.inconsistencies.map((m, i) => (
                      <li key={i}>{m}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            ) : (
              <p className="flex items-center gap-1.5 text-sm text-emerald-700" data-testid="reasoner-consistent">
                <CheckCircle2 className="size-4" /> No inconsistency detected.
              </p>
            )}
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <Badge variant="outline">{report.data.asserted_triples} asserted triples</Badge>
              {Object.entries(report.data.by_category).map(([category, count]) => (
                <Badge key={category} variant="secondary" className="font-normal">
                  {category}: {count}
                </Badge>
              ))}
              <span className="text-muted-foreground">
                {report.data.duration_ms} ms · {report.data.engine}
              </span>
            </div>
            {report.data.entailments.length === 0 ? (
              <p className="text-sm text-muted-foreground">No additional named-entity entailments.</p>
            ) : (
              <ul className="max-h-72 space-y-0.5 overflow-auto rounded-lg border p-2 font-mono text-[11px]" aria-label="Entailments">
                {report.data.entailments.map((e, i) => (
                  <li key={i}>{e.display}</li>
                ))}
              </ul>
            )}
            {report.data.truncated && <p className="text-xs text-muted-foreground">The list is truncated.</p>}
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function SemanticsView({ projectId, ontologyId, editor }: { projectId: string; ontologyId: string; editor: DraftEditor }) {
  const revision = editor.base?.draft_revision ?? 0
  return (
    <div className="mx-auto grid w-full max-w-7xl gap-6 p-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="semantics-view">
      <div className="space-y-6">
        <ExportCard ontologyId={ontologyId} editor={editor} />
        <ImportCard projectId={projectId} ontologyId={ontologyId} />
      </div>
      <div className="space-y-6">
        <AxiomsCard ontologyId={ontologyId} editor={editor} />
        <EntailmentCard key={revision} ontologyId={ontologyId} revision={revision} />
      </div>
    </div>
  )
}
