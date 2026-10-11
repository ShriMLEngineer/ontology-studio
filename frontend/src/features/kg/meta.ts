import type { FactStatus, FactSummary, GapType } from '@/lib/api/types'

export const FACT_STATUS_META: Record<FactStatus, { label: string; className: string; description: string }> = {
  accepted: {
    label: 'Accepted',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    description: 'Passed structural and evidence validation; stored in the graph.',
  },
  rejected: {
    label: 'Rejected',
    className: 'border-red-200 bg-red-50 text-red-800',
    description: 'Failed structural validation against the ontology version, or has no evidence.',
  },
  quarantined: {
    label: 'Quarantined',
    className: 'border-amber-200 bg-amber-50 text-amber-800',
    description: 'Structurally valid but held back: inadequate evidence, ambiguity or a conflicting value.',
  },
}

export const EVIDENCE_LABEL: Record<string, string> = {
  supported: 'Supported',
  weak: 'Weak',
  unlocated: 'Not located',
  missing: 'Missing',
}

export const GAP_TYPE_LABEL: Record<GapType, string> = {
  unknown_class: 'Unknown entity type',
  unknown_relationship: 'Unknown relationship',
  unknown_attribute: 'Unknown attribute',
  unmapped_field: 'Unmapped source field',
}

export const RESOLUTION_LABEL: Record<string, string> = {
  business_key: 'Business key',
  label: 'Label match',
  alias: 'Alias match',
  new: 'New (name only)',
  ambiguous: 'Ambiguous',
  unresolved_class: 'Unknown class',
  missing_identifier: 'Missing identifier',
}

export function factStatement(
  fact: Pick<FactSummary, 'kind' | 'subject_label' | 'predicate_label' | 'object_label' | 'value'>,
): string {
  if (fact.kind === 'type') return `${fact.subject_label} is a ${fact.object_label}`
  if (fact.kind === 'attribute') return `${fact.subject_label} · ${fact.predicate_label} = ${fact.value ?? ''}`
  return `${fact.subject_label} → ${fact.predicate_label} → ${fact.object_label}`
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes} min ${Math.round(seconds % 60)} s`
}

export function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

/** Stable, readable colour per ontology class for the graph explorer. */
const PALETTE = ['#2563eb', '#059669', '#d97706', '#7c3aed', '#db2777', '#0891b2', '#65a30d', '#dc2626', '#4f46e5', '#0d9488', '#9333ea', '#ca8a04']

export function classColor(classId: string, order: string[]): string {
  const index = order.indexOf(classId)
  return PALETTE[(index >= 0 ? index : classId.length) % PALETTE.length]
}
