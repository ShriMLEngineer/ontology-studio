import { useState } from 'react'
import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Plus, Trash2, X } from 'lucide-react'
import { cn } from 'cn'

import { DrawerSection, RightDrawer } from '@/components/common/RightDrawer'
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
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { plural } from '@/lib/format'
import { LOCAL_NAME_PATTERN, newElementId } from '@/lib/naming'
import { XSD_DATATYPES, type ClassDefinition, type DatatypePropertyDefinition, type ValidationIssue, type XsdDatatype } from '@/lib/api/types'
import {
  classDependents,
  descendantIds,
  findLocalNameOwner,
  iriHint,
  type DraftAction,
  type DraftDoc,
  type ElementSelection,
} from '../draft/model'
import { ClassSemanticsEditor, DatatypePropertySemanticsEditor, IriStatus } from './AdvancedSemantics'
import { AliasEditor, ClassSelect, Field } from './fields'
import { IssueList } from './IssueList'

type Dispatch = (action: DraftAction) => void

function localNameWarning(doc: DraftDoc, localName: string, id: string): string | undefined {
  if (!localName.trim()) return 'Local name is required.'
  if (!LOCAL_NAME_PATTERN.test(localName)) return 'Use letters, digits, "_" or "-", starting with a letter.'
  const owner = findLocalNameOwner(doc, localName, id)
  return owner ? `Also used by "${owner.label}" - validation will report a duplicate.` : undefined
}

function uniqueLocalName(doc: DraftDoc, base: string): string {
  let candidate = base
  for (let i = 2; findLocalNameOwner(doc, candidate); i += 1) candidate = `${base}${i}`
  return candidate
}

export function AttributeEditor({
  doc,
  attr,
  dispatch,
  issues,
  showDomain,
}: {
  doc: DraftDoc
  attr: DatatypePropertyDefinition
  dispatch: Dispatch
  issues: ValidationIssue[]
  showDomain?: boolean
}) {
  const update = (patch: Partial<DatatypePropertyDefinition>) =>
    dispatch({ type: 'updateDatatypeProperty', id: attr.id, patch })
  const fid = (name: string) => `attr-${attr.id}-${name}`

  return (
    <div className="grid gap-3">
      <IssueList issues={issues} />
      <div className="grid grid-cols-2 gap-3">
        <Field id={fid('label')} label="Label" warning={attr.label.trim() ? undefined : 'Label is required.'}>
          <Input id={fid('label')} value={attr.label} onChange={(e) => update({ label: e.target.value })} />
        </Field>
        <Field id={fid('datatype')} label="Datatype">
          <Select value={attr.datatype} onValueChange={(value) => update({ datatype: value as XsdDatatype })}>
            <SelectTrigger id={fid('datatype')} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {XSD_DATATYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  xsd:{t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <Field id={fid('local')} label="Local name (IRI)" hint={iriHint(doc, attr)} warning={localNameWarning(doc, attr.local_name, attr.id)}>
        <Input
          id={fid('local')}
          className="font-mono"
          value={attr.local_name}
          onChange={(e) => update({ local_name: e.target.value })}
        />
      </Field>
      <IriStatus element={attr} />
      {showDomain && (
        <Field id={fid('domain')} label="Domain class">
          <ClassSelect id={fid('domain')} classes={doc.classes} value={attr.domain_id} onChange={(id) => update({ domain_id: id })} />
        </Field>
      )}
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <label className="flex items-center gap-2 text-xs">
          <Switch checked={attr.required} onCheckedChange={(required) => update({ required })} /> Required
        </label>
        <label className="flex items-center gap-2 text-xs">
          <Switch checked={attr.multi_valued} onCheckedChange={(multi_valued) => update({ multi_valued })} /> Multi-valued
        </label>
      </div>
      <Field id={fid('description')} label="Definition">
        <Textarea
          id={fid('description')}
          rows={2}
          value={attr.description}
          onChange={(e) => update({ description: e.target.value })}
        />
      </Field>
      <DatatypePropertySemanticsEditor doc={doc} attr={attr} dispatch={dispatch} />
    </div>
  )
}

export function ClassInspector({
  doc,
  cls,
  dispatch,
  onSelect,
  onClose,
  onAddRelationship,
  issuesFor,
  issuesStale,
  initialAttributeId,
}: {
  doc: DraftDoc
  cls: ClassDefinition
  dispatch: Dispatch
  onSelect: (selection: ElementSelection) => void
  onClose: () => void
  onAddRelationship: (domainId: string) => void
  issuesFor: (id: string) => ValidationIssue[]
  issuesStale: boolean
  initialAttributeId?: string
}) {
  const [expanded, setExpanded] = useState<string | null>(initialAttributeId ?? null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const update = (patch: Partial<ClassDefinition>) => dispatch({ type: 'updateClass', id: cls.id, patch })

  const dependents = classDependents(doc, cls.id)
  const excludedParents = new Set([cls.id, ...descendantIds(doc, cls.id), ...cls.parent_ids])
  const attributes = doc.datatype_properties.filter((p) => p.domain_id === cls.id)
  const outgoing = doc.object_properties.filter((p) => p.domain_id === cls.id)
  const incoming = doc.object_properties.filter((p) => p.range_id === cls.id && p.domain_id !== cls.id)
  const className = (id: string | null) => doc.classes.find((c) => c.id === id)?.label ?? 'Unknown class'

  const addAttribute = () => {
    const attr: DatatypePropertyDefinition = {
      id: newElementId('dp'),
      label: 'new attribute',
      local_name: uniqueLocalName(doc, 'newAttribute'),
      description: '',
      aliases: [],
      domain_id: cls.id,
      datatype: 'string',
      required: false,
      multi_valued: false,
    }
    dispatch({ type: 'addDatatypeProperty', value: attr })
    setExpanded(attr.id)
  }

  return (
    <RightDrawer
      title={cls.label || 'Untitled class'}
      subtitle={`${doc.metadata.prefix}:${cls.local_name}`}
      badge={<Badge variant="secondary">Class</Badge>}
      onClose={onClose}
      footer={
        <Button variant="destructive" size="sm" onClick={() => setConfirmDelete(true)}>
          <Trash2 /> Delete class
        </Button>
      }
    >
      <DrawerSection title="Definition">
        <IssueList issues={issuesFor(cls.id)} stale={issuesStale} />
        <Field id="class-label" label="Label" warning={cls.label.trim() ? undefined : 'Label is required.'}>
          <Input id="class-label" value={cls.label} onChange={(e) => update({ label: e.target.value })} />
        </Field>
        <Field
          id="class-local-name"
          label="Local name (IRI)"
          hint={iriHint(doc, cls)}
          warning={localNameWarning(doc, cls.local_name, cls.id)}
        >
          <Input
            id="class-local-name"
            className="font-mono"
            value={cls.local_name}
            onChange={(e) => update({ local_name: e.target.value })}
          />
        </Field>
        <IriStatus element={cls} />
        <Field id="class-description" label="Definition">
          <Textarea
            id="class-description"
            rows={4}
            value={cls.description}
            placeholder="Business definition agreed by subject-matter experts"
            onChange={(e) => update({ description: e.target.value })}
          />
        </Field>
        <Field id="class-aliases" label="Aliases & synonyms">
          <AliasEditor id="class-aliases" value={cls.aliases} onChange={(aliases) => update({ aliases })} />
        </Field>
      </DrawerSection>

      <DrawerSection title="Hierarchy">
        <Field id="class-parent" label="Subclass of">
          {cls.parent_ids.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {cls.parent_ids.map((pid) => (
                <Badge key={pid} variant="outline" className="gap-1 pr-1">
                  <button type="button" className="hover:underline" onClick={() => onSelect({ kind: 'class', id: pid })}>
                    {className(pid)}
                  </button>
                  <button
                    type="button"
                    className="rounded-full p-0.5 hover:bg-foreground/10"
                    aria-label={`Remove parent ${className(pid)}`}
                    onClick={() => update({ parent_ids: cls.parent_ids.filter((p) => p !== pid) })}
                  >
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}
          <ClassSelect
            id="class-parent"
            classes={doc.classes}
            value={null}
            exclude={excludedParents}
            placeholder="Add parent class…"
            onChange={(pid) => update({ parent_ids: [...cls.parent_ids, pid] })}
          />
        </Field>
        <ClassSemanticsEditor doc={doc} cls={cls} dispatch={dispatch} />
        {dependents.children.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Subclasses:{' '}
            {dependents.children.map((child, i) => (
              <span key={child.id}>
                {i > 0 && ', '}
                <button type="button" className="text-foreground hover:underline" onClick={() => onSelect({ kind: 'class', id: child.id })}>
                  {child.label}
                </button>
              </span>
            ))}
          </p>
        )}
      </DrawerSection>

      <DrawerSection
        title={`Attributes (${attributes.length})`}
        action={
          <Button variant="ghost" size="xs" onClick={addAttribute}>
            <Plus /> Add attribute
          </Button>
        }
      >
        {attributes.length === 0 && <p className="text-xs text-muted-foreground">No datatype properties yet.</p>}
        <ul className="divide-y rounded-lg border">
          {attributes.map((attr) => {
            const open = expanded === attr.id
            return (
              <li key={attr.id}>
                <div className={cn('flex items-center gap-2 px-3 py-2', open && 'bg-muted/40')}>
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-sm"
                    onClick={() => setExpanded(open ? null : attr.id)}
                    aria-expanded={open}
                  >
                    {open ? <ChevronDown className="size-3.5 shrink-0" /> : <ChevronRight className="size-3.5 shrink-0" />}
                    <span className="truncate">
                      {attr.label || 'Untitled'}
                      {attr.required && <span className="text-red-500">*</span>}
                    </span>
                  </button>
                  <span className="font-mono text-[11px] text-muted-foreground">{attr.datatype}</span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Delete attribute ${attr.label}`}
                    onClick={() => dispatch({ type: 'deleteDatatypeProperty', id: attr.id })}
                  >
                    <Trash2 />
                  </Button>
                </div>
                {open && (
                  <div className="border-t px-3 py-3">
                    <AttributeEditor doc={doc} attr={attr} dispatch={dispatch} issues={issuesFor(attr.id)} />
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      </DrawerSection>

      <DrawerSection
        title={`Relationships (${outgoing.length + incoming.length})`}
        action={
          <Button variant="ghost" size="xs" onClick={() => onAddRelationship(cls.id)}>
            <Plus /> Add relationship
          </Button>
        }
      >
        {outgoing.length + incoming.length === 0 && <p className="text-xs text-muted-foreground">Not connected to other classes.</p>}
        <ul className="space-y-1">
          {outgoing.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                onClick={() => onSelect({ kind: 'object_property', id: p.id })}
              >
                <ArrowRight className="size-3.5 shrink-0 text-primary" />
                <span className="font-medium">{p.label}</span>
                <span className="truncate text-muted-foreground">{className(p.range_id)}</span>
              </button>
            </li>
          ))}
          {incoming.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                onClick={() => onSelect({ kind: 'object_property', id: p.id })}
              >
                <ArrowLeft className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="truncate text-muted-foreground">{className(p.domain_id)}</span>
                <span className="font-medium">{p.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </DrawerSection>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete class "{cls.label}"?</AlertDialogTitle>
            <AlertDialogDescription>
              {dependents.objectProperties.length + dependents.datatypeProperties.length + dependents.children.length > 0
                ? `This also removes ${plural(dependents.objectProperties.length, 'relationship')} and ${plural(
                    dependents.datatypeProperties.length,
                    'attribute',
                  )}, and detaches ${plural(dependents.children.length, 'subclass', 'subclasses')}. `
                : ''}
              The change applies to your working copy until you save the draft.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                dispatch({ type: 'deleteClass', id: cls.id })
                onClose()
              }}
            >
              Delete class
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </RightDrawer>
  )
}
