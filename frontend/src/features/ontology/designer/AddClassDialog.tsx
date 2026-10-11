import { useState, type FormEvent } from 'react'
import { X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { ClassDefinition } from '@/lib/api/types'
import { LOCAL_NAME_PATTERN, newElementId, toClassLocalName } from '@/lib/naming'
import { findLocalNameOwner, type DraftDoc } from '../draft/model'
import { ClassSelect, Field } from './fields'

export function AddClassDialog({
  open,
  onOpenChange,
  doc,
  onCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  doc: DraftDoc
  onCreate: (value: ClassDefinition) => void
}) {
  const [label, setLabel] = useState('')
  const [localName, setLocalName] = useState('')
  const [localNameEdited, setLocalNameEdited] = useState(false)
  const [description, setDescription] = useState('')
  const [parentId, setParentId] = useState<string | null>(null)

  const effectiveLocalName = localNameEdited ? localName : label.trim() ? toClassLocalName(label) : ''
  const owner = effectiveLocalName ? findLocalNameOwner(doc, effectiveLocalName) : undefined
  const invalidName = effectiveLocalName !== '' && !LOCAL_NAME_PATTERN.test(effectiveLocalName)
  const canSubmit = label.trim() !== '' && effectiveLocalName !== '' && !owner && !invalidName

  const reset = () => {
    setLabel('')
    setLocalName('')
    setLocalNameEdited(false)
    setDescription('')
    setParentId(null)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return
    onCreate({
      id: newElementId('cls'),
      label: label.trim(),
      local_name: effectiveLocalName,
      description: description.trim(),
      aliases: [],
      parent_ids: parentId ? [parentId] : [],
    })
    reset()
    onOpenChange(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset()
        onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>Add class</DialogTitle>
            <DialogDescription>Classes represent the business concepts of the domain.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <Field id="new-class-label" label="Label">
              <Input
                id="new-class-label"
                autoFocus
                value={label}
                placeholder="e.g. Inventory Lot"
                onChange={(e) => setLabel(e.target.value)}
              />
            </Field>
            <Field
              id="new-class-local-name"
              label="Local name (IRI)"
              hint={`${doc.metadata.namespace}${effectiveLocalName || '…'}`}
              warning={
                owner
                  ? `Already used by "${owner.label}".`
                  : invalidName
                    ? 'Use letters, digits, "_" or "-", starting with a letter.'
                    : undefined
              }
            >
              <Input
                id="new-class-local-name"
                className="font-mono"
                value={effectiveLocalName}
                onChange={(e) => {
                  setLocalNameEdited(true)
                  setLocalName(e.target.value)
                }}
              />
            </Field>
            <Field id="new-class-description" label="Definition">
              <Textarea
                id="new-class-description"
                rows={3}
                value={description}
                placeholder="What does this concept mean to the business?"
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>
            <Field id="new-class-parent" label="Parent class (optional)">
              <div className="flex gap-2">
                <ClassSelect
                  id="new-class-parent"
                  classes={doc.classes}
                  value={parentId}
                  onChange={setParentId}
                  placeholder="None (top-level class)"
                />
                {parentId && (
                  <Button type="button" variant="ghost" size="icon" onClick={() => setParentId(null)} aria-label="Clear parent">
                    <X />
                  </Button>
                )}
              </div>
            </Field>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              Add class
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
