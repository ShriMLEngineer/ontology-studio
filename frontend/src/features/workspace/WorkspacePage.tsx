import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowRight,
  Box,
  CheckCircle2,
  Database,
  FolderPlus,
  GitBranch,
  ListChecks,
  Network,
  PencilRuler,
  ShieldAlert,
  ShieldCheck,
  Spline,
  Tags,
  Waypoints,
} from 'lucide-react'
import { Link } from 'react-router'

import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { CreateProjectDialog } from '@/features/projects/CreateProjectDialog'
import { useProjectScope } from '@/features/projects/hooks'
import { governanceApi, projectsApi, registryApi, sourcesApi, validationApi } from '@/lib/api/endpoints'
import type { ActivityEvent } from '@/lib/api/types'
import { dateTime, plural, relativeTime } from '@/lib/format'
import { queryKeys } from '@/lib/query'

function StatCard({ label, value, icon }: { label: string; value: ReactNode; icon: ReactNode }) {
  return (
    <Card size="sm">
      <CardContent className="flex items-center gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary [&_svg]:size-4">{icon}</div>
        <div>
          <p className="text-2xl font-semibold tabular-nums">{value}</p>
          <p className="text-xs text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  )
}

const ACTIVITY_ICONS: Record<string, ReactNode> = {
  project: <FolderPlus />,
  ontology: <Network />,
  seed: <Database />,
}

function activityIcon(event: ActivityEvent): ReactNode {
  if (event.event_type === 'ontology.validated') return <ShieldCheck />
  if (event.event_type === 'ontology.draft_saved') return <GitBranch />
  return ACTIVITY_ICONS[event.event_type.split('.')[0] ?? ''] ?? <Activity />
}

function StatusRow({ icon, title, detail, badge }: { icon: ReactNode; title: string; detail: string; badge: ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
      <div className="mt-0.5 text-muted-foreground [&_svg]:size-4">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{detail}</p>
      </div>
      {badge}
    </div>
  )
}

export function WorkspacePage() {
  const { projectId, project, ontologies, activeOntology } = useProjectScope()
  const [creating, setCreating] = useState(false)

  const activity = useQuery({
    queryKey: queryKeys.activity(projectId),
    queryFn: () => projectsApi.activity(projectId, 12),
    enabled: Boolean(projectId),
  })
  const validation = useQuery({
    queryKey: queryKeys.latestValidation(activeOntology?.id ?? ''),
    queryFn: () => validationApi.latest(activeOntology!.id),
    enabled: Boolean(activeOntology),
  })
  const proposalStats = useQuery({
    queryKey: queryKeys.proposalStats(activeOntology?.id ?? ''),
    queryFn: () => governanceApi.stats(activeOntology!.id),
    enabled: Boolean(activeOntology),
  })
  const versions = useQuery({
    queryKey: queryKeys.versions(activeOntology?.id ?? ''),
    queryFn: () => registryApi.versions(activeOntology!.id),
    enabled: Boolean(activeOntology),
  })
  const sources = useQuery({
    queryKey: queryKeys.sources(projectId),
    queryFn: () => sourcesApi.list(projectId),
    enabled: Boolean(projectId),
  })

  if (!project) return <LoadingState />
  const studioTab = (tab: string) =>
    `/projects/${project.id}/ontology?${new URLSearchParams({
      ...(activeOntology ? { ontology: activeOntology.id } : {}),
      tab,
    }).toString()}`
  const studioPath = `/projects/${project.id}/ontology${activeOntology ? `?ontology=${activeOntology.id}` : ''}`
  const validationPath = studioTab('validation')
  const awaiting = proposalStats.data?.awaiting_review ?? 0
  const latestVersion = versions.data?.[0]

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6 p-6 lg:p-8">
      <PageHeader
        eyebrow={project.business_domain || 'Project'}
        title={project.name}
        description={project.description || 'No description provided.'}
        actions={
          <>
            <Button variant="outline" onClick={() => setCreating(true)}>
              <FolderPlus /> New project
            </Button>
            <Button asChild>
              <Link to={studioPath}>
                <Network /> Open Ontology Studio
              </Link>
            </Button>
          </>
        }
      />

      {ontologies.isPending ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : ontologies.isError ? (
        <ErrorState title="Unable to load ontology summary" error={ontologies.error} onRetry={() => ontologies.refetch()} />
      ) : activeOntology ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Classes" value={activeOntology.stats.class_count} icon={<Box />} />
          <StatCard label="Relationships" value={activeOntology.stats.object_property_count} icon={<Spline />} />
          <StatCard label="Attributes" value={activeOntology.stats.datatype_property_count} icon={<Tags />} />
          <StatCard label="Draft revision" value={`r${activeOntology.draft_revision}`} icon={<GitBranch />} />
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Ontology summary</CardTitle>
            <CardDescription>The governed, long-lived schema for this project.</CardDescription>
            {activeOntology && (
              <CardAction>
                <Button variant="outline" size="sm" asChild>
                  <Link to={studioPath}>
                    Open designer <ArrowRight />
                  </Link>
                </Button>
              </CardAction>
            )}
          </CardHeader>
          <CardContent>
            {!activeOntology ? (
              <EmptyState title="No ontology yet" description="This project does not contain an ontology." />
            ) : (
              <div className="space-y-4">
                <div>
                  <p className="font-medium">{activeOntology.name}</p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {activeOntology.prefix}: &lt;{activeOntology.namespace}&gt;
                  </p>
                  {activeOntology.description && <p className="mt-2 text-sm text-muted-foreground">{activeOntology.description}</p>}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">Draft r{activeOntology.draft_revision}</Badge>
                  <Badge variant="outline" className="font-mono">
                    {activeOntology.latest_version ? `Published v${activeOntology.latest_version.version}` : 'No published version'}
                  </Badge>
                  <Badge variant="outline">Updated {relativeTime(activeOntology.updated_at)}</Badge>
                </div>
                <div className="rounded-lg border bg-muted/30 p-3">
                  {validation.isPending ? (
                    <Skeleton className="h-10" />
                  ) : validation.isError ? (
                    <p className="text-sm text-destructive">Unable to load validation status.</p>
                  ) : !validation.data ? (
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm text-muted-foreground">Not validated yet.</p>
                      <Button size="sm" variant="outline" asChild>
                        <Link to={validationPath}>
                          <ListChecks /> Validate
                        </Link>
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5">
                        {validation.data.is_valid ? (
                          <ShieldCheck className="size-5 text-emerald-600" />
                        ) : (
                          <ShieldAlert className="size-5 text-red-600" />
                        )}
                        <div>
                          <p className="text-sm font-medium">
                            {validation.data.is_valid ? 'Structurally valid' : `${plural(validation.data.error_count, 'error')} found`}
                            {' · '}
                            {plural(validation.data.warning_count, 'warning')}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Revision {validation.data.draft_revision} · {dateTime(validation.data.created_at)}
                            {!validation.data.is_current && ' · outdated'}
                          </p>
                        </div>
                      </div>
                      <Button size="sm" variant="outline" asChild>
                        <Link to={validationPath}>View report</Link>
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Quick actions</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2">
            <Button variant="outline" className="justify-start" asChild>
              <Link to={studioPath}>
                <PencilRuler /> Edit ontology in designer
              </Link>
            </Button>
            <Button variant="outline" className="justify-start" asChild>
              <Link to={validationPath}>
                <ListChecks /> Validate ontology
              </Link>
            </Button>
            <Button variant="outline" className="justify-start" onClick={() => setCreating(true)}>
              <FolderPlus /> Create another project
            </Button>
            <Button variant="outline" className="justify-start" asChild>
              <Link to={`/projects/${project.id}/knowledge-graph`}>
                <Waypoints /> Knowledge Graph Studio
              </Link>
            </Button>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent activity</CardTitle>
            <CardDescription>Audit trail of changes in this project.</CardDescription>
          </CardHeader>
          <CardContent>
            {activity.isPending ? (
              <LoadingState label="Loading activity…" className="min-h-24" />
            ) : activity.isError ? (
              <ErrorState title="Unable to load activity" error={activity.error} onRetry={() => activity.refetch()} />
            ) : activity.data.length === 0 ? (
              <EmptyState title="No activity yet" />
            ) : (
              <ol className="space-y-3" aria-label="Recent activity">
                {activity.data.map((event) => (
                  <li key={event.id} className="flex items-start gap-3">
                    <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground [&_svg]:size-3.5">
                      {activityIcon(event)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm">{event.summary}</p>
                      <p className="text-xs text-muted-foreground" title={dateTime(event.created_at)}>
                        {relativeTime(event.created_at)}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Governance & knowledge graph</CardTitle>
            <CardDescription>Review, publication and source status. Work happens in Ontology Studio.</CardDescription>
          </CardHeader>
          <CardContent className="divide-y">
            <StatusRow
              icon={<CheckCircle2 />}
              title="Pending reviews"
              detail={
                awaiting
                  ? `${plural(awaiting, 'proposal')} awaiting SME review`
                  : `No proposals awaiting review${proposalStats.data?.total ? ` (${proposalStats.data.total} reviewed)` : ''}`
              }
              badge={
                <Button variant="outline" size="xs" asChild>
                  <Link to={studioTab('review')}>Review</Link>
                </Button>
              }
            />
            <StatusRow
              icon={<GitBranch />}
              title="Published versions"
              detail={
                latestVersion
                  ? `Latest v${latestVersion.version} by ${latestVersion.published_by}, ${relativeTime(latestVersion.published_at)}`
                  : 'Nothing published yet'
              }
              badge={
                <Button variant="outline" size="xs" asChild>
                  <Link to={studioTab('registry')}>{latestVersion ? `${versions.data?.length} total` : 'Publish'}</Link>
                </Button>
              }
            />
            <StatusRow
              icon={<Database />}
              title="Source documents"
              detail={`${plural(sources.data?.length ?? 0, 'document')} for AI discovery · KG ingestion arrives in Phase 3`}
              badge={
                <Button variant="outline" size="xs" asChild>
                  <Link to={studioTab('discovery')}>Discover</Link>
                </Button>
              }
            />
            <StatusRow
              icon={<Waypoints />}
              title="Latest KG build"
              detail="No knowledge graph has been built."
              badge={<Badge variant="outline">Phase 3</Badge>}
            />
          </CardContent>
        </Card>
      </div>

      <CreateProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  )
}
