import { useState, type ReactNode } from 'react'
import { Plus, X } from 'lucide-react'
import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ClassDefinition } from '@/lib/api/types'

export function Field({
  id,
  label,
  hint,
  warning,
  children,
  className,
}: {
  id?: string
  label: string
  hint?: ReactNode
  warning?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('grid gap-1.5', className)}>
      <Label htmlFor={id} className="text-xs font-medium">
        {label}
      </Label>
      {children}
      {warning ? (
        <p className="text-xs text-amber-700" role="alert">
          {warning}
        </p>
      ) : (
        hint && <p className="text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  )
}

export function AliasEditor({ id, value, onChange }: { id?: string; value: string[]; onChange: (next: string[]) => void }) {
  const [draft, setDraft] = useState('')

  const add = () => {
    const alias = draft.trim()
    if (alias && !value.some((v) => v.toLowerCase() === alias.toLowerCase())) onChange([...value, alias])
    setDraft('')
  }

  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((alias) => (
            <Badge key={alias} variant="secondary" className="gap-1 pr-1">
              {alias}
              <button
                type="button"
                className="rounded-full p-0.5 hover:bg-foreground/10"
                aria-label={`Remove alias ${alias}`}
                onClick={() => onChange(value.filter((v) => v !== alias))}
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          id={id}
          value={draft}
          placeholder="Add synonym or alias"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
        <Button type="button" variant="outline" size="icon" onClick={add} aria-label="Add alias" disabled={!draft.trim()}>
          <Plus />
        </Button>
      </div>
    </div>
  )
}

export function ClassSelect({
  id,
  classes,
  value,
  onChange,
  placeholder = 'Select a class',
  exclude,
}: {
  id?: string
  classes: ClassDefinition[]
  value: string | null
  onChange: (id: string) => void
  placeholder?: string
  exclude?: Set<string>
}) {
  const options = [...classes].filter((c) => !exclude?.has(c.id)).sort((a, b) => a.label.localeCompare(b.label))
  const known = value ? classes.some((c) => c.id === value) : false
  return (
    <Select value={known ? value! : ''} onValueChange={onChange}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue placeholder={value && !known ? `Unknown class (${value})` : placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((c) => (
          <SelectItem key={c.id} value={c.id}>
            {c.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
