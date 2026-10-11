import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Download, GitCompareArrows, Loader2, PackageCheck, ShieldAlert, ShieldCheck, Tag } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from 'cn'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ApiError, errorMessage } from '@/lib/api/client'
import { registryApi } from '@/lib/api/endpoints'
import type { ArtifactFormat, SchemaDiff, VersionBump, VersionSummary } from '@/lib/api/types'
import { dateTime, plural, relativeTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import type { DraftEditor } from '../draft/useDraftEditor'
import { FIELD_LABEL, KIND_LABEL } from '../governance/meta'
import { useReviewerName } from '../governance/reviewer'
import { makeLabelResolver, type LabelResolver } from '../review/labels'
import { FieldValue } from '../review/parts'

const DRAFT = 'draft'
const ARTIFACT_LABEL: Record<ArtifactFormat, string> = {
  turtle: 'Turtle (.ttl)',
  rdfxml: 'RDF/XML',
  jsonld: 'JSON-LD',
  ntriples: 'N-Triples',
  json: 'Snapshot JSON',
  manifest: 'Manifest',
}
const LEGACY_DERIVABLE: ArtifactFormat[] = ['rdfxml', 'jsonld', 'ntriples']

function showValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}
const CHANGE_STYLE = {
  added: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  modified: 'border-amber-200 bg-amber-50 text-amber-800',
  removed: 'border-red-200 bg-red-50 text-red-700',
}

export function DiffView({ diff, labelOf }: { diff: SchemaDiff; labelOf: LabelResolver }) {
  if (!diff.has_changes) return <p className="text-sm text-muted-foreground">No differences between {diff.from_label} and {diff.to_label}.</p>
  return (
    <div className="space-y-3" data-testid="schema-diff">
      <div className="flex flex-wrap gap-2 text-xs">
        {(Object.entries(diff.summary) as [keyof typeof KIND_LABEL, SchemaDiff['summary']['class']][]).map(([kind, counts]) =>
          counts.added + counts.modified + counts.removed > 0 ? (
            <Badge key={kind} variant="outline">
              {KIND_LABEL[kind]}: +{counts.added} ~{counts.modified} -{counts.removed}
            </Badge>
          ) : null,
        )}
        {diff.suggested_bump !== 'none' && <Badge variant="secondary">Suggested bump: {diff.suggested_bump}</Badge>}
      </div>
      {(diff.notes ?? []).map((note, i) => (
        <Alert key={i} data-testid="diff-note">
          <AlertTriangle />
          <AlertTitle>Semantic profile change</AlertTitle>
          <AlertDescription>{note}</AlertDescription>
        </Alert>
      ))}
      {diff.breaking_changes.length > 0 && (
        <Alert>
          <AlertTriangle />
          <AlertTitle>Breaking changes for consumers</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {diff.breaking_changes.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      <ul className="divide-y rounded-lg border">
        {diff.metadata_changes.map((c) => (
          <li key={c.field} className="px-3 py-2 text-sm">
            <span className="font-medium">Ontology {c.field}</span>: {showValue(c.before)} <ArrowRight className="inline size-3" />{' '}
            {showValue(c.after)}
          </li>
        ))}
        {(diff.axiom_changes ?? []).map((a) => (
          <li key={`${a.change}-${a.axiom_id}`} className="px-3 py-2 text-sm">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className={cn('capitalize', CHANGE_STYLE[a.change])}>
                {a.change}
              </Badge>
              <span className="text-xs text-muted-foreground">Preserved axiom ? {a.kind}</span>
              <span className="font-mono text-xs">{a.summary}</span>
            </div>
          </li>
        ))}
        {diff.elements.map((element) => (
          <li key={`${element.change}-${element.element_id}`} className="px-3 py-2 text-sm">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className={cn('capitalize', CHANGE_STYLE[element.change])}>
                {element.change}
              </Badge>
              <span className="text-xs text-muted-foreground">{KIND_LABEL[element.element_kind]}</span>
              <span className="font-medium">{element.label}</span>
            </div>
            {element.fields.length > 0 && (
              <dl className="mt-1.5 grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 pl-1 text-xs">
                {element.fields.map((f) => (
                  <div key={f.field} className="contents">
                    <dt className="text-muted-foreground">{FIELD_LABEL[f.field] ?? f.field}</dt>
                    <dd className="flex flex-wrap items-center gap-1.5">
                      <span className="line-through decoration-red-300 opacity-70">
                        <FieldValue field={f.field} value={f.before} labelOf={labelOf} />
                      </span>
                      <ArrowRight className="size-3 shrink-0" />
                      <FieldValue field={f.field} value={f.after} labelOf={labelOf} />
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function PublishCard({
  projectId,
  ontologyId,
  editor,
  labelOf,
}: {
  projectId: string
  ontologyId: string
  editor: DraftEditor
  labelOf: LabelResolver
}) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const [bump, setBump] = useState<VersionBump | undefined>(undefined)
  const [version, setVersion] = useState('')
  const [notes, setNotes] = useState('')
  const preview = useQuery({
    queryKey: [...queryKeys.publishPreview(ontologyId), bump ?? 'auto'],
    queryFn: () => registryApi.preview(ontologyId, bump),
  })

  const publish = useMutation({
    mutationFn: () =>
      registryApi.publish(ontologyId, {
        published_by: reviewer,
        release_notes: notes,
        version: version.trim() || null,
        bump: version.trim() ? null : (bump ?? null),
        expected_draft_revision: preview.data?.draft_revision ?? null,
      }),
    onSuccess: (published) => {
      toast.success(`Published version ${published.version}`, { description: 'The snapshot and its artifacts are now immutable.' })
      setVersion('')
      setNotes('')
      for (const key of [
        queryKeys.versions(ontologyId),
        queryKeys.publishPreview(ontologyId),
        queryKeys.ontologies(projectId),
        queryKeys.activity(projectId),
        queryKeys.latestValidation(ontologyId),
      ]) {
        void queryClient.invalidateQueries({ queryKey: key })
      }
    },
  })

  if (preview.isPending) return <LoadingState label="Preparing publication preview…" />
  if (preview.isError) return <ErrorState title="Unable to prepare publication" error={preview.error} onRetry={() => preview.refetch()} />
  const data = preview.data
  const publishError = publish.error instanceof ApiError ? publish.error : null
  const blockedIssues = (publishError?.details.issues as { message: string }[] | undefined) ?? []
  const disabledReason = !reviewer
    ? 'Set your reviewer name to publish.'
    : editor.dirty
      ? 'Save or discard unsaved designer changes first.'
      : !data.can_publish
        ? data.blockers[0]
        : null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PackageCheck className="size-4" /> Publish a new version
        </CardTitle>
        <CardDescription>
          Publishes draft revision {data.draft_revision} as an immutable version package: snapshot JSON, OWL in Turtle,
          RDF/XML, JSON-LD and N-Triples, and a manifest.
          {data.latest_version ? ` Latest version: v${data.latest_version.version}.` : ' Nothing has been published yet.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          className={cn(
            'flex items-start gap-3 rounded-lg border p-3 text-sm',
            data.validation.is_valid ? 'border-emerald-200 bg-emerald-50/60' : 'border-red-200 bg-red-50',
          )}
          data-testid="publish-validation"
        >
          {data.validation.is_valid ? <ShieldCheck className="size-5 text-emerald-600" /> : <ShieldAlert className="size-5 text-red-600" />}
          <div>
            <p className="font-medium">
              {data.validation.is_valid ? 'Validation gate passed' : `Blocked by ${plural(data.validation.error_count, 'validation error')}`}
            </p>
            <p className="text-xs text-muted-foreground">
              {plural(data.validation.warning_count, 'warning')} and {data.validation.info_count} info findings do not block publication.
            </p>
            {data.validation.blocking_issues.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-xs">
                {data.validation.blocking_issues.slice(0, 5).map((issue, i) => (
                  <li key={i}>{issue.message}</li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {(data.proposals_awaiting_review > 0 || data.proposals_approved_not_applied > 0) && (
          <p className="text-xs text-muted-foreground">
            Note: {plural(data.proposals_awaiting_review, 'proposal')} awaiting review and{' '}
            {plural(data.proposals_approved_not_applied, 'approved proposal')} not yet applied are not part of this publication.
          </p>
        )}

        <div>
          <p className="mb-2 text-sm font-medium">
            Changes since {data.latest_version ? `v${data.latest_version.version}` : 'the start'}
          </p>
          <DiffView diff={data.diff} labelOf={labelOf} />
        </div>

        <div className="grid gap-3 sm:grid-cols-[160px_1fr]">
          <div className="grid gap-1.5">
            <Label htmlFor="publish-bump" className="text-xs">
              Version bump
            </Label>
            <Select value={bump ?? 'auto'} onValueChange={(v) => setBump(v === 'auto' ? undefined : (v as VersionBump))}>
              <SelectTrigger id="publish-bump" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Suggested</SelectItem>
                <SelectItem value="major">Major</SelectItem>
                <SelectItem value="minor">Minor</SelectItem>
                <SelectItem value="patch">Patch</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="publish-version" className="text-xs">
              Version
            </Label>
            <Input
              id="publish-version"
              className="font-mono"
              placeholder={data.suggested_version}
              value={version}
              onChange={(e) => setVersion(e.target.value)}
            />
          </div>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="publish-notes" className="text-xs">
            Release notes
          </Label>
          <Textarea
            id="publish-notes"
            rows={3}
            placeholder="What changed and why"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        {publish.isError && (
          <Alert variant="destructive">
            <AlertDescription>
              {errorMessage(publish.error)}
              {blockedIssues.length > 0 && (
                <ul className="mt-1 list-disc pl-4">
                  {blockedIssues.map((issue, i) => (
                    <li key={i}>{issue.message}</li>
                  ))}
                </ul>
              )}
            </AlertDescription>
          </Alert>
        )}
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">{disabledReason ?? `Will publish as v${version.trim() || data.suggested_version} by ${reviewer}.`}</p>
          <Button onClick={() => publish.mutate()} disabled={Boolean(disabledReason) || publish.isPending}>
            {publish.isPending ? <Loader2 className="animate-spin" /> : <Tag />}
            Publish v{version.trim() || data.suggested_version}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function CompareCard({ ontologyId, versions, labelOf }: { ontologyId: string; versions: VersionSummary[]; labelOf: LabelResolver }) {
  const [base, setBase] = useState(versions[1]?.id ?? versions[0]?.id ?? DRAFT)
  const [target, setTarget] = useState(versions[1] ? versions[0].id : DRAFT)
  const diff = useQuery({
    queryKey: queryKeys.compare(ontologyId, base, target),
    queryFn: () => registryApi.compare(ontologyId, base, target),
  })
  const options = [{ id: DRAFT, label: 'Current draft' }, ...versions.map((v) => ({ id: v.id, label: `v${v.version}` }))]
  return (
    <Card data-testid="compare-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitCompareArrows className="size-4" /> Compare versions
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {[
            { id: 'compare-base', value: base, set: setBase, label: 'From' },
            { id: 'compare-target', value: target, set: setTarget, label: 'To' },
          ].map((control, index) => (
            <div key={control.id} className="flex items-center gap-2">
              {index === 1 && <ArrowRight className="size-4 text-muted-foreground" />}
              <Select value={control.value} onValueChange={control.set}>
                <SelectTrigger id={control.id} aria-label={`Compare ${control.label.toLowerCase()}`} className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {options.map((o) => (
                    <SelectItem key={o.id} value={o.id}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ))}
        </div>
        {diff.isPending ? (
          <LoadingState className="min-h-20" />
        ) : diff.isError ? (
          <ErrorState error={diff.error} onRetry={() => diff.refetch()} />
        ) : (
          <DiffView diff={diff.data} labelOf={labelOf} />
        )}
      </CardContent>
    </Card>
  )
}

export function RegistryView({ projectId, ontologyId, editor }: { projectId: string; ontologyId: string; editor: DraftEditor }) {
  const versions = useQuery({ queryKey: queryKeys.versions(ontologyId), queryFn: () => registryApi.versions(ontologyId) })
  const labelOf = makeLabelResolver(editor.doc, undefined)

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-6 p-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-6">
        {editor.dirty && (
          <Alert>
            <AlertTriangle />
            <AlertTitle>Unsaved designer changes</AlertTitle>
            <AlertDescription>Publication uses the saved draft. Save or discard your changes in the designer first.</AlertDescription>
          </Alert>
        )}
        <PublishCard projectId={projectId} ontologyId={ontologyId} editor={editor} labelOf={labelOf} />
      </div>
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Version history</CardTitle>
            <CardDescription>Published versions are immutable. Exports are verified against their recorded checksums.</CardDescription>
          </CardHeader>
          <CardContent>
            {versions.isPending ? (
              <LoadingState className="min-h-20" />
            ) : versions.isError ? (
              <ErrorState error={versions.error} onRetry={() => versions.refetch()} />
            ) : versions.data.length === 0 ? (
              <EmptyState icon={<Tag />} title="No published versions" description="Publish the validated draft to create version 1.0.0." />
            ) : (
              <ol className="space-y-3" aria-label="Version history">
                {versions.data.map((v, index) => (
                  <li key={v.id} className="rounded-lg border p-3" data-testid="version-row">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className="font-mono">v{v.version}</Badge>
                      {index === 0 && <Badge variant="outline">Latest</Badge>}
                      <Badge variant="outline" className="text-[10px]" title={v.snapshot_format}>
                        {v.package_format}
                      </Badge>
                      <span className="text-sm text-muted-foreground" title={dateTime(v.published_at)}>
                        {v.published_by} · {relativeTime(v.published_at)} · from draft r{v.draft_revision}
                      </span>
                    </div>
                    <p className="mt-1.5 text-xs text-muted-foreground">
                      {plural(v.class_count, 'class', 'classes')}, {plural(v.object_property_count, 'relationship')},{' '}
                      {plural(v.datatype_property_count, 'attribute')} · sha256 {v.content_hash.slice(0, 12)}…
                    </p>
                    {v.release_notes && <p className="mt-1.5 text-sm">{v.release_notes}</p>}
                    <div className="mt-2 flex flex-wrap gap-2">
                      {v.artifacts.map((artifact) => (
                        <Button key={artifact.format} variant="outline" size="xs" asChild>
                          <a href={registryApi.exportUrl(ontologyId, v.id, artifact.format)} download={artifact.filename}>
                            <Download /> {ARTIFACT_LABEL[artifact.format] ?? artifact.format}
                          </a>
                        </Button>
                      ))}
                      {v.snapshot_format === 'ols.ontology-snapshot/1' &&
                        LEGACY_DERIVABLE.map((format) => (
                          <Button
                            key={format}
                            variant="ghost"
                            size="xs"
                            asChild
                            title="Derived from the stored Turtle on download; not part of the original publication"
                          >
                            <a href={registryApi.exportUrl(ontologyId, v.id, format)}>
                              <Download /> {ARTIFACT_LABEL[format]} (derived)
                            </a>
                          </Button>
                        ))}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
        {versions.data && versions.data.length > 0 && (
          <CompareCard key={versions.data[0].id} ontologyId={ontologyId} versions={versions.data} labelOf={labelOf} />
        )}
      </div>
    </div>
  )
}
