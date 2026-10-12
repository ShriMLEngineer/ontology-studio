import { useState, type ComponentProps, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Flag, Lock, Plus, Trash2, X } from 'lucide-react'
import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import {
  CHARACTERISTICS,
  XSD_DATATYPES,
  type Characteristic,
  type ClassDefinition,
  type ClassSemantics,
  type DatatypePropertyDefinition,
  type DatatypePropertySemantics,
  type DescriptionPredicate,
  type ObjectPropertyDefinition,
  type ObjectPropertySemantics,
  type Restriction,
  type RestrictionKind,
  type XsdDatatype,
} from '@/lib/api/types'
import type { DraftAction, DraftDoc } from '../draft/model'
import { Field } from './fields'
import { useDesignerSemantics } from './semanticContext'

type Dispatch = (action: DraftAction) => void
type Option = { id: string; label: string }

const LANGUAGE_TAG = /^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$/

const CHARACTERISTIC_HELP: Record<Characteristic, { label: string; meaning: string }> = {
  functional: { label: 'Functional', meaning: 'each subject has at most one value' },
  inverse_functional: { label: 'Inverse functional', meaning: 'each value identifies at most one subject' },
  transitive: { label: 'Transitive', meaning: 'A→B and B→C imply A→C' },
  symmetric: { label: 'Symmetric', meaning: 'A→B implies B→A' },
  asymmetric: { label: 'Asymmetric', meaning: 'A→B excludes B→A' },
  reflexive: { label: 'Reflexive', meaning: 'every individual relates to itself' },
  irreflexive: { label: 'Irreflexive', meaning: 'no individual relates to itself' },
}

const RESTRICTION_KINDS: { kind: RestrictionKind; label: string }[] = [
  { kind: 'some', label: 'some (∃)' },
  { kind: 'all', label: 'only (∀)' },
  { kind: 'has_value', label: 'has value' },
  { kind: 'min', label: 'at least' },
  { kind: 'max', label: 'at most' },
  { kind: 'exact', label: 'exactly' },
]

function NativeSelect({ className, ...props }: ComponentProps<'select'>) {
  return (
    <select
      className={cn(
        'h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
        className,
      )}
      {...props}
    />
  )
}

/** Chips plus an "add" picker for a set of element references. */
function ReferenceList({
  id,
  options,
  value,
  onChange,
  placeholder,
}: {
  id: string
  options: Option[]
  value: string[]
  onChange: (next: string[]) => void
  placeholder: string
}) {
  const label = (ref: string) => options.find((o) => o.id === ref)?.label ?? `Unknown (${ref})`
  const remaining = options.filter((o) => !value.includes(o.id)).sort((a, b) => a.label.localeCompare(b.label))
  return (
    <div className="space-y-1.5">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((ref) => (
            <Badge key={ref} variant="outline" className="gap-1 pr-1">
              {label(ref)}
              <button
                type="button"
                className="rounded-full p-0.5 hover:bg-foreground/10"
                aria-label={`Remove ${label(ref)}`}
                onClick={() => onChange(value.filter((v) => v !== ref))}
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <NativeSelect id={id} value="" onChange={(e) => e.target.value && onChange([...value, e.target.value])} disabled={!remaining.length}>
        <option value="">{remaining.length ? placeholder : 'Nothing else to add'}</option>
        {remaining.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
    </div>
  )
}

/** Collapsible container; opens by default when the element already carries OWL semantics. */
function AdvancedSection({ active, children, testId }: { active: boolean; children: ReactNode; testId: string }) {
  const [open, setOpen] = useState(active)
  return (
    <section className="rounded-lg border" data-testid={testId}>
      <button
        type="button"
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-semibold tracking-wide text-muted-foreground uppercase"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        Advanced semantics (OWL)
        {active && <span className="ml-auto size-1.5 rounded-full bg-primary" aria-label="Has OWL semantics" />}
      </button>
      {open && <div className="grid gap-3 border-t px-3 py-3">{children}</div>}
    </section>
  )
}

/** IRI with its lock state and the preserved axioms that reference the element. */
export function IriStatus({ element }: { element: { id: string; iri?: string | null } }) {
  const { lockedIds, axiomCounts, latestVersion } = useDesignerSemantics()
  const locked = lockedIds.has(element.id)
  const axioms = axiomCounts.get(element.id) ?? 0
  if (!locked && !axioms) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]" data-testid="iri-status">
      {locked && (
        <Badge variant="outline" className="gap-1 border-slate-300 text-slate-700" title={element.iri ?? undefined}>
          <Lock className="size-3" /> IRI locked{latestVersion ? ` (published in v${latestVersion})` : ''}
        </Badge>
      )}
      {axioms > 0 && (
        <Badge variant="outline" className="gap-1 border-violet-300 text-violet-800" title="See Ontology Studio → RDF / OWL">
          <Flag className="size-3" /> {axioms} preserved axiom{axioms === 1 ? '' : 's'}
        </Badge>
      )}
    </div>
  )
}

function CommonSemantics<S extends { deprecated?: boolean; annotation_language?: string | null; description_predicate?: DescriptionPredicate }>({
  idPrefix,
  semantics,
  onChange,
}: {
  idPrefix: string
  semantics: S
  onChange: (patch: Partial<S>) => void
}) {
  const language = semantics.annotation_language ?? ''
  return (
    <>
      <label className="flex items-center gap-2 text-xs">
        <Switch checked={Boolean(semantics.deprecated)} onCheckedChange={(deprecated) => onChange({ deprecated } as Partial<S>)} />
        Deprecated <span className="text-muted-foreground">(owl:deprecated - kept for existing data, not for new use)</span>
      </label>
      <div className="grid grid-cols-2 gap-3">
        <Field
          id={`${idPrefix}-lang`}
          label="Annotation language"
          warning={language && !LANGUAGE_TAG.test(language) ? 'Use a language tag such as en or de-CH.' : undefined}
          hint="Tags label, definition and aliases"
        >
          <Input
            id={`${idPrefix}-lang`}
            className="font-mono"
            placeholder="none"
            value={language}
            onChange={(e) => onChange({ annotation_language: e.target.value.trim() || null } as Partial<S>)}
          />
        </Field>
        <Field id={`${idPrefix}-defpred`} label="Definition predicate">
          <NativeSelect
            id={`${idPrefix}-defpred`}
            value={semantics.description_predicate ?? 'skos:definition'}
            onChange={(e) => onChange({ description_predicate: e.target.value as DescriptionPredicate } as Partial<S>)}
          >
            <option value="skos:definition">skos:definition</option>
            <option value="rdfs:comment">rdfs:comment</option>
          </NativeSelect>
        </Field>
      </div>
    </>
  )
}

function hasSemantics(semantics: object | undefined): boolean {
  return Boolean(
    semantics &&
      Object.entries(semantics).some(([key, value]) =>
        Array.isArray(value) ? value.length > 0 : key === 'range_declared' ? value === false : key === 'description_predicate' ? value === 'rdfs:comment' : Boolean(value),
      ),
  )
}

// ------------------------------------------------------------------ classes

function describeRestriction(doc: DraftDoc, cls: ClassDefinition, r: Restriction): string {
  const prop =
    doc.object_properties.find((p) => p.id === r.property_id)?.label ??
    doc.datatype_properties.find((p) => p.id === r.property_id)?.label ??
    r.property_id
  const filler = r.class_id ? (doc.classes.find((c) => c.id === r.class_id)?.label ?? r.class_id) : r.datatype ? `xsd:${r.datatype}` : ''
  switch (r.kind) {
    case 'some':
      return `Every ${cls.label} has at least one '${prop}' that is a ${filler}.`
    case 'all':
      return `Every '${prop}' of a ${cls.label} is a ${filler}.`
    case 'has_value':
      return `Every ${cls.label} has '${prop}' = ${r.value || '…'}.`
    default: {
      const word = { min: 'at least', max: 'at most', exact: 'exactly' }[r.kind]
      return `Every ${cls.label} has ${word} ${r.cardinality ?? '…'} '${prop}'${filler ? ` that are ${filler}` : ''}.`
    }
  }
}

function defaultFiller(doc: DraftDoc, propertyId: string): Pick<Restriction, 'class_id' | 'datatype'> {
  const object = doc.object_properties.find((p) => p.id === propertyId)
  if (object) return { class_id: object.range_id ?? doc.classes[0]?.id ?? null, datatype: null }
  const data = doc.datatype_properties.find((p) => p.id === propertyId)
  return { class_id: null, datatype: data?.datatype ?? 'string' }
}

function RestrictionEditor({
  doc,
  cls,
  value,
  onChange,
}: {
  doc: DraftDoc
  cls: ClassDefinition
  value: Restriction[]
  onChange: (next: Restriction[]) => void
}) {
  const properties: (Option & { object: boolean })[] = [
    ...doc.object_properties.map((p) => ({ id: p.id, label: p.label, object: true })),
    ...doc.datatype_properties.map((p) => ({ id: p.id, label: `${p.label} (attribute)`, object: false })),
  ]
  const isObject = (id: string) => doc.object_properties.some((p) => p.id === id)
  const replace = (index: number, next: Restriction) => onChange(value.map((r, i) => (i === index ? next : r)))
  const add = () => {
    const preferred = doc.object_properties.find((p) => p.domain_id === cls.id) ?? doc.object_properties[0]
    const propertyId = preferred?.id ?? doc.datatype_properties[0]?.id
    if (!propertyId) return
    onChange([...value, { property_id: propertyId, kind: 'some', ...defaultFiller(doc, propertyId) }])
  }
  const setKind = (r: Restriction, kind: RestrictionKind): Restriction => {
    if (kind === 'some' || kind === 'all') return { property_id: r.property_id, kind, ...defaultFiller(doc, r.property_id) }
    if (kind === 'has_value') return { property_id: r.property_id, kind, value: r.value ?? '' }
    return { property_id: r.property_id, kind, cardinality: r.cardinality ?? 1, class_id: null, datatype: null }
  }
  return (
    <div className="space-y-2" data-testid="restriction-editor">
      {value.map((r, index) => (
        <div key={index} className="space-y-1.5 rounded-lg border bg-muted/20 p-2">
          <div className="grid grid-cols-[1fr_auto_auto] gap-1.5">
            <NativeSelect
              aria-label="Restricted property"
              value={r.property_id}
              onChange={(e) => replace(index, { ...setKind({ ...r, property_id: e.target.value }, r.kind), property_id: e.target.value })}
            >
              {properties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect aria-label="Restriction kind" className="w-28" value={r.kind} onChange={(e) => replace(index, setKind(r, e.target.value as RestrictionKind))}>
              {RESTRICTION_KINDS.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.label}
                </option>
              ))}
            </NativeSelect>
            <Button variant="ghost" size="icon-sm" aria-label="Remove restriction" onClick={() => onChange(value.filter((_, i) => i !== index))}>
              <Trash2 />
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {(r.kind === 'min' || r.kind === 'max' || r.kind === 'exact') && (
              <Input
                aria-label="Cardinality"
                type="number"
                min={0}
                value={r.cardinality ?? 0}
                onChange={(e) => replace(index, { ...r, cardinality: Math.max(0, Number(e.target.value) || 0) })}
              />
            )}
            {r.kind === 'has_value' && (
              <Input
                aria-label="Value"
                className="col-span-2"
                placeholder={isObject(r.property_id) ? 'Absolute IRI of an individual' : 'Literal value'}
                value={r.value ?? ''}
                onChange={(e) => replace(index, { ...r, value: e.target.value })}
              />
            )}
            {r.kind !== 'has_value' &&
              (isObject(r.property_id) ? (
                <NativeSelect
                  aria-label="Filler class"
                  className={cn(r.kind === 'some' || r.kind === 'all' ? 'col-span-2' : '')}
                  value={r.class_id ?? ''}
                  onChange={(e) => replace(index, { ...r, class_id: e.target.value || null, datatype: null })}
                >
                  {r.kind !== 'some' && r.kind !== 'all' && <option value="">any class (unqualified)</option>}
                  {doc.classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
                </NativeSelect>
              ) : (
                <NativeSelect
                  aria-label="Filler datatype"
                  className={cn(r.kind === 'some' || r.kind === 'all' ? 'col-span-2' : '')}
                  value={r.datatype ?? ''}
                  onChange={(e) => replace(index, { ...r, datatype: (e.target.value || null) as XsdDatatype | null, class_id: null })}
                >
                  {r.kind !== 'some' && r.kind !== 'all' && <option value="">any value (unqualified)</option>}
                  {XSD_DATATYPES.map((t) => (
                    <option key={t} value={t}>
                      xsd:{t}
                    </option>
                  ))}
                </NativeSelect>
              ))}
          </div>
          <p className="text-[11px] text-muted-foreground">{describeRestriction(doc, cls, r)}</p>
          {r.kind === 'has_value' && isObject(r.property_id) && !/^[a-z][a-z0-9+.-]*:\S+$/i.test(r.value ?? '') && (
            <p className="text-[11px] text-amber-700">Enter an absolute IRI; validation reports other values as errors.</p>
          )}
        </div>
      ))}
      <Button variant="outline" size="xs" onClick={add} disabled={!properties.length}>
        <Plus /> Add restriction
      </Button>
      <p className="text-[11px] text-muted-foreground">
        OWL restrictions describe what is true of every member (open world); they are not data validation. Use SHACL shapes to
        reject incomplete data.
      </p>
    </div>
  )
}

export function ClassSemanticsEditor({ doc, cls, dispatch }: { doc: DraftDoc; cls: ClassDefinition; dispatch: Dispatch }) {
  const semantics: ClassSemantics = cls.semantics ?? {}
  const update = (patch: Partial<ClassSemantics>) => dispatch({ type: 'updateClass', id: cls.id, patch: { semantics: { ...semantics, ...patch } } })
  const others = doc.classes.filter((c) => c.id !== cls.id).map((c) => ({ id: c.id, label: c.label }))
  return (
    <AdvancedSection active={hasSemantics(cls.semantics)} testId="class-semantics">
      <Field id="cls-equivalent" label="Equivalent classes" hint="owl:equivalentClass - members of one are members of the other">
        <ReferenceList id="cls-equivalent" options={others} value={semantics.equivalent_ids ?? []} onChange={(equivalent_ids) => update({ equivalent_ids })} placeholder="Add equivalent class…" />
      </Field>
      <Field id="cls-disjoint" label="Disjoint classes" hint="owl:disjointWith - nothing can be a member of both">
        <ReferenceList id="cls-disjoint" options={others} value={semantics.disjoint_ids ?? []} onChange={(disjoint_ids) => update({ disjoint_ids })} placeholder="Add disjoint class…" />
      </Field>
      <Field label="Restrictions (superclass expressions)">
        <RestrictionEditor doc={doc} cls={cls} value={semantics.restrictions ?? []} onChange={(restrictions) => update({ restrictions })} />
      </Field>
      <CommonSemantics idPrefix="cls" semantics={semantics} onChange={update} />
    </AdvancedSection>
  )
}

// ------------------------------------------------------------------ relationships and attributes

export function ObjectPropertySemanticsEditor({ doc, prop, dispatch }: { doc: DraftDoc; prop: ObjectPropertyDefinition; dispatch: Dispatch }) {
  const semantics: ObjectPropertySemantics = prop.semantics ?? {}
  const update = (patch: Partial<ObjectPropertySemantics>) =>
    dispatch({ type: 'updateObjectProperty', id: prop.id, patch: { semantics: { ...semantics, ...patch } } })
  const others = doc.object_properties.filter((p) => p.id !== prop.id).map((p) => ({ id: p.id, label: p.label }))
  const characteristics = semantics.characteristics ?? []
  return (
    <AdvancedSection active={hasSemantics(prop.semantics)} testId="relationship-semantics">
      <Field id="op-inverse" label="Inverse of" hint="owl:inverseOf - A rel B implies B inverse A">
        <NativeSelect id="op-inverse" value={semantics.inverse_id ?? ''} onChange={(e) => update({ inverse_id: e.target.value || null })}>
          <option value="">none</option>
          {others.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="op-parents" label="Sub-property of" hint="rdfs:subPropertyOf">
        <ReferenceList id="op-parents" options={others} value={semantics.parent_ids ?? []} onChange={(parent_ids) => update({ parent_ids })} placeholder="Add parent relationship…" />
      </Field>
      <Field id="op-equivalent" label="Equivalent relationships">
        <ReferenceList id="op-equivalent" options={others} value={semantics.equivalent_ids ?? []} onChange={(equivalent_ids) => update({ equivalent_ids })} placeholder="Add equivalent relationship…" />
      </Field>
      <fieldset className="space-y-1.5">
        <legend className="text-xs font-medium">Characteristics</legend>
        {CHARACTERISTICS.map((c) => (
          <label key={c} className="flex items-start gap-2 text-xs">
            <Checkbox
              className="mt-0.5"
              checked={characteristics.includes(c)}
              onCheckedChange={(checked) =>
                update({ characteristics: checked === true ? [...characteristics, c] : characteristics.filter((x) => x !== c) })
              }
              aria-label={CHARACTERISTIC_HELP[c].label}
            />
            <span>
              {CHARACTERISTIC_HELP[c].label} <span className="text-muted-foreground">- {CHARACTERISTIC_HELP[c].meaning}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <CommonSemantics idPrefix="op" semantics={semantics} onChange={update} />
    </AdvancedSection>
  )
}

export function DatatypePropertySemanticsEditor({ doc, attr, dispatch }: { doc: DraftDoc; attr: DatatypePropertyDefinition; dispatch: Dispatch }) {
  const semantics: DatatypePropertySemantics = attr.semantics ?? {}
  const update = (patch: Partial<DatatypePropertySemantics>) =>
    dispatch({ type: 'updateDatatypeProperty', id: attr.id, patch: { semantics: { ...semantics, ...patch } } })
  const others = doc.datatype_properties.filter((p) => p.id !== attr.id).map((p) => ({ id: p.id, label: p.label }))
  const idPrefix = `dp-${attr.id}`
  return (
    <AdvancedSection active={hasSemantics(attr.semantics)} testId="attribute-semantics">
      <label className="flex items-start gap-2 text-xs">
        <Switch checked={Boolean(semantics.functional)} onCheckedChange={(functional) => update({ functional })} />
        <span>
          Functional (owl:FunctionalProperty)
          <span className="block text-muted-foreground">
            An OWL axiom about meaning. "Multi-valued" above only controls the SHACL data constraint.
          </span>
        </span>
      </label>
      <label className="flex items-start gap-2 text-xs">
        <Switch checked={semantics.range_declared !== false} onCheckedChange={(range_declared) => update({ range_declared })} />
        <span>
          Declare range xsd:{attr.datatype}
          <span className="block text-muted-foreground">Off: the datatype is only a data constraint, not rdfs:range.</span>
        </span>
      </label>
      <Field id={`${idPrefix}-parents`} label="Sub-property of" hint="rdfs:subPropertyOf">
        <ReferenceList id={`${idPrefix}-parents`} options={others} value={semantics.parent_ids ?? []} onChange={(parent_ids) => update({ parent_ids })} placeholder="Add parent attribute…" />
      </Field>
      <Field id={`${idPrefix}-equivalent`} label="Equivalent attributes">
        <ReferenceList id={`${idPrefix}-equivalent`} options={others} value={semantics.equivalent_ids ?? []} onChange={(equivalent_ids) => update({ equivalent_ids })} placeholder="Add equivalent attribute…" />
      </Field>
      <CommonSemantics idPrefix={idPrefix} semantics={semantics} onChange={update} />
    </AdvancedSection>
  )
}
