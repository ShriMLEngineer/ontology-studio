import { AlertCircle, AlertTriangle, Info } from 'lucide-react'

import type { DraftChangeSummary, Severity } from '@/lib/api/types'

export const SEVERITY_META: Record<Severity, { icon: typeof AlertCircle; className: string; label: string }> = {
  error: { icon: AlertCircle, className: 'text-red-600', label: 'Error' },
  warning: { icon: AlertTriangle, className: 'text-amber-600', label: 'Warning' },
  info: { icon: Info, className: 'text-sky-600', label: 'Info' },
}

export function describeChanges(changes: DraftChangeSummary): string {
  const parts: string[] = []
  if (changes.metadata_changed) parts.push('ontology details updated')
  const groups: [string, DraftChangeSummary['classes']][] = [
    ['class', changes.classes],
    ['relationship', changes.object_properties],
    ['attribute', changes.datatype_properties],
  ]
  for (const [noun, counts] of groups) {
    const pluralNoun = noun === 'class' ? 'classes' : `${noun}s`
    if (counts.added) parts.push(`${counts.added} ${counts.added === 1 ? noun : pluralNoun} added`)
    if (counts.updated) parts.push(`${counts.updated} ${counts.updated === 1 ? noun : pluralNoun} updated`)
    if (counts.removed) parts.push(`${counts.removed} ${counts.removed === 1 ? noun : pluralNoun} removed`)
  }
  if (!parts.length && changes.layout_changed) parts.push('diagram layout updated')
  return parts.join(' · ') || 'No changes'
}
