import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from 'cn'

import { Button } from '@/components/ui/button'

/**
 * Non-modal right-side panel used for inspecting and editing details while keeping the
 * main canvas visible and interactive.
 */
export function RightDrawer({
  title,
  subtitle,
  badge,
  onClose,
  children,
  footer,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  badge?: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  className?: string
}) {
  return (
    <aside
      aria-label="Details panel"
      className={cn(
        'flex h-full w-[380px] shrink-0 flex-col border-l bg-background animate-in slide-in-from-right-4 duration-150',
        className,
      )}
    >
      <header className="flex items-start gap-3 border-b px-5 py-4">
        <div className="min-w-0 flex-1">
          {badge && <div className="mb-1.5">{badge}</div>}
          <h2 className="truncate text-base font-semibold">{title}</h2>
          {subtitle && <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close panel">
          <X />
        </Button>
      </header>
      <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
      {footer && <footer className="border-t px-5 py-3">{footer}</footer>}
    </aside>
  )
}

export function DrawerSection({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="space-y-3 border-t pt-4 first:border-t-0 first:pt-0 [&+section]:mt-5">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}
