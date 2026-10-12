import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Brain, FileCheck2, Loader2, Shapes, ShieldAlert, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { errorMessage } from '@/lib/api/client'
import { semanticsApi, shapesApi } from '@/lib/api/endpoints'
import { queryKeys } from '@/lib/query'

/**
 * The validation lanes besides structural validation, shown side by side but never merged:
 * SHACL shape well-formedness (gates publication), OWL 2 RL reasoning (informational) and
 * evidence validation (per fact, in knowledge-graph builds).
 */
export function SemanticLanes({ projectId, ontologyId, revision }: { projectId: string; ontologyId: string; revision: number }) {
  const [reason, setReason] = useState(false)
  const shapes = useQuery({ queryKey: queryKeys.shapes(ontologyId), queryFn: () => shapesApi.overview(ontologyId) })
  const entailments = useQuery({
    queryKey: queryKeys.entailments(ontologyId, revision),
    queryFn: () => semanticsApi.entailments(ontologyId),
    enabled: reason,
  })
  const tab = (name: string) => `/projects/${projectId}/ontology?${new URLSearchParams({ ontology: ontologyId, tab: name }).toString()}`
  const overview = shapes.data

  return (
    <section className="space-y-3" aria-label="Other validation lanes">
      <div>
        <h2 className="text-lg font-semibold">Other validation lanes</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Each lane answers a different question and is reported separately: structural validation (above) checks the
          model, SHACL checks the shapes that will validate data, OWL reasoning shows what the axioms imply, and evidence
          validation checks every extracted fact against its source in knowledge-graph builds.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card size="sm" data-testid="lane-shacl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Shapes className="size-4" /> SHACL shapes
            </CardTitle>
            <CardDescription>SHACL-SHACL well-formedness of the shapes in the next package. Malformed shapes block publication.</CardDescription>
            <CardAction>
              <Button size="xs" variant="ghost" asChild>
                <Link to={tab('shapes')}>
                  Open <ArrowRight />
                </Link>
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {shapes.isPending ? (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Checking shapes…
              </p>
            ) : shapes.isError ? (
              <p className="text-destructive">{errorMessage(shapes.error)}</p>
            ) : overview ? (
              <>
                <p className="flex items-center gap-2 font-medium" data-testid="lane-shacl-status">
                  {overview.check.well_formed ? (
                    <ShieldCheck className="size-4 text-emerald-600" />
                  ) : (
                    <ShieldAlert className="size-4 text-red-600" />
                  )}
                  {overview.check.well_formed ? 'Well-formed' : 'Not well-formed'}
                </p>
                {!overview.check.well_formed && <p className="text-xs text-red-700">{overview.check.message}</p>}
                <div className="flex flex-wrap gap-1 text-[11px]">
                  <Badge variant="outline">{overview.authored.length} authored</Badge>
                  <Badge variant="outline">{overview.generated.length} generated</Badge>
                  <Badge variant="outline">{overview.signatures.length} signature</Badge>
                  <Badge variant="outline">{overview.preserved.length} preserved</Badge>
                </div>
                <p className="text-xs text-muted-foreground">Revision {overview.draft_revision} · {overview.triple_count} triples</p>
              </>
            ) : null}
          </CardContent>
        </Card>

        <Card size="sm" data-testid="lane-reasoning">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Brain className="size-4" /> OWL 2 RL reasoning
            </CardTitle>
            <CardDescription>Informational: implied statements and inconsistencies. Never blocks publication or changes data.</CardDescription>
            <CardAction>
              <Button size="xs" variant="ghost" asChild>
                <Link to={tab('semantics')}>
                  Open <ArrowRight />
                </Link>
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {!reason ? (
              <Button size="sm" variant="outline" onClick={() => setReason(true)} data-testid="lane-reasoning-run">
                <Brain /> Run reasoning check (r{revision})
              </Button>
            ) : entailments.isPending ? (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Reasoning…
              </p>
            ) : entailments.isError ? (
              <p className="text-destructive">{errorMessage(entailments.error)}</p>
            ) : (
              <>
                <p className="flex items-center gap-2 font-medium" data-testid="lane-reasoning-status">
                  {entailments.data.inconsistencies.length === 0 ? (
                    <ShieldCheck className="size-4 text-emerald-600" />
                  ) : (
                    <ShieldAlert className="size-4 text-amber-600" />
                  )}
                  {entailments.data.inconsistencies.length === 0
                    ? 'No inconsistency found'
                    : `${entailments.data.inconsistencies.length} inconsistenc${entailments.data.inconsistencies.length === 1 ? 'y' : 'ies'}`}
                </p>
                <ul className="list-inside list-disc text-xs text-amber-800">
                  {entailments.data.inconsistencies.slice(0, 3).map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground">
                  {entailments.data.entailments.length} named entailment(s) · {entailments.data.inferred_triples} inferred triples ·{' '}
                  {entailments.data.engine}
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card size="sm" data-testid="lane-evidence">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <FileCheck2 className="size-4" /> Evidence validation
            </CardTitle>
            <CardDescription>
              Runs per extracted fact in knowledge-graph builds: every fact needs a traceable source that states it.
            </CardDescription>
            <CardAction>
              <Button size="xs" variant="ghost" asChild>
                <Link to={`/projects/${projectId}/knowledge-graph?tab=facts`}>
                  Open <ArrowRight />
                </Link>
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Results appear in Knowledge Graph Studio → Fact Validation, next to the structural and SHACL lanes of each fact.
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
