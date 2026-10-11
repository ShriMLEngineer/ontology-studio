import { useMemo, useRef, useState, type DragEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, BrainCircuit, ChevronDown, Eye, FileSpreadsheet, FileText, Loader2, Play, Save, Settings2, Upload } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { kgApi, sourcesApi } from '@/lib/api/endpoints'
import type { BuildDetail, BuildSettings, PublishedVersionOption, SourceDocument, SourceMapping } from '@/lib/api/types'
import { plural } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import { useReviewerName } from '@/features/ontology/governance/reviewer'
import { FormField, NativeSelect } from '../fields'
import { isTabular, useLlmStatus, useMappings, useSources, useValidationPolicies, useVersionSnapshot } from '../hooks'
import { SourcePreviewDialog } from '../SourcePreviewDialog'
import { MappingEditorDialog } from './MappingEditorDialog'
import { useProjectDefaults } from '@/features/settings/hooks'
import { GraphTargetSelect, LlmConfigSelect } from '@/features/settings/selectors'

const DEFAULT_SETTINGS: BuildSettings = {
  max_chunks: 20,
  batch_chars: 6000,
  extract_attributes: true,
  instructions: '',
  validation_policy: 'application-strict/1',
}
const ACCEPT = '.csv,.tsv,.pdf,.txt,.md,.markdown'

function pickMapping(mappings: SourceMapping[], documentId: string, ontologyId: string | undefined): string | undefined {
  return mappings
    .filter((m) => m.document_id === documentId && (!ontologyId || m.ontology_id === ontologyId))
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]?.id
}

export function BuildConfigPanel({
  projectId,
  versions,
  build,
  onSaved,
}: {
  projectId: string
  versions: PublishedVersionOption[]
  build: BuildDetail | null
  onSaved: (build: BuildDetail) => void
}) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const sources = useSources(projectId)
  const mappings = useMappings(projectId)
  const policies = useValidationPolicies()
  const defaults = useProjectDefaults(projectId)
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const [name, setName] = useState(build?.name ?? '')
  const [versionId, setVersionId] = useState(build?.ontology_version_id ?? versions.find((v) => v.is_latest)?.version_id ?? '')
  const [selected, setSelected] = useState<Set<string>>(new Set(build?.sources.map((s) => s.id) ?? []))
  const [chosenMappings, setChosenMappings] = useState<Record<string, string>>(() =>
    Object.fromEntries((build?.sources ?? []).filter((s) => s.mapping_id).map((s) => [s.id, s.mapping_id as string])),
  )
  const [settings, setSettings] = useState<BuildSettings>(build?.settings ?? DEFAULT_SETTINGS)
  const llm = useLlmStatus(projectId, settings.llm_config_id ?? null)
  const [editing, setEditing] = useState<{ document: SourceDocument; mapping: SourceMapping | null } | null>(null)
  const [previewing, setPreviewing] = useState<SourceDocument | null>(null)
  const [showSchema, setShowSchema] = useState(false)

  const version = versions.find((v) => v.version_id === versionId)
  const snapshot = useVersionSnapshot(version?.ontology_id, version?.version_id)
  const documents = useMemo(() => sources.data ?? [], [sources.data])
  const mappingList = useMemo(() => mappings.data ?? [], [mappings.data])

  const mappingFor = (documentId: string): string | undefined => {
    const chosen = chosenMappings[documentId]
    if (chosen && mappingList.some((m) => m.id === chosen && m.ontology_id === version?.ontology_id)) return chosen
    return pickMapping(mappingList, documentId, version?.ontology_id)
  }

  const selectedDocs = documents.filter((d) => selected.has(d.id))
  const tabularDocs = selectedDocs.filter((d) => isTabular(d.media_type))
  const textDocs = selectedDocs.filter((d) => !isTabular(d.media_type))

  const problems: string[] = []
  if (versions.length === 0) problems.push('No published ontology version exists yet. Publish one in Ontology Studio → Registry.')
  else if (!version) problems.push('Select a published ontology version.')
  if (selectedDocs.length === 0) problems.push('Select at least one data source.')
  for (const doc of tabularDocs) if (!mappingFor(doc.id)) problems.push(`Configure a mapping for ${doc.filename}.`)
  if (textDocs.length > 0 && llm.data && !llm.data.configured)
    problems.push('Document sources need the LLM provider, which is not configured (OLS_LLM_BASE_URL, OLS_LLM_MODEL).')
  if (!reviewer) problems.push('Set your reviewer name (top right) - it is recorded on the build.')

  const upload = useMutation({
    mutationFn: (file: File) => sourcesApi.upload(projectId, file, reviewer),
    onSuccess: (document) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources(projectId) })
      setSelected((current) => new Set(current).add(document.id))
      toast.success(`Uploaded ${document.filename}`)
    },
    onError: (error) => toast.error('Upload failed', { description: errorMessage(error) }),
  })

  const payload = () => ({
    name: name.trim() || null,
    ontology_version_id: versionId,
    source_document_ids: selectedDocs.map((d) => d.id),
    mapping_ids: tabularDocs.map((d) => mappingFor(d.id)).filter((id): id is string => Boolean(id)),
    settings,
  })

  const save = useMutation({
    mutationFn: async (start: boolean) => {
      let saved = build
        ? await kgApi.updateBuild(build.id, payload())
        : await kgApi.createBuild(projectId, { ...payload(), requested_by: reviewer, start: false })
      if (start) saved = await kgApi.startBuild(saved.id, reviewer)
      return saved
    },
    onSuccess: (saved, start) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.kgBuilds(projectId) })
      queryClient.setQueryData(queryKeys.kgBuild(saved.id), saved)
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity(projectId) })
      if (start) toast.info(`Build #${saved.number} started`, { description: 'Progress is shown stage by stage.' })
      else toast.success(`Build #${saved.number} configuration saved`)
      onSaved(saved)
    },
    onError: (error) => toast.error('The build could not be saved or started', { description: errorMessage(error) }),
  })

  const toggle = (id: string, checked: boolean) =>
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    for (const file of Array.from(event.dataTransfer.files)) upload.mutate(file)
  }

  const classes = snapshot.data?.snapshot.classes ?? []
  const relations = snapshot.data?.snapshot.object_properties ?? []
  const classLabel = (id: string | null) => classes.find((c) => c.id === id)?.label ?? '?'

  return (
    <Card size="sm" data-testid="build-config">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Settings2 className="size-4" />
          {build ? `Configure build #${build.number}` : 'New knowledge graph build'}
        </CardTitle>
        <CardDescription>Builds always use an immutable, published ontology version as the schema authority.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <FormField label="Build name (optional)" htmlFor="build-name">
          <Input id="build-name" value={name} placeholder="e.g. Supplier network Q3" onChange={(e) => setName(e.target.value)} />
        </FormField>

        <section className="space-y-2" aria-label="Ontology version">
          <FormField label="Published ontology version" htmlFor="build-version">
            <NativeSelect id="build-version" value={versionId} onChange={(e) => setVersionId(e.target.value)} disabled={versions.length === 0}>
              <option value="">{versions.length ? 'Select a version…' : 'No published versions'}</option>
              {versions.map((v) => (
                <option key={v.version_id} value={v.version_id}>
                  {v.ontology_name} v{v.version}
                  {v.is_latest ? ' (latest)' : ''}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          {versions.length === 0 && (
            <Button variant="link" size="xs" className="px-0" asChild>
              <Link to={`/projects/${projectId}/ontology?tab=registry`}>Open the Registry in Ontology Studio</Link>
            </Button>
          )}
          {version && (
            <div className="rounded-lg border bg-muted/30">
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium"
                onClick={() => setShowSchema((value) => !value)}
                aria-expanded={showSchema}
              >
                <ChevronDown className={cn('size-3.5 transition-transform', !showSchema && '-rotate-90')} />
                Available for extraction: {plural(version.class_count, 'class', 'classes')},{' '}
                {plural(version.object_property_count, 'relationship')}, {plural(version.datatype_property_count, 'attribute')}
              </button>
              {showSchema && (
                <div className="grid gap-3 border-t px-3 py-2 text-xs sm:grid-cols-2" data-testid="version-schema">
                  <div>
                    <p className="mb-1 font-semibold text-muted-foreground">Classes</p>
                    <ul className="space-y-0.5">
                      {classes.map((c) => (
                        <li key={c.id}>{c.label}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="mb-1 font-semibold text-muted-foreground">Relationships</p>
                    <ul className="space-y-0.5">
                      {relations.map((p) => (
                        <li key={p.id}>
                          {classLabel(p.domain_id)} → <strong>{p.label}</strong> → {classLabel(p.range_id)}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        <section className="space-y-2" aria-label="Data sources">
          <p className="text-xs font-medium">Data sources</p>
          <div
            role="button"
            tabIndex={0}
            aria-label="Upload data sources"
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed px-3 py-3 text-xs transition-colors hover:bg-muted/50',
              dragging && 'border-primary bg-primary/5',
            )}
          >
            {upload.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4 text-muted-foreground" />}
            Upload CSV (structured) or PDF/text documents
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              multiple
              className="hidden"
              data-testid="kg-source-upload"
              onChange={(e) => {
                for (const file of Array.from(e.target.files ?? [])) upload.mutate(file)
                e.target.value = ''
              }}
            />
          </div>
          {documents.length === 0 ? (
            <p className="text-xs text-muted-foreground">No sources in this project yet.</p>
          ) : (
            <ul className="divide-y rounded-lg border" aria-label="Project sources">
              {documents.map((doc) => {
                const tabular = isTabular(doc.media_type)
                const mappingId = mappingFor(doc.id)
                const docMappings = mappingList.filter((m) => m.document_id === doc.id && m.ontology_id === version?.ontology_id)
                const mapping = docMappings.find((m) => m.id === mappingId) ?? null
                return (
                  <li key={doc.id} className="space-y-2 px-3 py-2" data-testid={`source-${doc.filename}`}>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id={`kg-src-${doc.id}`}
                        checked={selected.has(doc.id)}
                        onCheckedChange={(checked) => toggle(doc.id, checked === true)}
                        aria-label={`Use ${doc.filename}`}
                      />
                      {tabular ? <FileSpreadsheet className="size-4 text-emerald-600" /> : <FileText className="size-4 text-sky-600" />}
                      <label htmlFor={`kg-src-${doc.id}`} className="min-w-0 flex-1 cursor-pointer truncate text-sm">
                        {doc.filename}
                      </label>
                      <Badge variant="outline" className="text-[10px]">
                        {tabular ? 'Structured' : doc.page_count ? plural(doc.page_count, 'page') : 'Text'}
                      </Badge>
                      <Button variant="ghost" size="icon-xs" aria-label={`Preview ${doc.filename}`} onClick={() => setPreviewing(doc)}>
                        <Eye />
                      </Button>
                    </div>
                    {tabular && selected.has(doc.id) && (
                      <div className="ml-6 flex items-center gap-2">
                        {docMappings.length > 0 ? (
                          <NativeSelect
                            aria-label={`Mapping for ${doc.filename}`}
                            className="h-7 text-xs"
                            value={mappingId ?? ''}
                            onChange={(e) => setChosenMappings((current) => ({ ...current, [doc.id]: e.target.value }))}
                          >
                            {docMappings.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.name}
                                {m.issues.some((i) => i.severity === 'warning') ? ' (warnings)' : ''}
                              </option>
                            ))}
                          </NativeSelect>
                        ) : (
                          <span className="flex-1 text-xs text-amber-700">No mapping yet</span>
                        )}
                        <Button
                          variant="outline"
                          size="xs"
                          disabled={!version}
                          onClick={() => setEditing({ document: doc, mapping })}
                        >
                          {mapping ? 'Edit mapping' : 'Configure mapping'}
                        </Button>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section className="grid gap-3 sm:grid-cols-2" aria-label="Models and targets">
          <FormField label="LLM model" htmlFor="kg-llm" hint="Used for document sources; recorded with the build.">
            <LlmConfigSelect
              id="kg-llm"
              value={settings.llm_config_id}
              projectDefault={defaults.data?.effective_llm}
              onChange={(v) => setSettings((s) => ({ ...s, llm_config_id: v }))}
            />
          </FormField>
          <FormField label="Graph database" htmlFor="kg-graph" hint="Deployment target; recorded with the build.">
            <GraphTargetSelect
              id="kg-graph"
              value={settings.graph_connection_id}
              projectDefault={defaults.data?.effective_graph}
              onChange={(v) => setSettings((s) => ({ ...s, graph_connection_id: v }))}
            />
          </FormField>
        </section>

        <section className="space-y-2" aria-label="Validation settings">
          <FormField
            label="Validation policy"
            htmlFor="kg-policy"
            hint={policies.data?.find((p) => p.id === (settings.validation_policy ?? 'application-strict/1'))?.description}
          >
            <NativeSelect
              id="kg-policy"
              value={settings.validation_policy ?? 'application-strict/1'}
              onChange={(e) => setSettings((s) => ({ ...s, validation_policy: e.target.value }))}
            >
              {(policies.data ?? [{ id: 'application-strict/1', name: 'Application strict', default: true }]).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.id}){p.default ? ' - default' : ''}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <p className="text-[11px] text-muted-foreground">
            Structural, SHACL, evidence and (for open-world policies) OWL 2 RL entailment results are recorded separately for
            every fact; the policy only decides how they combine into accepted, rejected or quarantined.
          </p>
        </section>

        <section className="space-y-3" aria-label="Extraction settings">
          <p className="text-xs font-medium">Extraction settings (documents)</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Maximum chunks" htmlFor="max-chunks" hint="Text chunks sent to the LLM">
              <Input
                id="max-chunks"
                type="number"
                min={1}
                max={200}
                value={settings.max_chunks}
                onChange={(e) => setSettings((s) => ({ ...s, max_chunks: Number(e.target.value) || 1 }))}
              />
            </FormField>
            <FormField label="Characters per request" htmlFor="batch-chars" hint="Larger batches mean fewer, longer calls">
              <Input
                id="batch-chars"
                type="number"
                min={1000}
                max={20000}
                step={500}
                value={settings.batch_chars}
                onChange={(e) => setSettings((s) => ({ ...s, batch_chars: Number(e.target.value) || 6000 }))}
              />
            </FormField>
          </div>
          <label className="flex items-center gap-2 text-xs">
            <Switch
              checked={settings.extract_attributes}
              onCheckedChange={(checked) => setSettings((s) => ({ ...s, extract_attributes: checked }))}
              aria-label="Extract attribute values"
            />
            Extract attribute values from documents
          </label>
          <FormField label="SME focus (optional)" htmlFor="kg-instructions">
            <Textarea
              id="kg-instructions"
              rows={2}
              value={settings.instructions}
              placeholder="e.g. Focus on supplier relationships"
              onChange={(e) => setSettings((s) => ({ ...s, instructions: e.target.value }))}
            />
          </FormField>
          <div className="flex items-center gap-2 rounded-lg bg-muted/40 px-3 py-2 text-xs" data-testid="llm-info">
            <BrainCircuit className="size-4 text-muted-foreground" />
            {llm.data?.configured ? (
              <span>
                LLM: <strong>{llm.data.model}</strong> via {llm.data.provider}
                {llm.data.endpoint_host ? ` (${llm.data.endpoint_host})` : ''} - {llm.data.config_name ?? 'server configuration'}
              </span>
            ) : (
              <span className="text-amber-700">No LLM available for this build - only structured sources can be built.</span>
            )}
          </div>
        </section>

        {(problems.length > 0 || (build?.readiness && !build.readiness.ready)) && (
          <ul className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900" role="alert" data-testid="build-problems">
            {problems.map((problem) => (
              <li key={problem} className="flex gap-2">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                {problem}
              </li>
            ))}
            {problems.length === 0 &&
              build?.readiness?.issues
                .filter((i) => i.severity === 'error')
                .map((issue) => (
                  <li key={issue.message} className="flex gap-2">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                    {issue.message}
                  </li>
                ))}
          </ul>
        )}

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => save.mutate(false)} disabled={save.isPending || !version || selectedDocs.length === 0 || !reviewer}>
            <Save /> Save configuration
          </Button>
          <Button onClick={() => save.mutate(true)} disabled={save.isPending || problems.length > 0}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Play />}
            Start build
          </Button>
        </div>
      </CardContent>
      {editing && version && (
        <MappingEditorDialog
          key={`${editing.document.id}-${editing.mapping?.id ?? 'new'}`}
          open
          onOpenChange={(open) => !open && setEditing(null)}
          projectId={projectId}
          document={editing.document}
          version={version}
          snapshot={snapshot.data}
          existing={editing.mapping}
          onSaved={(mapping) => setChosenMappings((current) => ({ ...current, [mapping.document_id]: mapping.id }))}
        />
      )}
      {previewing && <SourcePreviewDialog document={previewing} onClose={() => setPreviewing(null)} />}
    </Card>
  )
}
