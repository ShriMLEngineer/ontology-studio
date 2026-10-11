import { useState } from 'react'
import { AlertCircle, ArrowRight, Box, Search } from 'lucide-react'
import { cn } from 'cn'

import { Input } from '@/components/ui/input'
import type { Severity } from '@/lib/api/types'
import { classLabel, type DraftDoc, type ElementSelection } from '../draft/model'
import { SEVERITY_META } from './presentation'

interface Searchable {
  label: string
  local_name: string
  aliases: string[]
}

export function ElementOutline({
  doc,
  selection,
  onSelect,
  severityById,
}: {
  doc: DraftDoc
  selection: ElementSelection | null
  onSelect: (selection: ElementSelection) => void
  severityById: Map<string, Severity>
}) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const matches = (e: Searchable) =>
    !q || e.label.toLowerCase().includes(q) || e.local_name.toLowerCase().includes(q) || e.aliases.some((a) => a.toLowerCase().includes(q))

  const classIds = new Set(doc.classes.map((c) => c.id))
  const classes = doc.classes.filter(matches).sort((a, b) => a.label.localeCompare(b.label))
  const relationships = doc.object_properties.filter(matches).sort((a, b) => a.label.localeCompare(b.label))
  const orphanAttributes = doc.datatype_properties.filter((p) => !p.domain_id || !classIds.has(p.domain_id)).filter(matches)

  const isSelected = (kind: ElementSelection['kind'], id: string) =>
    selection !== null && selection.kind === kind && 'id' in selection && selection.id === id

  const severityIcon = (id: string) => {
    const severity = severityById.get(id)
    if (!severity) return null
    const meta = SEVERITY_META[severity]
    return <meta.icon className={cn('size-3.5 shrink-0', meta.className)} aria-label={meta.label} />
  }

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r bg-background" aria-label="Ontology outline">
      <div className="border-b p-3">
        <div className="relative">
          <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search classes & relationships"
            className="h-8 pl-8 text-xs"
            aria-label="Search ontology elements"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-3">
        <p className="px-2 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
          Classes ({classes.length})
        </p>
        <ul>
          {classes.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onSelect({ kind: 'class', id: c.id })}
                className={cn(
                  'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted',
                  isSelected('class', c.id) && 'bg-primary/10 text-primary',
                )}
              >
                <Box className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="flex-1 truncate">{c.label || 'Untitled'}</span>
                {severityIcon(c.id)}
              </button>
            </li>
          ))}
        </ul>

        <p className="mt-4 px-2 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
          Relationships ({relationships.length})
        </p>
        <ul>
          {relationships.map((p) => {
            const dangling = !p.domain_id || !p.range_id || !classIds.has(p.domain_id) || !classIds.has(p.range_id)
            return (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => onSelect({ kind: 'object_property', id: p.id })}
                  className={cn(
                    'flex w-full flex-col rounded-md px-2 py-1.5 text-left hover:bg-muted',
                    isSelected('object_property', p.id) && 'bg-primary/10',
                  )}
                >
                  <span className="flex w-full items-center gap-2 text-sm">
                    <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate">{p.label || 'Untitled'}</span>
                    {dangling ? <AlertCircle className="size-3.5 text-red-600" aria-label="Not drawn: missing domain or range" /> : severityIcon(p.id)}
                  </span>
                  <span className="truncate pl-5.5 text-[11px] text-muted-foreground">
                    {classLabel(doc, p.domain_id)} → {classLabel(doc, p.range_id)}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>

        {orphanAttributes.length > 0 && (
          <>
            <p className="mt-4 px-2 pb-1 text-[11px] font-semibold tracking-wide text-red-700 uppercase">
              Attributes without a class ({orphanAttributes.length})
            </p>
            <ul>
              {orphanAttributes.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => onSelect({ kind: 'datatype_property', id: p.id })}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                  >
                    <AlertCircle className="size-3.5 shrink-0 text-red-600" />
                    <span className="truncate">{p.label || 'Untitled'}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </aside>
  )
}
