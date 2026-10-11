import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2, Plus, Sparkles, Trash2, XCircle } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { LoadingState, ErrorState } from '@/components/common/states'
import { errorMessage } from '@/lib/api/client'
import { kgApi } from '@/lib/api/endpoints'
import type {
  EntityMapping,
  MappingIssue,
  MappingSpec,
  PublishedVersionOption,
  RelationshipMapping,
  SourceDocument,
  SourceMapping,
  VersionDetail,
} from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import { useReviewerName } from '@/features/ontology/governance/reviewer'
import { FormField, NativeSelect } from '../fields'

const FROM_COLUMN = '__column__'

function emptyEntity(key: string): EntityMapping {
  return {
    key,
    class_id: null,
    class_column: null,
    id_column: '',
    label_column: null,
    alias_columns: [],
    alias_separator: '|',
    key_namespace: '',
    reference_only: false,
    attributes: [],
  }
}

function nextKey(entities: EntityMapping[]): string {
  let index = entities.length + 1
  while (entities.some((e) => e.key === `e${index}`)) index += 1
  return `e${index}`
}

export function MappingEditorDialog({
  open,
  onOpenChange,
  projectId,
  document,
  version,
  snapshot,
  existing,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  document: SourceDocument
  version: PublishedVersionOption
  snapshot: VersionDetail | undefined
  existing: SourceMapping | null
  onSaved: (mapping: SourceMapping) => void
}) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const [name, setName] = useState(() => existing?.name ?? `${document.filename.replace(/\.[^.]+$/, '')} mapping`)
  const [spec, setSpec] = useState<MappingSpec>(() => existing?.spec ?? { entities: [emptyEntity('e1')], relationships: [] })
  const [notes, setNotes] = useState<string[]>([])
  const [issues, setIssues] = useState<MappingIssue[]>([])

  const preview = useQuery({
    queryKey: queryKeys.sourcePreview(document.id),
    queryFn: () => kgApi.preview(document.id),
    enabled: open,
  })
  const columns = useMemo(() => preview.data?.columns.map((c) => c.name) ?? [], [preview.data])

  const suggest = useMutation({
    mutationFn: () => kgApi.suggestMapping(document.id, version.version_id),
    onSuccess: (suggestion) => {
      setNotes(suggestion.notes)
      if (suggestion.spec) setSpec(suggestion.spec)
      else toast.info('No mapping could be suggested', { description: suggestion.notes[0] })
    },
    onError: (error) => toast.error('Suggestion failed', { description: errorMessage(error) }),
  })
  const { mutate: runSuggestion } = suggest

  // A new mapping starts from a deterministic, column-name based suggestion that the SME reviews.
  useEffect(() => {
    if (!existing) runSuggestion()
  }, [existing, runSuggestion])

  useEffect(() => {
    const handle = window.setTimeout(() => {
      kgApi
        .validateMapping(projectId, { document_id: document.id, ontology_version_id: version.version_id, spec })
        .then((result) => setIssues(result.issues))
        .catch((error) => setIssues([{ severity: 'error', code: 'INVALID', message: errorMessage(error), path: '' }]))
    }, 300)
    return () => window.clearTimeout(handle)
  }, [spec, projectId, document.id, version.version_id])

  const save = useMutation({
    mutationFn: () =>
      existing
        ? kgApi.updateMapping(existing.id, { ontology_version_id: version.version_id, name, spec, updated_by: reviewer })
        : kgApi.createMapping(projectId, {
            document_id: document.id,
            ontology_version_id: version.version_id,
            name,
            spec,
            updated_by: reviewer,
          }),
    onSuccess: (mapping) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.kgMappings(projectId) })
      toast.success(`Mapping '${mapping.name}' saved`)
      onSaved(mapping)
      onOpenChange(false)
    },
    onError: (error) => toast.error('Could not save the mapping', { description: errorMessage(error) }),
  })

  const classes = snapshot?.snapshot.classes ?? []
  const objectProperties = snapshot?.snapshot.object_properties ?? []
  const datatypeProperties = snapshot?.snapshot.datatype_properties ?? []
  const classLabel = (id: string | null | undefined) => classes.find((c) => c.id === id)?.label ?? id ?? '?'

  const updateEntity = (index: number, patch: Partial<EntityMapping>) =>
    setSpec((s) => ({ ...s, entities: s.entities.map((e, i) => (i === index ? { ...e, ...patch } : e)) }))
  const removeEntity = (index: number) =>
    setSpec((s) => {
      const key = s.entities[index].key
      return {
        entities: s.entities.filter((_, i) => i !== index),
        relationships: s.relationships.filter((r) => r.subject !== key && r.object !== key),
      }
    })
  const updateRelationship = (index: number, patch: Partial<RelationshipMapping>) =>
    setSpec((s) => ({ ...s, relationships: s.relationships.map((r, i) => (i === index ? { ...r, ...patch } : r)) }))

  const errors = issues.filter((i) => i.severity === 'error')
  const warnings = issues.filter((i) => i.severity === 'warning')
  const incomplete = spec.entities.some((e) => !e.id_column || (!e.class_id && !e.class_column))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-5xl" data-testid="mapping-editor">
        <DialogHeader>
          <DialogTitle>Source-to-ontology mapping · {document.filename}</DialogTitle>
          <DialogDescription>
            Records are transformed deterministically (no LLM). Classes and properties come from{' '}
            <strong>
              {version.ontology_name} v{version.version}
            </strong>
            ; values that do not fit the ontology are rejected during validation, never repaired.
          </DialogDescription>
        </DialogHeader>

        {preview.isPending ? (
          <LoadingState className="min-h-24" label="Reading columns…" />
        ) : preview.isError ? (
          <ErrorState error={preview.error} />
        ) : (
          <section aria-label="Data preview" className="space-y-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Preview · {preview.data.total_rows} records · {preview.data.columns.length} columns
            </h3>
            <div className="max-h-48 overflow-auto rounded-lg border">
              <table className="w-full text-xs" data-testid="mapping-preview">
                <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">#</th>
                    {preview.data.columns.map((c) => (
                      <th key={c.name} className="px-2 py-1.5 text-left font-medium">
                        <span className="font-mono">{c.name}</span>
                        <span className="ml-1 font-normal text-muted-foreground">{c.inferred_datatype}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.data.rows.map((row) => (
                    <tr key={row.row_number} className="border-t">
                      <td className="px-2 py-1 text-muted-foreground">{row.row_number}</td>
                      {preview.data.columns.map((c) => (
                        <td key={c.name} className="px-2 py-1 whitespace-nowrap">
                          {row.values[c.name]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <FormField label="Mapping name" htmlFor="mapping-name">
            <Input id="mapping-name" value={name} onChange={(e) => setName(e.target.value)} />
          </FormField>
          <Button variant="outline" onClick={() => suggest.mutate()} disabled={suggest.isPending}>
            {suggest.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
            Suggest from column names
          </Button>
        </div>
        {notes.length > 0 && (
          <ul className="space-y-1 rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground" aria-label="Suggestion notes">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}

        <section className="space-y-3" aria-label="Entities">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Entities per record</h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSpec((s) => ({ ...s, entities: [...s.entities, emptyEntity(nextKey(s.entities))] }))}
            >
              <Plus /> Add entity
            </Button>
          </div>
          {spec.entities.map((entity, index) => (
            <div key={entity.key} className="space-y-3 rounded-lg border p-3" data-testid={`entity-${entity.key}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary" className="font-mono">
                  {entity.key}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {entity.reference_only
                    ? 'Referenced by key only - the record does not establish this entity'
                    : 'Master record - the record establishes this entity'}
                </span>
                <label className="ml-auto flex items-center gap-2 text-xs">
                  <Switch
                    checked={entity.reference_only}
                    onCheckedChange={(checked) =>
                      updateEntity(index, { reference_only: checked, attributes: checked ? [] : entity.attributes })
                    }
                    aria-label={`Reference only ${entity.key}`}
                  />
                  Reference only
                </label>
                {spec.entities.length > 1 && (
                  <Button variant="ghost" size="icon-xs" aria-label={`Remove ${entity.key}`} onClick={() => removeEntity(index)}>
                    <Trash2 />
                  </Button>
                )}
              </div>
              <div className="grid gap-3 sm:grid-cols-4">
                <FormField label="Ontology class">
                  <NativeSelect
                    aria-label={`Class for ${entity.key}`}
                    value={entity.class_column !== null ? FROM_COLUMN : (entity.class_id ?? '')}
                    onChange={(e) =>
                      e.target.value === FROM_COLUMN
                        ? updateEntity(index, { class_id: null, class_column: columns[0] ?? '' })
                        : updateEntity(index, { class_id: e.target.value || null, class_column: null })
                    }
                  >
                    <option value="">Select a class…</option>
                    {classes.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                    <option value={FROM_COLUMN}>Class named in a column…</option>
                  </NativeSelect>
                </FormField>
                {entity.class_column !== null && (
                  <FormField label="Class column">
                    <NativeSelect
                      aria-label={`Class column for ${entity.key}`}
                      value={entity.class_column}
                      onChange={(e) => updateEntity(index, { class_column: e.target.value })}
                    >
                      {columns.map((c) => (
                        <option key={c}>{c}</option>
                      ))}
                    </NativeSelect>
                  </FormField>
                )}
                <FormField label="Identifier column">
                  <NativeSelect
                    aria-label={`Identifier column for ${entity.key}`}
                    value={entity.id_column}
                    onChange={(e) => updateEntity(index, { id_column: e.target.value })}
                  >
                    <option value="">Select…</option>
                    {columns.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </NativeSelect>
                </FormField>
                <FormField label="Label column">
                  <NativeSelect
                    aria-label={`Label column for ${entity.key}`}
                    value={entity.label_column ?? ''}
                    onChange={(e) => updateEntity(index, { label_column: e.target.value || null })}
                  >
                    <option value="">(none)</option>
                    {columns.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </NativeSelect>
                </FormField>
                <FormField label="Alias column" hint={`Values split on "${entity.alias_separator}"`}>
                  <NativeSelect
                    aria-label={`Alias column for ${entity.key}`}
                    value={entity.alias_columns[0] ?? ''}
                    onChange={(e) => updateEntity(index, { alias_columns: e.target.value ? [e.target.value] : [] })}
                  >
                    <option value="">(none)</option>
                    {columns.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </NativeSelect>
                </FormField>
              </div>
              {!entity.reference_only && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Attributes</p>
                  {entity.attributes.map((attribute, attrIndex) => (
                    <div key={attrIndex} className="grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2">
                      <NativeSelect
                        aria-label="Attribute column"
                        value={attribute.column}
                        onChange={(e) =>
                          updateEntity(index, {
                            attributes: entity.attributes.map((a, i) => (i === attrIndex ? { ...a, column: e.target.value } : a)),
                          })
                        }
                      >
                        {columns.map((c) => (
                          <option key={c}>{c}</option>
                        ))}
                      </NativeSelect>
                      <span className="text-xs text-muted-foreground">→</span>
                      <NativeSelect
                        aria-label="Attribute property"
                        value={attribute.property_id}
                        onChange={(e) =>
                          updateEntity(index, {
                            attributes: entity.attributes.map((a, i) => (i === attrIndex ? { ...a, property_id: e.target.value } : a)),
                          })
                        }
                      >
                        {datatypeProperties.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.label} ({classLabel(p.domain_id)}, {p.datatype})
                          </option>
                        ))}
                      </NativeSelect>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        aria-label="Remove attribute"
                        onClick={() => updateEntity(index, { attributes: entity.attributes.filter((_, i) => i !== attrIndex) })}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  ))}
                  <Button
                    variant="ghost"
                    size="xs"
                    disabled={columns.length === 0 || datatypeProperties.length === 0}
                    onClick={() =>
                      updateEntity(index, {
                        attributes: [...entity.attributes, { column: columns[0], property_id: datatypeProperties[0].id }],
                      })
                    }
                  >
                    <Plus /> Add attribute
                  </Button>
                </div>
              )}
            </div>
          ))}
        </section>

        <section className="space-y-3" aria-label="Relationships">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Relationships between entities of a record</h3>
            <Button
              variant="ghost"
              size="sm"
              disabled={spec.entities.length < 2 || objectProperties.length === 0}
              onClick={() =>
                setSpec((s) => ({
                  ...s,
                  relationships: [
                    ...s.relationships,
                    { subject: s.entities[0].key, object: s.entities[1].key, predicate_id: objectProperties[0]?.id ?? null, predicate_column: null },
                  ],
                }))
              }
            >
              <Plus /> Add relationship
            </Button>
          </div>
          {spec.relationships.length === 0 && (
            <p className="text-xs text-muted-foreground">No relationships are created from this source.</p>
          )}
          {spec.relationships.map((rel, index) => (
            <div key={index} className="grid items-center gap-2 sm:grid-cols-[1fr_1.4fr_1fr_auto]" data-testid={`relationship-${index}`}>
              <NativeSelect aria-label="Subject entity" value={rel.subject} onChange={(e) => updateRelationship(index, { subject: e.target.value })}>
                {spec.entities.map((e) => (
                  <option key={e.key} value={e.key}>
                    {e.key} · {e.class_column ? `[${e.class_column}]` : classLabel(e.class_id)}
                  </option>
                ))}
              </NativeSelect>
              <div className="flex gap-2">
                <NativeSelect
                  aria-label="Relationship"
                  value={rel.predicate_column !== null ? FROM_COLUMN : (rel.predicate_id ?? '')}
                  onChange={(e) =>
                    e.target.value === FROM_COLUMN
                      ? updateRelationship(index, { predicate_id: null, predicate_column: columns[0] ?? '' })
                      : updateRelationship(index, { predicate_id: e.target.value, predicate_column: null })
                  }
                >
                  {objectProperties.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label} ({classLabel(p.domain_id)} → {classLabel(p.range_id)})
                    </option>
                  ))}
                  <option value={FROM_COLUMN}>Relationship named in a column…</option>
                </NativeSelect>
                {rel.predicate_column !== null && (
                  <NativeSelect
                    aria-label="Relationship column"
                    value={rel.predicate_column}
                    onChange={(e) => updateRelationship(index, { predicate_column: e.target.value })}
                  >
                    {columns.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </NativeSelect>
                )}
              </div>
              <NativeSelect aria-label="Object entity" value={rel.object} onChange={(e) => updateRelationship(index, { object: e.target.value })}>
                {spec.entities.map((e) => (
                  <option key={e.key} value={e.key}>
                    {e.key} · {e.class_column ? `[${e.class_column}]` : classLabel(e.class_id)}
                  </option>
                ))}
              </NativeSelect>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Remove relationship"
                onClick={() => setSpec((s) => ({ ...s, relationships: s.relationships.filter((_, i) => i !== index) }))}
              >
                <Trash2 />
              </Button>
            </div>
          ))}
        </section>

        {(errors.length > 0 || warnings.length > 0) && (
          <ul className="space-y-1.5 rounded-lg border p-3" aria-label="Mapping validation" data-testid="mapping-issues">
            {[...errors, ...warnings].map((issue, index) => (
              <li key={`${issue.path}-${index}`} className="flex gap-2 text-xs">
                {issue.severity === 'error' ? (
                  <XCircle className="mt-0.5 size-3.5 shrink-0 text-red-600" />
                ) : (
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
                )}
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
        )}

        <DialogFooter>
          {!reviewer && <p className="mr-auto text-xs text-amber-700">Set your reviewer name to save mappings.</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={save.isPending || suggest.isPending || errors.length > 0 || incomplete || !name.trim() || !reviewer}
          >
            {save.isPending && <Loader2 className="animate-spin" />}
            Save mapping
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
