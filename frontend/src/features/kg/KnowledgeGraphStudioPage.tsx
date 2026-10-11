import { ArrowRight, CheckCircle2, Circle } from 'lucide-react'
import { Link } from 'react-router'

import { PageHeader } from '@/components/common/PageHeader'
import { PhaseNotice } from '@/components/common/PhaseNotice'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useProjectScope } from '@/features/projects/hooks'

const STAGES = [
  'Ingest data',
  'Select approved ontology',
  'Extract entities & relationships',
  'Validate facts',
  'Build / refresh KG',
  'Evaluate & propose improvements',
]

export function KnowledgeGraphStudioPage() {
  const { projectId, activeOntology } = useProjectScope()

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 p-6 lg:p-8">
      <PageHeader
        eyebrow="Knowledge Graph Studio"
        title="Knowledge graph construction"
        description="Build a knowledge graph from source data using an approved, published ontology version. Extracted facts are validated against ontology constraints and their evidence before entering the graph."
      />

      <ol className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6" aria-label="KG construction lifecycle">
        {STAGES.map((stage, index) => (
          <li key={stage} className="rounded-xl border bg-card p-3">
            <p className="text-[11px] font-medium text-muted-foreground">Step {index + 1}</p>
            <p className="mt-1 text-sm font-medium">{stage}</p>
            <Badge variant="outline" className="mt-2">
              Phase 3
            </Badge>
          </li>
        ))}
      </ol>

      <div className="rounded-xl border bg-card p-5">
        <h2 className="text-sm font-semibold">Prerequisites</h2>
        <ul className="mt-3 space-y-2 text-sm">
          <li className="flex items-center gap-2">
            {activeOntology && activeOntology.stats.class_count > 0 ? (
              <CheckCircle2 className="size-4 text-emerald-600" />
            ) : (
              <Circle className="size-4 text-muted-foreground" />
            )}
            Ontology draft with classes and relationships
            {activeOntology && (
              <span className="text-muted-foreground">
                ({activeOntology.name}, revision {activeOntology.draft_revision})
              </span>
            )}
          </li>
          <li className="flex items-center gap-2">
            {activeOntology?.latest_version ? (
              <CheckCircle2 className="size-4 text-emerald-600" />
            ) : (
              <Circle className="size-4 text-muted-foreground" />
            )}
            Published, approved ontology version
            <span className="text-muted-foreground">
              {activeOntology?.latest_version
                ? `(v${activeOntology.latest_version.version} available)`
                : '(publish one in Ontology Studio → Registry)'}
            </span>
          </li>
          <li className="flex items-center gap-2">
            <Circle className="size-4 text-muted-foreground" />
            Registered data sources
            <span className="text-muted-foreground">(ingestion arrives in Phase 3)</span>
          </li>
        </ul>
        <Button variant="outline" size="sm" className="mt-4" asChild>
          <Link to={`/projects/${projectId}/ontology`}>
            Continue in Ontology Studio <ArrowRight />
          </Link>
        </Button>
      </div>

      <PhaseNotice
        phase={3}
        title="Pipeline, fact validation, graph explorer and evaluation"
        description="Knowledge graph construction depends on a published ontology version, so it follows the governance milestone."
        capabilities={[
          'Select input sources and an approved ontology version',
          'Schema-guided entity and relationship extraction',
          'Structural domain/range validation independent of the LLM',
          'Accepted, rejected and quarantined facts with reasons',
          'Interactive graph explorer with provenance to source documents',
          'Quality metrics and ontology improvement proposals',
        ]}
      />
    </div>
  )
}
