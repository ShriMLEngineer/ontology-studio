import type { ProposalElementKind, ProposalStatus, ProposalType } from '@/lib/api/types'

export const PROPOSAL_TYPE_META: Record<ProposalType, { label: string; className: string; description: string }> = {
  add: {
    label: 'Add',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    description: 'Adds a new element to the draft.',
  },
  reuse: {
    label: 'Reuse',
    className: 'border-slate-200 bg-slate-100 text-slate-700',
    description: 'The source concept is already covered; approving records coverage without changing the draft.',
  },
  alias: {
    label: 'Alias',
    className: 'border-sky-200 bg-sky-50 text-sky-700',
    description: 'Adds a synonym to an existing element.',
  },
  modify: {
    label: 'Modify',
    className: 'border-amber-200 bg-amber-50 text-amber-800',
    description: 'Changes fields of an existing element.',
  },
  conflict: {
    label: 'Conflict',
    className: 'border-red-200 bg-red-50 text-red-700',
    description: 'The source contradicts the ontology. Resolve by editing the proposed change, or reject it.',
  },
}

export const STATUS_META: Record<ProposalStatus, { label: string; className: string }> = {
  pending: { label: 'Pending review', className: 'border-slate-200 bg-white text-slate-700' },
  needs_refinement: { label: 'Needs refinement', className: 'border-amber-300 bg-amber-50 text-amber-800' },
  approved: { label: 'Approved', className: 'border-emerald-300 bg-emerald-50 text-emerald-800' },
  rejected: { label: 'Rejected', className: 'border-red-200 bg-red-50 text-red-700' },
  applied: { label: 'Applied', className: 'border-primary/30 bg-primary/10 text-primary' },
}

export const KIND_LABEL: Record<ProposalElementKind, string> = {
  class: 'Class',
  object_property: 'Relationship',
  datatype_property: 'Attribute',
}

export const EVENT_LABEL: Record<string, string> = {
  created: 'Proposed',
  edited: 'Edited the proposal',
  approved: 'Approved',
  rejected: 'Rejected',
  refinement_requested: 'Requested refinement',
  reopened: 'Reopened',
  commented: 'Commented',
  applied: 'Applied to the draft',
  apply_failed: 'Could not apply',
}

export const FIELD_LABEL: Record<string, string> = {
  label: 'Label',
  local_name: 'Local name (IRI)',
  description: 'Definition',
  aliases: 'Aliases',
  parent_ids: 'Parent classes',
  domain_id: 'Domain',
  range_id: 'Range',
  datatype: 'Datatype',
  required: 'Required',
  multi_valued: 'Multi-valued',
}
