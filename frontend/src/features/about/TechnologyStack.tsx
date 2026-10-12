import { useMemo } from 'react'
import { SearchX, Search, X } from 'lucide-react'
import { cn } from 'cn'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { TECH_CATEGORIES, TECHNOLOGIES, type TechCategory, type Technology } from './content'

export interface TechFilter {
  query: string
  category: TechCategory | 'all'
}

const ALL_TECHNOLOGIES: readonly Technology[] = Object.values(TECHNOLOGIES)
const CATEGORY_KEYS = Object.keys(TECH_CATEGORIES) as TechCategory[]

function matches(tech: Technology, filter: TechFilter): boolean {
  if (filter.category !== 'all' && tech.category !== filter.category) return false
  const query = filter.query.trim().toLowerCase()
  if (!query) return true
  return `${tech.name} ${tech.role} ${tech.usage} ${TECH_CATEGORIES[tech.category].label}`.toLowerCase().includes(query)
}

/** Filterable catalogue of every framework, library and standard the studio is built on. */
export function TechnologyStack({ filter, onFilterChange }: { filter: TechFilter; onFilterChange: (filter: TechFilter) => void }) {
  const visible = useMemo(() => ALL_TECHNOLOGIES.filter((tech) => matches(tech, filter)), [filter])
  const countFor = (category: TechCategory | 'all') =>
    category === 'all' ? ALL_TECHNOLOGIES.length : ALL_TECHNOLOGIES.filter((tech) => tech.category === category).length
  const filtered = filter.query.trim() !== '' || filter.category !== 'all'

  return (
    <div className="space-y-4" data-testid="about-technology">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={filter.query}
            onChange={(event) => onFilterChange({ ...filter, query: event.target.value })}
            placeholder="Search technologies…"
            aria-label="Search technologies"
            className="pr-8 pl-8"
            data-testid="about-tech-search"
          />
          {filter.query && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => onFilterChange({ ...filter, query: '' })}
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              <X className="size-4" />
            </button>
          )}
        </div>
        <p className="text-xs text-muted-foreground" aria-live="polite" data-testid="about-tech-count">
          Showing {visible.length} of {ALL_TECHNOLOGIES.length} technologies
        </p>
      </div>

      <div role="group" aria-label="Filter by category" className="flex flex-wrap gap-1.5">
        {(['all', ...CATEGORY_KEYS] as const).map((key) => {
          const selected = filter.category === key
          const label = key === 'all' ? 'All' : TECH_CATEGORIES[key].label
          return (
            <button
              key={key}
              type="button"
              aria-pressed={selected}
              data-testid={`about-tech-filter-${key}`}
              onClick={() => onFilterChange({ ...filter, category: key })}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1 text-xs font-medium transition outline-none hover:border-primary/50 focus-visible:ring-3 focus-visible:ring-ring/50',
                selected && 'border-primary bg-primary/10 text-primary',
              )}
            >
              {label}
              <span className={cn('rounded-full bg-muted px-1.5 text-[10px] text-muted-foreground', selected && 'bg-primary/15 text-primary')}>
                {countFor(key)}
              </span>
            </button>
          )
        })}
      </div>

      {visible.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-8 text-center">
          <SearchX className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No technology matches the current filter.</p>
          <Button variant="outline" size="sm" onClick={() => onFilterChange({ query: '', category: 'all' })}>
            Clear filters
          </Button>
        </div>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((tech) => {
            const category = TECH_CATEGORIES[tech.category]
            const Icon = category.icon
            return (
              <li key={tech.name} className="flex" data-testid="about-tech-card">
                <div className="flex w-full flex-col gap-2 rounded-xl border bg-card p-4 transition hover:border-primary/40 hover:shadow-md">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold">{tech.name}</h3>
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                      <Icon className="size-3" />
                      {category.label}
                    </span>
                  </div>
                  <p className="text-xs font-medium text-muted-foreground">{tech.role}</p>
                  <p className="text-sm">{tech.usage}</p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {filtered && visible.length > 0 && (
        <Button variant="ghost" size="sm" onClick={() => onFilterChange({ query: '', category: 'all' })}>
          <X /> Clear filters
        </Button>
      )}
    </div>
  )
}
