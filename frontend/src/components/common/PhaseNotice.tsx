import type { ReactNode } from 'react'
import { CalendarClock } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

/**
 * Honest placeholder for capabilities scheduled in a later milestone. It describes what is
 * planned and never pretends the feature already works.
 */
export function PhaseNotice({
  phase,
  title,
  description,
  capabilities,
  children,
}: {
  phase: 2 | 3
  title: string
  description: ReactNode
  capabilities: string[]
  children?: ReactNode
}) {
  return (
    <div className="mx-auto w-full max-w-3xl rounded-xl border border-dashed bg-muted/30 p-8">
      <div className="flex items-center gap-2">
        <CalendarClock className="size-5 text-muted-foreground" />
        <Badge variant="outline">Planned · Phase {phase}</Badge>
      </div>
      <h2 className="mt-4 text-lg font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      <ul className="mt-5 grid gap-2 sm:grid-cols-2">
        {capabilities.map((capability) => (
          <li key={capability} className="flex items-start gap-2 text-sm">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
            {capability}
          </li>
        ))}
      </ul>
      <p className="mt-6 text-xs text-muted-foreground">
        This capability is not implemented yet. Nothing on this screen performs a backend operation.
      </p>
      {children}
    </div>
  )
}
