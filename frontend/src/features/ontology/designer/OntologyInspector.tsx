import { DrawerSection, RightDrawer } from '@/components/common/RightDrawer'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { ValidationIssue } from '@/lib/api/types'
import type { DraftAction, DraftDoc } from '../draft/model'
import { Field } from './fields'
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
          hint="All class and property IRIs are formed as namespace + local name."
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
    </RightDrawer>
  )
}
