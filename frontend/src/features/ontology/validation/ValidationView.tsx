import { useState } from 'react'
import { useMutation, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { CheckCircle2, ExternalLink, Loader2, PlayCircle, ShieldAlert, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from 'cn'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { errorMessage } from '@/lib/api/client'
import { validationApi } from '@/lib/api/endpoints'
import type { Severity, ValidationIssue, ValidationReport } from '@/lib/api/types'
import { dateTime, plural } from '@/lib/format'
import { queryKeys } from '@/lib/query'
import type { DraftEditor } from '../draft/useDraftEditor'
import { SEVERITY_META } from '../designer/presentation'
import { SemanticLanes } from './SemanticLanes'

const KIND_LABEL: Record<ValidationIssue['element_kind'], string> = {
  ontology: 'Ontology',
  class: 'Class',
  object_property: 'Relationship',
  datatype_property: 'Attribute',
}

export function ValidationView({
  projectId,
  ontologyId,
  editor,
  latest,
  onShowIssue,
}: {
  projectId: string
  ontologyId: string
  editor: DraftEditor
  latest: UseQueryResult<ValidationReport | null>
  onShowIssue: (issue: ValidationIssue) => void
}) {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<Severity | 'all'>('all')

  const run = useMutation({
    mutationFn: () => validationApi.run(ontologyId),
    onSuccess: (report) => {
      queryClient.setQueryData(queryKeys.latestValidation(ontologyId), report)
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity(projectId) })
      if (report.is_valid) toast.success('Validation passed', { description: `${plural(report.warning_count, 'warning')}, ${report.info_count} info` })
      else toast.error('Validation found errors', { description: `${plural(report.error_count, 'error')} must be fixed before publication.` })
    },
  })

  const saveAndValidate = async () => {
    try {
      await editor.save()
      run.mutate()
    } catch {
      toast.error('Draft could not be saved', { description: errorMessage(editor.saveError) })
    }
  }

  const report = latest.data
  const issues = report?.issues.filter((i) => filter === 'all' || i.severity === filter) ?? []

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Structural validation</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Checks the saved draft for invalid identifiers and namespaces, duplicates, unknown references, domain/range
            consistency, hierarchy cycles and missing definitions. Errors block publication.
          </p>
        </div>
        <Button onClick={() => run.mutate()} disabled={run.isPending || editor.saving}>
          {run.isPending ? <Loader2 className="animate-spin" /> : <PlayCircle />}
          Run validation
        </Button>
      </div>

      {editor.dirty && (
        <Alert>
          <AlertTitle>You have unsaved changes</AlertTitle>
          <AlertDescription>
            Validation runs against the saved draft (revision {editor.base?.draft_revision}). Save first to include your
            latest edits.
          </AlertDescription>
          <AlertAction>
            <Button size="sm" onClick={() => void saveAndValidate()} disabled={editor.saving || run.isPending}>
              Save & validate
            </Button>
          </AlertAction>
        </Alert>
      )}

      {run.isError && (
        <Alert variant="destructive">
          <AlertTitle>Validation could not run</AlertTitle>
          <AlertDescription>{errorMessage(run.error)}</AlertDescription>
        </Alert>
      )}

      {latest.isPending ? (
        <LoadingState label="Loading latest validation report…" />
      ) : latest.isError ? (
        <ErrorState title="Unable to load the validation report" error={latest.error} onRetry={() => latest.refetch()} />
      ) : !report ? (
        <EmptyState
          icon={<ShieldCheck />}
          title="This ontology has not been validated yet"
          description="Run validation to check the saved draft's structure."
          action={
            <Button onClick={() => run.mutate()} disabled={run.isPending}>
              <PlayCircle /> Run validation
            </Button>
          }
        />
      ) : (
        <>
          <Card className={cn('border-l-4', report.is_valid ? 'border-l-emerald-500' : 'border-l-red-500')}>
            <CardContent className="flex flex-wrap items-center gap-4">
              {report.is_valid ? (
                <ShieldCheck className="size-8 text-emerald-600" />
              ) : (
                <ShieldAlert className="size-8 text-red-600" />
              )}
              <div className="min-w-0 flex-1">
                <p className="font-semibold" data-testid="validation-status">
                  {report.is_valid ? 'Structurally valid' : 'Validation failed'}
                </p>
                <p className="text-sm text-muted-foreground">
                  Revision {report.draft_revision} · validated {dateTime(report.created_at)}
                </p>
              </div>
              {report.is_current ? (
                <Badge variant="outline" className="border-emerald-300 text-emerald-700">
                  <CheckCircle2 /> Current revision
                </Badge>
              ) : (
                <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-800">
                  Outdated - draft is now revision {report.current_draft_revision}
                </Badge>
              )}
            </CardContent>
          </Card>

          <div className="grid grid-cols-3 gap-4">
            {(['error', 'warning', 'info'] as const).map((severity) => {
              const meta = SEVERITY_META[severity]
              const count = report[`${severity}_count`]
              const active = filter === severity
              return (
                <button
                  key={severity}
                  type="button"
                  onClick={() => setFilter(active ? 'all' : severity)}
                  aria-pressed={active}
                  className={cn(
                    'flex items-center gap-3 rounded-xl border bg-card p-4 text-left transition-colors hover:bg-muted/50',
                    active && 'border-primary ring-2 ring-primary/20',
                  )}
                >
                  <meta.icon className={cn('size-5', meta.className)} />
                  <div>
                    <p className="text-2xl font-semibold tabular-nums">{count}</p>
                    <p className="text-xs text-muted-foreground">{severity === 'info' ? 'Info' : `${meta.label}s`}</p>
                  </div>
                </button>
              )
            })}
          </div>

          {report.issues.length === 0 ? (
            <EmptyState icon={<CheckCircle2 />} title="No issues found" description="The saved draft passed every structural check." />
          ) : (
            <div className="overflow-hidden rounded-xl border bg-card">
              <div className="flex items-center justify-between border-b px-4 py-2.5 text-sm">
                <span className="font-medium">
                  {filter === 'all' ? 'All findings' : `${SEVERITY_META[filter].label} findings`} ({issues.length})
                </span>
                {filter !== 'all' && (
                  <Button variant="ghost" size="xs" onClick={() => setFilter('all')}>
                    Show all
                  </Button>
                )}
              </div>
              <ul className="divide-y" aria-label="Validation findings">
                {issues.map((issue, index) => {
                  const meta = SEVERITY_META[issue.severity]
                  return (
                    <li key={`${issue.code}-${issue.element_id}-${index}`} className="flex items-start gap-3 px-4 py-3">
                      <meta.icon className={cn('mt-0.5 size-4 shrink-0', meta.className)} aria-label={meta.label} />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm">{issue.message}</p>
                        <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <code className="rounded bg-muted px-1.5 py-0.5">{issue.code}</code>
                          <span>
                            {KIND_LABEL[issue.element_kind]}
                            {issue.element_label ? ` · ${issue.element_label}` : ''}
                            {issue.field ? ` · ${issue.field}` : ''}
                          </span>
                        </p>
                      </div>
                      <Button variant="ghost" size="xs" onClick={() => onShowIssue(issue)}>
                        <ExternalLink /> Show
                      </Button>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </>
      )}

      {editor.base && <SemanticLanes projectId={projectId} ontologyId={ontologyId} revision={editor.base.draft_revision} />}
    </div>
  )
}
