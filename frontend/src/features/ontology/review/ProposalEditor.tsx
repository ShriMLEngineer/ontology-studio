import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { governanceApi } from '@/lib/api/endpoints'
import { XSD_DATATYPES, type ProposalDetail, type ProposalType, type XsdDatatype } from '@/lib/api/types'
import type { DraftDoc } from '../draft/model'
import { AliasEditor, ClassSelect, Field } from '../designer/fields'
import { KIND_LABEL, PROPOSAL_TYPE_META } from '../governance/meta'

type Values = Record<string, unknown>

const MODIFY_FIELDS: Record<string, string[]> = {
  class: ['label', 'description'],
  object_property: ['label', 'description', 'domain_id', 'range_id'],
  datatype_property: ['label', 'description', 'domain_id', 'datatype'],
}

function initialAfter(proposal: ProposalDetail): Values {
  const base: Values = { ...(proposal.target ?? {}) }
  for (const [field, change] of Object.entries(proposal.changes)) base[field] = change.after
  return base
}

export function ProposalEditor({
  proposal,
  doc,
  reviewer,
  onSaved,
  onCancel,
}: {
  proposal: ProposalDetail
  doc: DraftDoc
  reviewer: string
  onSaved: (detail: ProposalDetail) => void
  onCancel: () => void
}) {
  const kind = proposal.element_kind
  const [type, setType] = useState<ProposalType>(proposal.proposal_type)
  const [element, setElement] = useState<Values>(proposal.new_element ?? { label: proposal.term, local_name: '', description: '', aliases: [] })
  const [targetId, setTargetId] = useState<string | null>(proposal.target_element_id)
  const [alias, setAlias] = useState<string>(() => {
    const change = proposal.changes.aliases
    const before = (change?.before as string[] | undefined) ?? []
    const after = (change?.after as string[] | undefined) ?? []
    return after.find((a) => !before.includes(a)) ?? proposal.term
  })
  const [after, setAfter] = useState<Values>(() => initialAfter(proposal))
  const [comment, setComment] = useState('')

  const candidates =
    kind === 'class' ? doc.classes : kind === 'object_property' ? doc.object_properties : doc.datatype_properties
  const target = candidates.find((c) => c.id === targetId) as unknown as Values | undefined

  const save = useMutation({
    mutationFn: () => {
      const body: Parameters<typeof governanceApi.update>[1] = { actor: reviewer, comment, proposal_type: type }
      if (type === 'add') body.new_element = element
      else {
        body.target_element_id = targetId
        if (type === 'alias') body.alias = alias
        if (type === 'modify' || type === 'conflict') {
          body.after = Object.fromEntries(
            MODIFY_FIELDS[kind].filter((f) => after[f] !== undefined && after[f] !== target?.[f]).map((f) => [f, after[f]]),
          )
        }
      }
      return governanceApi.update(proposal.id, body)
    },
    onSuccess: onSaved,
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  const setEl = (patch: Values) => setElement((current) => ({ ...current, ...patch }))
  const setAf = (patch: Values) => setAfter((current) => ({ ...current, ...patch }))
  const parents = (element.parent_ids as string[] | undefined) ?? []

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border border-primary/30 bg-primary/[0.03] p-4" aria-label="Edit proposal">
      <div className="flex items-center justify-between">
        <p className="font-medium">Edit proposal</p>
        <Button type="button" variant="ghost" size="icon-sm" onClick={onCancel} aria-label="Cancel editing">
          <X />
        </Button>
      </div>

      <Field id="edit-type" label="Proposal type" hint={PROPOSAL_TYPE_META[type].description}>
        <Select value={type} onValueChange={(v) => setType(v as ProposalType)}>
          <SelectTrigger id="edit-type" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(PROPOSAL_TYPE_META) as ProposalType[]).map((t) => (
              <SelectItem key={t} value={t}>
                {PROPOSAL_TYPE_META[t].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      {type === 'add' ? (
        <div className="grid gap-3">
          <div className="grid grid-cols-2 gap-3">
            <Field id="edit-label" label="Label">
              <Input id="edit-label" value={String(element.label ?? '')} onChange={(e) => setEl({ label: e.target.value })} />
            </Field>
            <Field id="edit-local" label="Local name (IRI)">
              <Input
                id="edit-local"
                className="font-mono"
                value={String(element.local_name ?? '')}
                onChange={(e) => setEl({ local_name: e.target.value })}
              />
            </Field>
          </div>
          <Field id="edit-description" label="Definition">
            <Textarea
              id="edit-description"
              rows={3}
              value={String(element.description ?? '')}
              onChange={(e) => setEl({ description: e.target.value })}
            />
          </Field>
          <Field id="edit-aliases" label="Aliases">
            <AliasEditor
              id="edit-aliases"
              value={(element.aliases as string[] | undefined) ?? []}
              onChange={(aliases) => setEl({ aliases })}
            />
          </Field>
          {kind === 'class' && (
            <Field id="edit-parent" label="Parent class">
              <div className="flex gap-2">
                <ClassSelect
                  id="edit-parent"
                  classes={doc.classes}
                  value={parents[0] ?? null}
                  placeholder="None (top-level class)"
                  onChange={(id) => setEl({ parent_ids: [id] })}
                />
                {parents.length > 0 && (
                  <Button type="button" variant="ghost" size="icon" aria-label="Clear parent" onClick={() => setEl({ parent_ids: [] })}>
                    <X />
                  </Button>
                )}
              </div>
            </Field>
          )}
          {kind !== 'class' && (
            <Field id="edit-domain" label="Domain class">
              <ClassSelect
                id="edit-domain"
                classes={doc.classes}
                value={(element.domain_id as string | null) ?? null}
                onChange={(id) => setEl({ domain_id: id })}
              />
            </Field>
          )}
          {kind === 'object_property' && (
            <Field id="edit-range" label="Range class">
              <ClassSelect
                id="edit-range"
                classes={doc.classes}
                value={(element.range_id as string | null) ?? null}
                onChange={(id) => setEl({ range_id: id })}
              />
            </Field>
          )}
          {kind === 'datatype_property' && (
            <div className="grid grid-cols-2 items-end gap-3">
              <Field id="edit-datatype" label="Datatype">
                <Select value={String(element.datatype ?? 'string')} onValueChange={(v) => setEl({ datatype: v as XsdDatatype })}>
                  <SelectTrigger id="edit-datatype" className="w-full">
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
              <label className="flex items-center gap-2 pb-2 text-xs">
                <Switch checked={Boolean(element.required)} onCheckedChange={(required) => setEl({ required })} /> Required
              </label>
            </div>
          )}
        </div>
      ) : (
        <div className="grid gap-3">
          <Field id="edit-target" label={`Target ${KIND_LABEL[kind].toLowerCase()}`}>
            <Select value={targetId ?? ''} onValueChange={setTargetId}>
              <SelectTrigger id="edit-target" className="w-full">
                <SelectValue placeholder="Select an existing element" />
              </SelectTrigger>
              <SelectContent>
                {[...candidates]
                  .sort((a, b) => a.label.localeCompare(b.label))
                  .map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.label}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </Field>
          {type === 'alias' && (
            <Field id="edit-alias" label="Alias to add">
              <Input id="edit-alias" value={alias} onChange={(e) => setAlias(e.target.value)} />
            </Field>
          )}
          {(type === 'modify' || type === 'conflict') && (
            <>
              <Field id="edit-after-label" label="Proposed label">
                <Input id="edit-after-label" value={String(after.label ?? '')} onChange={(e) => setAf({ label: e.target.value })} />
              </Field>
              <Field id="edit-after-description" label="Proposed definition">
                <Textarea
                  id="edit-after-description"
                  rows={3}
                  value={String(after.description ?? '')}
                  onChange={(e) => setAf({ description: e.target.value })}
                />
              </Field>
              {kind !== 'class' && (
                <Field id="edit-after-domain" label="Proposed domain">
                  <ClassSelect
                    id="edit-after-domain"
                    classes={doc.classes}
                    value={(after.domain_id as string | null) ?? null}
                    onChange={(id) => setAf({ domain_id: id })}
                  />
                </Field>
              )}
              {kind === 'object_property' && (
                <Field id="edit-after-range" label="Proposed range">
                  <ClassSelect
                    id="edit-after-range"
                    classes={doc.classes}
                    value={(after.range_id as string | null) ?? null}
                    onChange={(id) => setAf({ range_id: id })}
                  />
                </Field>
              )}
              {type === 'conflict' && (
                <p className="text-xs text-muted-foreground">
                  Leave the values unchanged to approve the conflict as acknowledged without changing the ontology.
                </p>
              )}
            </>
          )}
        </div>
      )}

      <Field id="edit-comment" label="Reason for the edit (recorded in the review trail)">
        <Textarea id="edit-comment" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      {save.isError && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(save.error)}</AlertDescription>
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending || !reviewer}>
          {save.isPending && <Loader2 className="animate-spin" />}
          Save changes
        </Button>
      </div>
    </form>
  )
}
