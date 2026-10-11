import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileUp,
  Loader2,
  Pencil,
  Plus,
  ShieldCheck,
  ShieldQuestion,
  SquareStack,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { shapesApi } from '@/lib/api/endpoints'
import {
  XSD_DATATYPES,
  type NodeShape,
  type NodeShapeInput,
  type PropertyConstraint,
  type ShapeSeverity,
} from '@/lib/api/types'
import { plural } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import type { DraftDoc } from '../draft/model'
import type { DraftEditor } from '../draft/useDraftEditor'
import { useReviewerName } from '../governance/reviewer'
import { ShaclResults } from './ShaclResults'
import { SEVERITY_STYLE } from './severity'

const SEVERITIES: ShapeSeverity[] = ['Violation', 'Warning', 'Info']
const NONE = '__none__'

function labelOf(doc: DraftDoc | undefined, id: string | null | undefined): string {
  if (!id) return '—'
  if (!doc) return id
  return (
    doc.classes.find((c) => c.id === id)?.label ??
    doc.object_properties.find((p) => p.id === id)?.label ??
    doc.datatype_properties.find((p) => p.id === id)?.label ??
    `${id} (missing)`
  )
}

function describeConstraint(c: PropertyConstraint, doc: DraftDoc | undefined): string {
  const parts: string[] = []
  if (c.min_count != null) parts.push(`min ${c.min_count}`)
  if (c.max_count != null) parts.push(`max ${c.max_count}`)
  if (c.datatype) parts.push(`xsd:${c.datatype}`)
  if (c.class_id) parts.push(`class ${labelOf(doc, c.class_id)}`)
  if (c.node_kind) parts.push(`node kind ${c.node_kind}`)
  if (c.pattern) parts.push(`pattern /${c.pattern}/`)
  if (c.min_length != null) parts.push(`length ≥ ${c.min_length}`)
  if (c.max_length != null) parts.push(`length ≤ ${c.max_length}`)
  if (c.min_inclusive) parts.push(`≥ ${c.min_inclusive}`)
  if (c.max_inclusive) parts.push(`≤ ${c.max_inclusive}`)
  if (c.allowed_values?.length) parts.push(`one of ${c.allowed_values.join(', ')}`)
  return `${labelOf(doc, c.path_id)}: ${parts.join(' · ') || 'no condition'}`
}

// ------------------------------------------------------------------------------------ shape dialog

const numberOrNull = (value: string) => (value.trim() === '' ? null : Number(value))
const textOrNull = (value: string) => (value.trim() === '' ? null : value)

function ConstraintEditor({
  doc,
  value,
  index,
  onChange,
  onRemove,
}: {
  doc: DraftDoc
  value: PropertyConstraint
  index: number
  onChange: (next: PropertyConstraint) => void
  onRemove: () => void
}) {
  const isRelationship = doc.object_properties.some((p) => p.id === value.path_id)
  const set = (patch: Partial<PropertyConstraint>) => onChange({ ...value, ...patch })
  return (
    <div className="space-y-2 rounded-lg border p-3" data-testid="constraint-editor">
      <div className="flex items-center gap-2">
        <Select
          value={value.path_id || NONE}
          onValueChange={(v) => set({ path_id: v === NONE ? '' : v, class_id: null, datatype: null })}
        >
          <SelectTrigger className="flex-1" aria-label={`Constraint ${index + 1} property`}>
            <SelectValue placeholder="Property (sh:path)" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE} disabled>
              Choose a property
            </SelectItem>
            {doc.datatype_properties.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.label} · attribute of {labelOf(doc, p.domain_id)}
              </SelectItem>
            ))}
            {doc.object_properties.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.label} · relationship
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="ghost" size="icon-sm" aria-label={`Remove constraint ${index + 1}`} onClick={onRemove}>
          <X />
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Input
          aria-label="Minimum count"
          placeholder="min count"
          type="number"
          min={0}
          value={value.min_count ?? ''}
          onChange={(e) => set({ min_count: numberOrNull(e.target.value) })}
        />
        <Input
          aria-label="Maximum count"
          placeholder="max count"
          type="number"
          min={0}
          value={value.max_count ?? ''}
          onChange={(e) => set({ max_count: numberOrNull(e.target.value) })}
        />
        {isRelationship ? (
          <Select value={value.class_id ?? NONE} onValueChange={(v) => set({ class_id: v === NONE ? null : v })}>
            <SelectTrigger className="col-span-2 w-full" aria-label="Value class (sh:class)">
              <SelectValue placeholder="Value class" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Any class</SelectItem>
              {doc.classes.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <>
            <Select
              value={value.datatype ?? NONE}
              onValueChange={(v) => set({ datatype: v === NONE ? null : (v as PropertyConstraint['datatype']) })}
            >
              <SelectTrigger className="w-full" aria-label="Datatype (sh:datatype)">
                <SelectValue placeholder="Datatype" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Any datatype</SelectItem>
                {XSD_DATATYPES.map((d) => (
                  <SelectItem key={d} value={d}>
                    xsd:{d}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label="Pattern (regular expression)"
              placeholder="pattern (regex)"
              className="font-mono text-xs"
              value={value.pattern ?? ''}
              onChange={(e) => set({ pattern: textOrNull(e.target.value) })}
            />
            <Input
              aria-label="Minimum length"
              placeholder="min length"
              type="number"
              min={0}
              value={value.min_length ?? ''}
              onChange={(e) => set({ min_length: numberOrNull(e.target.value) })}
            />
            <Input
              aria-label="Maximum length"
              placeholder="max length"
              type="number"
              min={0}
              value={value.max_length ?? ''}
              onChange={(e) => set({ max_length: numberOrNull(e.target.value) })}
            />
            <Input
              aria-label="Minimum value (inclusive)"
              placeholder="min value"
              value={value.min_inclusive ?? ''}
              onChange={(e) => set({ min_inclusive: textOrNull(e.target.value) })}
            />
            <Input
              aria-label="Maximum value (inclusive)"
              placeholder="max value"
              value={value.max_inclusive ?? ''}
              onChange={(e) => set({ max_inclusive: textOrNull(e.target.value) })}
            />
          </>
        )}
      </div>
      <Input
        aria-label="Allowed values (comma separated)"
        placeholder={isRelationship ? 'allowed IRIs, comma separated (sh:in)' : 'allowed values, comma separated (sh:in)'}
        value={(value.allowed_values ?? []).join(', ')}
        onChange={(e) =>
          set({
            allowed_values: e.target.value
              .split(',')
              .map((v) => v.trim())
              .filter(Boolean),
          })
        }
      />
    </div>
  )
}

function emptyInput(doc: DraftDoc): NodeShapeInput {
  return {
    target_class_id: doc.classes[0]?.id ?? '',
    label: '',
    description: '',
    severity: 'Violation',
    message: '',
    deactivated: false,
    properties: [{ path_id: '' }],
  }
}

function ShapeDialog({
  doc,
  initial,
  onClose,
  onSave,
  saving,
  error,
}: {
  doc: DraftDoc
  initial: NodeShapeInput
  onClose: () => void
  onSave: (value: NodeShapeInput) => void
  saving: boolean
  error: unknown
}) {
  const [value, setValue] = useState<NodeShapeInput>(initial)
  const set = (patch: Partial<NodeShapeInput>) => setValue((v) => ({ ...v, ...patch }))
  const valid = value.label.trim() && value.target_class_id && value.properties.every((p) => p.path_id)
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl" data-testid="shape-dialog">
        <DialogHeader>
          <DialogTitle>{initial.label ? `Edit shape "${initial.label}"` : 'New SHACL shape'}</DialogTitle>
          <DialogDescription>
            A node shape targets every instance of a class (sh:targetClass, including subclasses) and constrains the
            values of its properties.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label htmlFor="shape-label" className="text-xs">
              Label
            </Label>
            <Input id="shape-label" value={value.label} onChange={(e) => set({ label: e.target.value })} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="shape-target" className="text-xs">
              Target class
            </Label>
            <Select value={value.target_class_id} onValueChange={(v) => set({ target_class_id: v })}>
              <SelectTrigger id="shape-target" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {doc.classes.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="shape-severity" className="text-xs">
              Severity
            </Label>
            <Select value={value.severity} onValueChange={(v) => set({ severity: v as ShapeSeverity })}>
              <SelectTrigger id="shape-severity" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SEVERITIES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <label className="flex items-end gap-2 pb-2 text-xs" htmlFor="shape-deactivated">
            <Switch id="shape-deactivated" checked={value.deactivated} onCheckedChange={(checked) => set({ deactivated: checked })} />
            Deactivated (sh:deactivated)
          </label>
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor="shape-message" className="text-xs">
              Message shown for results
            </Label>
            <Input id="shape-message" value={value.message} onChange={(e) => set({ message: e.target.value })} />
          </div>
        </div>
        <div className="space-y-2">
          <p className="text-xs font-medium">Property constraints</p>
          {value.properties.map((constraint, index) => (
            <ConstraintEditor
              key={index}
              doc={doc}
              index={index}
              value={constraint}
              onChange={(next) => set({ properties: value.properties.map((p, i) => (i === index ? next : p)) })}
              onRemove={() => set({ properties: value.properties.filter((_, i) => i !== index) })}
            />
          ))}
          <Button variant="outline" size="xs" onClick={() => set({ properties: [...value.properties, { path_id: '' }] })}>
            <Plus /> Add constraint
          </Button>
        </div>
        {Boolean(error) && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(error)}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => onSave(value)} disabled={!valid || saving}>
            {saving && <Loader2 className="animate-spin" />} Save shape
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------------------------ sample validation

const SAMPLE_PLACEHOLDER = `@prefix ex: <https://example.org/data/> .
# Paste instance data in Turtle, using the ontology IRIs.`

function SampleValidationCard({ ontologyId, revision }: { ontologyId: string; revision: number }) {
  const [data, setData] = useState('')
  const [signatures, setSignatures] = useState(false)
  const validate = useMutation({ mutationFn: () => shapesApi.validate(ontologyId, data, signatures) })
  return (
    <Card data-testid="shacl-sample-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldQuestion className="size-4" /> Validate sample data
        </CardTitle>
        <CardDescription>
          Runs PySHACL against the shapes of revision r{revision} with the class hierarchy mixed in and no inference.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          aria-label="Sample data (Turtle)"
          rows={8}
          className="font-mono text-xs"
          placeholder={SAMPLE_PLACEHOLDER}
          value={data}
          onChange={(e) => setData(e.target.value)}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-xs" htmlFor="include-signatures">
            <Switch id="include-signatures" checked={signatures} onCheckedChange={setSignatures} />
            Also enforce domain/range signature shapes
          </label>
          <Button onClick={() => validate.mutate()} disabled={!data.trim() || validate.isPending}>
            {validate.isPending ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Validate
          </Button>
        </div>
        {validate.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(validate.error)}</AlertDescription>
          </Alert>
        )}
        {validate.data && <ShaclResults report={validate.data} />}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------------------------ view

export function ShapesView({ ontologyId, editor }: { ontologyId: string; editor: DraftEditor }) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const doc = editor.doc
  const fileRef = useRef<HTMLInputElement>(null)
  const [dialog, setDialog] = useState<{ shape: NodeShape | null } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<NodeShape | null>(null)
  const overview = useQuery({ queryKey: queryKeys.shapes(ontologyId), queryFn: () => shapesApi.overview(ontologyId) })
  const disabledReason = !reviewer
    ? 'Set your reviewer name first.'
    : editor.dirty
      ? 'Save or discard designer changes first.'
      : null

  const afterChange = () => {
    void queryClient.invalidateQueries({ queryKey: ['ontologies', ontologyId] })
    void editor.reload()
  }
  const save = useMutation({
    mutationFn: ({ id, value }: { id: string | null; value: NodeShapeInput }) =>
      id ? shapesApi.update(ontologyId, id, value, reviewer) : shapesApi.create(ontologyId, value, reviewer),
    onSuccess: (shape) => {
      toast.success(`Shape '${shape.label}' saved`, { description: 'The draft revision was incremented.' })
      setDialog(null)
      afterChange()
    },
  })
  const remove = useMutation({
    mutationFn: (shape: NodeShape) => shapesApi.remove(ontologyId, shape.id, reviewer),
    onSuccess: () => {
      toast.success('Shape deleted')
      afterChange()
    },
    onError: (error) => toast.error('Could not delete the shape', { description: errorMessage(error) }),
    onSettled: () => setPendingDelete(null),
  })
  const importShapes = useMutation({
    mutationFn: (file: File) => shapesApi.importShapes(ontologyId, file, reviewer),
    onSuccess: (result) => {
      toast.success(`${plural(result.preserved.length, 'shape group')} imported`, {
        description: 'Preserved verbatim and enforced.',
      })
      afterChange()
    },
    onError: (error) => toast.error('SHACL import failed', { description: errorMessage(error) }),
    onSettled: () => {
      if (fileRef.current) fileRef.current.value = ''
    },
  })

  if (overview.isPending || !doc) return <LoadingState label="Loading shapes…" />
  if (overview.isError) return <ErrorState className="m-6" error={overview.error} onRetry={() => overview.refetch()} />
  const data = overview.data

  return (
    <div className="mx-auto grid w-full max-w-7xl gap-6 p-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="shapes-view">
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SquareStack className="size-4" /> SHACL shapes of the draft
            </CardTitle>
            <CardDescription>
              Shapes validate knowledge-graph data (closed world); they never change the ontology. Generated shapes follow
              the designer's required, single-value, datatype and range settings; authored shapes add SME rules; imported
              SHACL is preserved verbatim. All are published with the version as shapes.ttl.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2 text-xs">
            {data.check.well_formed ? (
              <Badge className="gap-1 bg-emerald-600" data-testid="shapes-well-formed">
                <CheckCircle2 className="size-3" /> Well formed (SHACL-SHACL)
              </Badge>
            ) : (
              <Badge variant="destructive" title={data.check.message}>
                <AlertTriangle className="size-3" /> Not well formed
              </Badge>
            )}
            <Badge variant="outline">{plural(data.authored.length, 'authored shape')}</Badge>
            <Badge variant="outline">{plural(data.generated.length, 'generated shape')}</Badge>
            <Badge variant="outline">{plural(data.signatures.length, 'signature shape')}</Badge>
            <Badge variant="outline">{plural(data.preserved.length, 'imported group')}</Badge>
            <span className="text-muted-foreground">{data.triple_count} triples</span>
            <Button variant="outline" size="xs" asChild className="ml-auto">
              <a href={shapesApi.rdfUrl(ontologyId)}>
                <Download /> shapes.ttl
              </a>
            </Button>
          </CardContent>
        </Card>

        <Card data-testid="authored-shapes">
          <CardHeader className="flex flex-row items-start justify-between gap-3">
            <div>
              <CardTitle>Authored shapes</CardTitle>
              <CardDescription>Changes are audited and increment the draft revision.</CardDescription>
            </div>
            <Button
              size="sm"
              onClick={() => setDialog({ shape: null })}
              disabled={Boolean(disabledReason) || doc.classes.length === 0}
              title={disabledReason ?? undefined}
            >
              <Plus /> New shape
            </Button>
          </CardHeader>
          <CardContent>
            {data.authored.length === 0 ? (
              <EmptyState icon={<SquareStack />} title="No authored shapes" description="Add a shape to express a rule the ontology cannot." />
            ) : (
              <ul className="space-y-2">
                {data.authored.map((shape) => (
                  <li key={shape.id} className="rounded-lg border p-3 text-sm" data-testid="authored-shape-row">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{shape.label}</span>
                      <Badge variant="outline" className={SEVERITY_STYLE[shape.severity]}>
                        {shape.severity}
                      </Badge>
                      <span className="text-xs text-muted-foreground">targets {labelOf(doc, shape.target_class_id)}</span>
                      {shape.deactivated && <Badge variant="secondary">Deactivated</Badge>}
                      <div className="ml-auto flex gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Edit shape ${shape.label}`}
                          disabled={Boolean(disabledReason)}
                          onClick={() => setDialog({ shape })}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Delete shape ${shape.label}`}
                          disabled={Boolean(disabledReason)}
                          onClick={() => setPendingDelete(shape)}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    </div>
                    {shape.message && <p className="mt-1 text-xs text-muted-foreground">“{shape.message}”</p>}
                    <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs">
                      {shape.properties.map((c) => (
                        <li key={c.id}>{describeConstraint(c, doc)}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card data-testid="preserved-shapes">
          <CardHeader className="flex flex-row items-start justify-between gap-3">
            <div>
              <CardTitle>Imported (preserved) SHACL</CardTitle>
              <CardDescription>Meta-validated on import, kept verbatim, enforced in validation and published.</CardDescription>
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={Boolean(disabledReason) || importShapes.isPending}
              title={disabledReason ?? undefined}
              onClick={() => fileRef.current?.click()}
            >
              {importShapes.isPending ? <Loader2 className="animate-spin" /> : <FileUp />} Import SHACL
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept=".ttl,.rdf,.owl,.xml,.jsonld,.nt"
              className="hidden"
              aria-label="SHACL file"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) importShapes.mutate(file)
              }}
            />
          </CardHeader>
          <CardContent>
            {data.preserved.length === 0 ? (
              <p className="text-sm text-muted-foreground">No imported shapes.</p>
            ) : (
              <ul className="space-y-2">
                {data.preserved.map((p) => (
                  <li key={p.axiom_id} className="rounded-lg border p-2.5 text-xs" data-testid="preserved-shape-row">
                    <div className="flex items-center gap-1.5">
                      <Badge variant="outline">SHACL</Badge>
                      {p.orphaned && <Badge variant="destructive">Orphaned</Badge>}
                      <span className="font-mono break-all">{p.summary}</span>
                    </div>
                    <details className="mt-1">
                      <summary className="cursor-pointer text-muted-foreground">N-Triples</summary>
                      <pre className="mt-1 overflow-auto rounded border bg-muted/40 p-2 font-mono text-[10px]">{p.ntriples}</pre>
                    </details>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="space-y-6">
        <SampleValidationCard ontologyId={ontologyId} revision={data.draft_revision} />
        <Card data-testid="generated-shapes">
          <CardHeader>
            <CardTitle>Generated shapes</CardTitle>
            <CardDescription>Read-only. Edit the attribute switches, datatypes and ranges in the designer to change them.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.generated.map((shape) => (
              <details key={shape.iri} className="rounded-lg border p-2.5 text-sm">
                <summary className="cursor-pointer font-medium">
                  {labelOf(doc, shape.target_class_id)}{' '}
                  <span className="text-xs font-normal text-muted-foreground">({plural(shape.constraints.length, 'constraint')})</span>
                </summary>
                <table className="mt-2 w-full text-xs">
                  <thead className="text-left text-muted-foreground">
                    <tr>
                      <th className="py-1 font-normal">Property</th>
                      <th className="font-normal">Value</th>
                      <th className="font-normal">Min</th>
                      <th className="font-normal">Max</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shape.constraints.map((c) => (
                      <tr key={c.iri} className="border-t">
                        <td className="py-1">{c.property_label}</td>
                        <td className="font-mono">{c.datatype ? `xsd:${c.datatype}` : c.class_id ? labelOf(doc, c.class_id) : '—'}</td>
                        <td>{c.min_count ?? '—'}</td>
                        <td>{c.max_count ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            ))}
            <p className="pt-1 text-xs text-muted-foreground">
              {plural(data.signatures.length, 'signature shape')} (sh:targetSubjectsOf / sh:targetObjectsOf + sh:class) are
              generated from domains and ranges and enforced only by validation policies that delegate signatures to SHACL.
            </p>
          </CardContent>
        </Card>
      </div>

      {dialog && (
        <ShapeDialog
          doc={doc}
          initial={dialog.shape ? { ...dialog.shape } : emptyInput(doc)}
          onClose={() => {
            setDialog(null)
            save.reset()
          }}
          onSave={(value) => save.mutate({ id: dialog.shape?.id ?? null, value })}
          saving={save.isPending}
          error={save.error}
        />
      )}
      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete shape "{pendingDelete?.label}"?</AlertDialogTitle>
            <AlertDialogDescription>
              Published versions keep their shapes. The draft revision is incremented and the deletion is audited.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => pendingDelete && remove.mutate(pendingDelete)}>
              Delete shape
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
