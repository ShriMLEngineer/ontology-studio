import { ArrowUp } from 'lucide-react'
import { cn } from 'cn'

import { Button } from '@/components/ui/button'
import { SECTIONS, type SectionId } from './content'
import { PAGE_TOP_ID } from './useSectionNav'

/** Sticky table of contents: a vertical rail on large screens, a scrolling chip bar on small ones. */
export function SectionNav({ active, onSelect }: { active: SectionId; onSelect: (id: string) => void }) {
  return (
    <nav
      aria-label="About sections"
      data-testid="about-nav"
      className="sticky top-0 z-20 -mx-6 min-w-0 border-b bg-background/90 px-6 py-2 backdrop-blur lg:top-8 lg:mx-0 lg:border-b-0 lg:bg-transparent lg:p-0 lg:backdrop-blur-none"
    >
      <p className="mb-2 hidden px-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase lg:block">On this page</p>
      <ol className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
        {SECTIONS.map(({ id, label, icon: Icon, blurb }) => {
          const isActive = active === id
          return (
            <li key={id} className="shrink-0">
              <a
                href={`#${id}`}
                data-testid={`about-nav-${id}`}
                aria-current={isActive ? 'location' : undefined}
                onClick={(event) => {
                  event.preventDefault()
                  onSelect(id)
                }}
                className={cn(
                  'flex items-start gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50',
                  isActive && 'bg-primary/10 text-primary hover:bg-primary/10 hover:text-primary',
                )}
              >
                <Icon className="mt-0.5 size-4 shrink-0" />
                <span className="min-w-0">
                  <span className="block whitespace-nowrap">{label}</span>
                  <span className="hidden text-xs font-normal text-muted-foreground lg:block">{blurb}</span>
                </span>
              </a>
            </li>
          )
        })}
      </ol>
      <Button
        variant="ghost"
        size="sm"
        className="mt-3 hidden w-full justify-start text-muted-foreground lg:flex"
        onClick={() => onSelect(PAGE_TOP_ID)}
      >
        <ArrowUp /> Back to top
      </Button>
    </nav>
  )
}
