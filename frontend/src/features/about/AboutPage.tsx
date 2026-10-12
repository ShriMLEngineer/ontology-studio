import { useState, type ReactNode } from 'react'
import { ArrowLeft, ArrowRight, Info, Map as MapIcon } from 'lucide-react'
import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useProjectScope } from '@/features/projects/hooks'
import { ArchitectureMap } from './ArchitectureMap'
import { appHref, AT_A_GLANCE, SECTIONS, type SectionId } from './content'
import { LifecycleExplorer } from './LifecycleExplorer'
import { LiveSystem } from './LiveSystem'
import { Overview } from './Overview'
import { ProductTour } from './ProductTour'
import { SectionNav } from './SectionNav'
import { TechnologyStack, type TechFilter } from './TechnologyStack'
import { PAGE_END_ID, PAGE_TOP_ID, useSectionNav } from './useSectionNav'

const SECTION_IDS: SectionId[] = SECTIONS.map((section) => section.id)

function NetworkBackdrop({ className }: { className?: string }) {
  const nodes: [number, number][] = [
    [40, 70],
    [150, 30],
    [270, 90],
    [215, 190],
    [95, 165],
    [300, 225],
  ]
  return (
    <svg viewBox="0 0 340 260" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true" className={className}>
      <path d="M40 70 150 30 270 90 215 190 95 165Z" />
      <path d="M150 30 215 190M40 70 95 165M270 90 95 165M215 190 300 225" strokeDasharray="4 5" />
      {nodes.map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r="9" fill="currentColor" stroke="none" />
      ))}
    </svg>
  )
}

function Hero({ projectId, onJump }: { projectId: string; onJump: (id: string) => void }) {
  return (
    <header
      id={PAGE_TOP_ID}
      className="relative overflow-hidden rounded-2xl border bg-gradient-to-br from-primary/10 via-background to-background p-6 lg:p-10"
    >
      <NetworkBackdrop className="pointer-events-none absolute -top-4 -right-4 hidden h-72 w-auto text-primary/20 md:block" />
      <div className="relative max-w-3xl">
        <Badge variant="secondary">
          <Info /> About
        </Badge>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight lg:text-4xl">Ontology Lifecycle Studio</h1>
        <p className="mt-3 text-base text-muted-foreground">
          A governed workspace where AI, domain experts and deterministic engineering rules build ontologies together, then turn source
          data into validated, traceable knowledge graphs.
        </p>
        <blockquote className="mt-4 border-l-2 border-primary pl-3 text-sm font-medium">
          LLMs assist discovery. Domain experts govern meaning. Engineering systems enforce consistency.
        </blockquote>
        <div className="mt-6 flex flex-wrap gap-2">
          <Button onClick={() => onJump('tour')} data-testid="about-cta-tour">
            <MapIcon /> Take the tour
          </Button>
          <Button variant="outline" onClick={() => onJump('lifecycle')}>
            How it works
          </Button>
          <Button variant="outline" onClick={() => onJump('technology')}>
            Technology
          </Button>
          <Button variant="ghost" asChild>
            <Link to={appHref(projectId, { area: 'workspace' })}>
              Go to the workspace <ArrowRight />
            </Link>
          </Button>
        </div>
      </div>
      <dl className="relative mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {AT_A_GLANCE.map(({ value, label }) => (
          <div key={label} className="rounded-xl border bg-background/80 px-4 py-3">
            <dt className="sr-only">{label}</dt>
            <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
            <dd className="text-xs text-muted-foreground" aria-hidden="true">
              {label}
            </dd>
          </div>
        ))}
      </dl>
    </header>
  )
}

function AboutSection({
  id,
  title,
  description,
  onNavigate,
  children,
}: {
  id: SectionId
  title: string
  description: ReactNode
  onNavigate: (id: string) => void
  children: ReactNode
}) {
  const index = SECTIONS.findIndex((section) => section.id === id)
  const { icon: Icon } = SECTIONS[index]
  const previous = SECTIONS[index - 1]
  const next = SECTIONS[index + 1]
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-16 space-y-5 lg:scroll-mt-8" data-testid={`about-section-${id}`}>
      <div className="flex items-start gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon className="size-5" />
        </div>
        <div className="min-w-0">
          <h2 id={`${id}-title`} className="text-xl font-semibold tracking-tight">
            {title}
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{description}</p>
        </div>
      </div>
      {children}
      <div className="flex items-center justify-between gap-2 border-t pt-3">
        {previous ? (
          <Button variant="ghost" size="sm" onClick={() => onNavigate(previous.id)}>
            <ArrowLeft /> {previous.label}
          </Button>
        ) : (
          <span />
        )}
        {next && (
          <Button variant="ghost" size="sm" onClick={() => onNavigate(next.id)}>
            Next: {next.label} <ArrowRight />
          </Button>
        )}
      </div>
    </section>
  )
}

export function AboutPage() {
  const { projectId } = useProjectScope()
  const { active, scrollTo } = useSectionNav(SECTION_IDS)
  const [techFilter, setTechFilter] = useState<TechFilter>({ query: '', category: 'all' })

  const showTechnology = (name: string) => {
    setTechFilter({ query: name, category: 'all' })
    scrollTo('technology')
  }

  return (
    <div className="mx-auto w-full max-w-7xl p-6 lg:p-8" data-testid="about-page">
      <Hero projectId={projectId} onJump={scrollTo} />

      <div className="mt-6 grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:mt-8 lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-10">
        <SectionNav active={active} onSelect={scrollTo} />

        <div className="min-w-0 space-y-16">
          <AboutSection
            id="overview"
            title="What is Ontology Lifecycle Studio?"
            description="A web application for building and governing ontologies and for turning source data into validated, traceable knowledge graphs. The approved ontology is a long-lived asset: knowledge graphs are built against its immutable, published versions."
            onNavigate={scrollTo}
          >
            <Overview projectId={projectId} />
          </AboutSection>

          <AboutSection
            id="lifecycle"
            title="How it works"
            description="Two connected lifecycles share one governed path. Select a stage to see what happens there, what is guaranteed and where to do the work."
            onNavigate={scrollTo}
          >
            <LifecycleExplorer projectId={projectId} />
          </AboutSection>

          <AboutSection
            id="tour"
            title="Product tour"
            description="Every area of the application and the capabilities inside it. Each card opens the exact screen."
            onNavigate={scrollTo}
          >
            <ProductTour projectId={projectId} />
          </AboutSection>

          <AboutSection
            id="architecture"
            title="Architecture"
            description="A React single-page application talks to a FastAPI modular monolith, which stores data, calls LLM providers and deploys to graph databases. Select a component to explore it."
            onNavigate={scrollTo}
          >
            <ArchitectureMap projectId={projectId} onTechnology={showTechnology} />
          </AboutSection>

          <AboutSection
            id="technology"
            title="Technology"
            description="The frontend, the backend, the canvas and graph libraries, the semantic-web toolchain and the stores behind the studio. Search or filter by category."
            onNavigate={scrollTo}
          >
            <TechnologyStack filter={techFilter} onFilterChange={setTechFilter} />
          </AboutSection>

          <AboutSection
            id="system"
            title="Live system"
            description="Real status of this running instance, read from the same endpoints as the status badge in the header."
            onNavigate={scrollTo}
          >
            <LiveSystem projectId={projectId} />
          </AboutSection>

          <div id={PAGE_END_ID} aria-hidden="true" className="h-px" />
        </div>
      </div>
    </div>
  )
}
