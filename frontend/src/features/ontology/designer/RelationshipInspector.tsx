import { ArrowRight, Trash2 } from 'lucide-react'

import { DrawerSection, RightDrawer } from '@/components/common/RightDrawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { DatatypePropertyDefinition, ObjectPropertyDefinition, ValidationIssue } from '@/lib/api/types'
import { LOCAL_NAME_PATTERN } from '@/lib/naming'
import { classLabel, findLocalNameOwner, iriHint, type DraftAction, type DraftDoc, type ElementSelection } from '../draft/model'
import { AttributeEditor } from './ClassInspector'
import { AliasEditor, ClassSelect, Field } from './fields'
import { IssueList } from './IssueList'

export function RelationshipInspector({
  doc,
  prop,
  dispatch,
  onSelect,
  onClose,
  issues,
  issuesStale,
}: {
  doc: DraftDoc
  prop: ObjectPropertyDefinition
  dispatch: (action: DraftAction) => void
  onSelect: (selection: ElementSelection) => void
  onClose: () => void
  issues: ValidationIssue[]
  issuesStale: boolean
}) {
  const update = (patch: Partial<ObjectPropertyDefinition>) =>
    dispatch({ type: 'updateObjectProperty', id: prop.id, patch })
  const owner = findLocalNameOwner(doc, prop.local_name, prop.id)
  const nameWarning = !prop.local_name.trim()
    ? 'Local name is required.'
    : !LOCAL_NAME_PATTERN.test(prop.local_name)
      ? 'Use letters, digits, "_" or "-", starting with a letter.'
      : owner
        ? `Also used by "${owner.label}" - validation will report a duplicate.`
        : undefined

  return (
    <RightDrawer
      title={prop.label || 'Untitled relationship'}
      subtitle={`${doc.metadata.prefix}:${prop.local_name}`}
      badge={<Badge variant="secondary">Relationship · object property</Badge>}
      onClose={onClose}
      footer={
        <Button
          variant="destructive"
          size="sm"
          onClick={() => {
            dispatch({ type: 'deleteObjectProperty', id: prop.id })
            onClose()
          }}
        >
          <Trash2 /> Delete relationship
        </Button>
      }
    >
      <DrawerSection title="Direction">
        <IssueList issues={issues} stale={issuesStale} />
        <div className="flex items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2.5 text-sm">
          <button
            type="button"
            className="truncate font-medium hover:underline"
            disabled={!prop.domain_id}
            onClick={() => prop.domain_id && onSelect({ kind: 'class', id: prop.domain_id })}
          >
            {classLabel(doc, prop.domain_id)}
          </button>
          <ArrowRight className="size-4 shrink-0 text-primary" />
          <button
            type="button"
            className="truncate font-medium hover:underline"
            disabled={!prop.range_id}
            onClick={() => prop.range_id && onSelect({ kind: 'class', id: prop.range_id })}
          >
            {classLabel(doc, prop.range_id)}
          </button>
        </div>
        <Field id="rel-domain" label="Domain (subject class)">
          <ClassSelect id="rel-domain" classes={doc.classes} value={prop.domain_id} onChange={(id) => update({ domain_id: id })} />
        </Field>
        <Field id="rel-range" label="Range (object class)">
          <ClassSelect id="rel-range" classes={doc.classes} value={prop.range_id} onChange={(id) => update({ range_id: id })} />
        </Field>
      </DrawerSection>

      <DrawerSection title="Definition">
        <Field id="rel-label" label="Label" warning={prop.label.trim() ? undefined : 'Label is required.'}>
          <Input id="rel-label" value={prop.label} onChange={(e) => update({ label: e.target.value })} />
        </Field>
        <Field id="rel-local-name" label="Local name (IRI)" hint={iriHint(doc, prop)} warning={nameWarning}>
          <Input
            id="rel-local-name"
            className="font-mono"
            value={prop.local_name}
            onChange={(e) => update({ local_name: e.target.value })}
          />
        </Field>
        <Field id="rel-description" label="Definition">
          <Textarea
            id="rel-description"
            rows={3}
            value={prop.description}
            onChange={(e) => update({ description: e.target.value })}
          />
        </Field>
        <Field id="rel-aliases" label="Aliases & synonyms">
          <AliasEditor id="rel-aliases" value={prop.aliases} onChange={(aliases) => update({ aliases })} />
        </Field>
      </DrawerSection>
    </RightDrawer>
  )
}

/** Used for attributes whose domain class is missing, so they can still be repaired. */
export function AttributeInspector({
  doc,
  attr,
  dispatch,
  onClose,
  issues,
}: {
  doc: DraftDoc
  attr: DatatypePropertyDefinition
  dispatch: (action: DraftAction) => void
  onClose: () => void
  issues: ValidationIssue[]
}) {
  return (
    <RightDrawer
      title={attr.label || 'Untitled attribute'}
      subtitle={`${doc.metadata.prefix}:${attr.local_name}`}
      badge={<Badge variant="secondary">Attribute · datatype property</Badge>}
      onClose={onClose}
      footer={
        <Button
          variant="destructive"
          size="sm"
          onClick={() => {
            dispatch({ type: 'deleteDatatypeProperty', id: attr.id })
            onClose()
          }}
        >
          <Trash2 /> Delete attribute
        </Button>
      }
    >
      <AttributeEditor doc={doc} attr={attr} dispatch={dispatch} issues={issues} showDomain />
    </RightDrawer>
  )
}
