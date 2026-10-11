import { useState } from 'react'
import { UserRound } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useReviewerName } from './reviewer'

export function ReviewerControl() {
  const [name, setName] = useReviewerName()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(name)

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) setDraft(name)
      }}
    >
      <PopoverTrigger asChild>
        <Button variant={name ? 'ghost' : 'outline'} size="sm" className={name ? '' : 'border-amber-300 text-amber-800'}>
          <UserRound />
          {name ? `Reviewer: ${name}` : 'Set reviewer name'}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72">
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (draft.trim()) {
              setName(draft)
              setOpen(false)
            }
          }}
        >
          <div>
            <p className="text-sm font-medium">Reviewer identity</p>
            <p className="text-xs text-muted-foreground">
              Recorded on decisions, comments, applied changes and publications.
            </p>
          </div>
          <Input
            autoFocus
            aria-label="Reviewer name"
            placeholder="e.g. Dana Smith"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <Button type="submit" size="sm" className="w-full" disabled={!draft.trim()}>
            Save
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  )
}
