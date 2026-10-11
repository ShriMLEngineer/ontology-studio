import { Plus, X } from 'lucide-react'

import { DrawerSection, RightDrawer } from '@/components/common/RightDrawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import type { PrefixBinding, ValidationIssue } from '@/lib/api/types'
import { defaultOntologyIri, type DraftAction, type DraftDoc } from '../draft/model'
import { AliasEditor, Field } from './fields'
import { IssueList } from './IssueList'

export function OntologyInspector({
  doc,
  dispatch,
  onClose,
  issues,
  issuesStale,
}: {
  doc: DraftDoc
  dispatch: (action: DraftAction) => void
  onClose: () => void
  issues: ValidationIssue[]
  issuesStale: boolean
}) {
  const update = (patch: Partial<DraftDoc['metadata']>) => dispatch({ type: 'updateMetadata', patch })
  const { metadata } = doc
  return (
    <RightDrawer
      title={metadata.name || 'Untitled ontology'}
      subtitle={metadata.namespace}
      badge={<Badge variant="secondary">Ontology settings</Badge>}
      onClose={onClose}
    >
      <DrawerSection title="Ontology">
        <IssueList issues={issues} stale={issuesStale} />
        <Field id="ont-name" label="Name" warning={metadata.name.trim() ? undefined : 'Name is required.'}>
          <Input id="ont-name" value={metadata.name} onChange={(e) => update({ name: e.target.value })} />
        </Field>
        <Field
          id="ont-namespace"
          label="Namespace IRI"
          hint="New elements get namespace + local name as IRI. IRIs of published elements are locked."
          warning={metadata.namespace.trim() ? undefined : 'Namespace is required.'}
        >
          <Input
            id="ont-namespace"
            className="font-mono text-xs"
            value={metadata.namespace}
            onChange={(e) => update({ namespace: e.target.value })}
          />
        </Field>
        <Field id="ont-prefix" label="Prefix" warning={metadata.prefix.trim() ? undefined : 'Prefix is required.'}>
          <Input id="ont-prefix" className="font-mono" value={metadata.prefix} onChange={(e) => update({ prefix: e.target.value })} />
        </Field>
        <Field id="ont-description" label="Description">
          <Textarea
            id="ont-description"
            rows={4}
            value={metadata.description}
            onChange={(e) => update({ description: e.target.value })}
          />
        </Field>
      </DrawerSection>
      <DrawerSection title="Semantic header (OWL)">
        <Field
          id="ont-iri"
          label="Ontology IRI"
          hint={metadata.ontology_iri ? 'Explicit ontology IRI.' : 'Derived from the namespace when left empty.'}
        >
          <Input
            id="ont-iri"
            className="font-mono text-xs"
            placeholder={defaultOntologyIri(metadata.namespace)}
            value={metadata.ontology_iri ?? ''}
            onChange={(e) => update({ ontology_iri: e.target.value || null })}
          />
        </Field>
        <Field id="ont-imports" label="Imported ontologies (owl:imports)" hint="Referenced only; imported axioms are not loaded.">
          <AliasEditor id="ont-imports" value={metadata.imports ?? []} onChange={(imports) => update({ imports })} />
        </Field>
        <PrefixEditor value={metadata.prefixes ?? []} onChange={(prefixes) => update({ prefixes })} />
        <label className="flex items-start gap-3 text-sm" htmlFor="ont-domain-range">
          <Switch
            id="ont-domain-range"
            checked={metadata.require_domain_range ?? true}
            onCheckedChange={(checked) => update({ require_domain_range: checked })}
          />
          <span>
            Require domain and range
            <span className="block text-xs text-muted-foreground">
              When off, properties without a domain or range are warnings instead of blocking errors (open signatures).
            </span>
          </span>
        </label>
      </DrawerSection>
    </RightDrawer>
  )
}

function PrefixEditor({ value, onChange }: { value: PrefixBinding[]; onChange: (next: PrefixBinding[]) => void }) {
  const set = (index: number, patch: Partial<PrefixBinding>) =>
    onChange(value.map((binding, i) => (i === index ? { ...binding, ...patch } : binding)))
  return (
    <div className="grid gap-1.5">
      <span className="text-xs font-medium">Prefixes</span>
      {value.map((binding, index) => (
        <div key={index} className="flex items-center gap-1.5">
          <Input
            aria-label={`Prefix ${index + 1}`}
            className="w-20 font-mono text-xs"
            value={binding.prefix}
            onChange={(e) => set(index, { prefix: e.target.value })}
          />
          <Input
            aria-label={`Prefix ${index + 1} namespace`}
            className="font-mono text-xs"
            value={binding.namespace}
            onChange={(e) => set(index, { namespace: e.target.value })}
          />
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Remove prefix ${binding.prefix}`}
            onClick={() => onChange(value.filter((_, i) => i !== index))}
          >
            <X />
          </Button>
        </div>
      ))}
      <Button
        variant="outline"
        size="xs"
        className="w-fit"
        onClick={() => onChange([...value, { prefix: '', namespace: 'https://' }])}
      >
        <Plus /> Add prefix
      </Button>
    </div>
  )
}
