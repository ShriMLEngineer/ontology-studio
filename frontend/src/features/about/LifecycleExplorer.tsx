import { useState } from 'react'
import { ArrowLeft, ArrowRight, RefreshCcw, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router'
import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { appHref, LANES, LIFECYCLE, type LaneKey, type StageKey } from './content'

const LANE_KEYS = Object.keys(LANES) as LaneKey[]

function StepButton({
  number,
  label,
  optional,
  selected,
  hasNext,
  stageKey,
  onSelect,
}: {
  number: number
  label: string
  optional: boolean
  selected: boolean
  hasNext: boolean
  stageKey: StageKey
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      data-testid={`about-stage-${stageKey}`}
      onClick={onSelect}
      className={cn(
        'flex w-full items-center gap-2.5 rounded-xl border bg-background px-3 py-2.5 text-left text-sm transition outline-none hover:border-primary/50 hover:shadow-sm focus-visible:ring-3 focus-visible:ring-ring/50',
        selected && 'border-primary bg-primary/5 ring-2 ring-primary/20',
      )}
    >
      <span
        className={cn(
          'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
          selected ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
        )}
      >
        {number}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block leading-tight font-medium">{label}</span>
        {optional && <span className="block text-[10px] text-muted-foreground">optional</span>}
      </span>
      {hasNext && <ArrowRight className="size-3.5 shrink-0 text-muted-foreground/60" />}
    </button>
  )
}

/** Interactive version of the lifecycle: pick a stage to see what happens, what is guaranteed and where to do it. */
export function LifecycleExplorer({ projectId }: { projectId: string }) {
  const [selectedKey, setSelectedKey] = useState<StageKey>('discovery')
  const index = LIFECYCLE.findIndex((step) => step.key === selectedKey)
  const step = LIFECYCLE[index]
  const select = (next: number) => setSelectedKey(LIFECYCLE[next].key)

  return (
    <div className="space-y-4" data-testid="about-lifecycle">
      <div className="space-y-5 rounded-2xl border bg-card p-4 lg:p-5">
        {LANE_KEYS.map((laneKey) => {
          const lane = LANES[laneKey]
          const steps = LIFECYCLE.filter((s) => s.lane === laneKey)
          return (
            <div key={laneKey}>
              <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
                <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{lane.label}</h3>
                <span className="text-xs text-muted-foreground">{lane.blurb}</span>
              </div>
              <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))]">
                {steps.map((s, i) => {
                  const position = LIFECYCLE.indexOf(s)
                  return (
                    <li key={s.key}>
                      <StepButton
                        number={position + 1}
                        label={s.label}
                        optional={Boolean(s.optional)}
                        selected={s.key === selectedKey}
                        hasNext={i < steps.length - 1}
                        stageKey={s.key}
                        onSelect={() => setSelectedKey(s.key)}
                      />
                    </li>
                  )
                })}
              </ol>
            </div>
          )
        })}
        <button
          type="button"
          onClick={() => setSelectedKey('review')}
          className="flex w-full items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-left text-xs text-muted-foreground transition outline-none hover:border-primary/50 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <RefreshCcw className="size-3.5 shrink-0" />
          <span>
            <strong className="font-medium text-foreground">Feedback loop:</strong> ontology gaps found during evaluation return to SME
            review as proposals, so the ontology evolves through the same governed path.
          </span>
        </button>
      </div>

      <Card aria-live="polite" data-testid="about-stage-detail" data-stage={step.key}>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
            <span className="text-muted-foreground">Step {index + 1} of {LIFECYCLE.length}</span>
            <span>{step.label}</span>
            <Badge variant="outline">{LANES[step.lane].label}</Badge>
            {step.optional && <Badge variant="secondary">optional</Badge>}
          </CardTitle>
          <CardDescription className="text-sm">{step.summary}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-950">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-700" />
            <div>
              <p className="font-medium">Guardrail</p>
              <p>{step.guardrail}</p>
            </div>
          </div>
        </CardContent>
        <CardFooter className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={index === 0} onClick={() => select(index - 1)}>
            <ArrowLeft /> Previous
          </Button>
          <Button variant="outline" size="sm" disabled={index === LIFECYCLE.length - 1} onClick={() => select(index + 1)}>
            Next <ArrowRight />
          </Button>
          <Button size="sm" className="ml-auto" asChild>
            <Link to={appHref(projectId, step.link)}>
              {step.link.label} <ArrowRight />
            </Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
