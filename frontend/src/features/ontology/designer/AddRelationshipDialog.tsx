import { useState, type FormEvent } from 'react'
import { ArrowRight } from 'lucide-react'

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
import type { ObjectPropertyDefinition } from '@/lib/api/types'
import { LOCAL_NAME_PATTERN, newElementId, toPropertyLocalName } from '@/lib/naming'
import { findLocalNameOwner, type DraftDoc } from '../draft/model'
import { ClassSelect, Field } from './fields'

export interface RelationshipPrefill {
  domainId?: string
  rangeId?: string
}

/** Mount with a fresh ``key`` per opening so the form starts from the given prefill. */
export function AddRelationshipDialog({
  open,
  onOpenChange,
  doc,
  prefill,
  onCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  doc: DraftDoc
  prefill: RelationshipPrefill
  onCreate: (value: ObjectPropertyDefinition) => void
}) {
  const [label, setLabel] = useState('')
  const [localName, setLocalName] = useState('')
  const [localNameEdited, setLocalNameEdited] = useState(false)
  const [description, setDescription] = useState('')
  const [domainId, setDomainId] = useState<string | null>(prefill.domainId ?? null)
  const [rangeId, setRangeId] = useState<string | null>(prefill.rangeId ?? null)

  const effectiveLocalName = localNameEdited ? localName : label.trim() ? toPropertyLocalName(label) : ''
  const owner = effectiveLocalName ? findLocalNameOwner(doc, effectiveLocalName) : undefined
  const invalidName = effectiveLocalName !== '' && !LOCAL_NAME_PATTERN.test(effectiveLocalName)
  const canSubmit = label.trim() !== '' && effectiveLocalName !== '' && !owner && !invalidName && domainId && rangeId

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return
    onCreate({
      id: newElementId('op'),
      label: label.trim(),
      local_name: effectiveLocalName,
      description: description.trim(),
      aliases: [],
      domain_id: domainId,
      range_id: rangeId,
    })
    onOpenChange(false)
  }

  const domainLabel = doc.classes.find((c) => c.id === domainId)?.label
  const rangeLabel = doc.classes.find((c) => c.id === rangeId)?.label

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>Add relationship</DialogTitle>
            <DialogDescription>
              A directed object property from a domain class to a range class.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-2">
              <Field id="new-rel-domain" label="Domain (from)">
                <ClassSelect id="new-rel-domain" classes={doc.classes} value={domainId} onChange={setDomainId} />
              </Field>
              <ArrowRight className="mb-2 size-4 text-muted-foreground" />
              <Field id="new-rel-range" label="Range (to)">
                <ClassSelect id="new-rel-range" classes={doc.classes} value={rangeId} onChange={setRangeId} />
              </Field>
            </div>
            <Field id="new-rel-label" label="Label">
              <Input
                id="new-rel-label"
                autoFocus
                value={label}
                placeholder="e.g. held at"
                onChange={(e) => setLabel(e.target.value)}
              />
            </Field>
            <Field
              id="new-rel-local-name"
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
                id="new-rel-local-name"
                className="font-mono"
                value={effectiveLocalName}
                onChange={(e) => {
                  setLocalNameEdited(true)
                  setLocalName(e.target.value)
                }}
              />
            </Field>
            <Field id="new-rel-description" label="Definition">
              <Textarea
                id="new-rel-description"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>
            {domainLabel && rangeLabel && label.trim() && (
              <p className="rounded-md bg-muted px-3 py-2 text-xs">
                <span className="font-medium">{domainLabel}</span> — {label.trim()} →{' '}
                <span className="font-medium">{rangeLabel}</span>
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              Add relationship
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
