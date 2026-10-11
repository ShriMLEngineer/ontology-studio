import { useEffect } from 'react'
import { FolderX } from 'lucide-react'
import { Link, Outlet } from 'react-router'

import { AppHeader } from '@/components/layout/AppHeader'
import { Sidebar } from '@/components/layout/Sidebar'
import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { rememberProject, useProjectScope } from '@/features/projects/hooks'

export function AppShell() {
  const { projectId, project, projects, activeOntology, projectMissing } = useProjectScope()

  useEffect(() => {
    if (project) rememberProject(project.id)
  }, [project])

  if (projects.isPending) return <LoadingState label="Loading workspace…" className="min-h-screen" />
  if (projects.isError)
    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <ErrorState title="Unable to load projects" error={projects.error} onRetry={() => projects.refetch()} />
      </div>
    )
  if (projectMissing || !project)
    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <EmptyState
          icon={<FolderX />}
          title="Project not found"
          description={`No project exists with id "${projectId}".`}
          action={
            <Button asChild>
              <Link to="/">Go to projects</Link>
            </Button>
          }
        />
      </div>
    )

  return (
    <div className="flex h-screen overflow-hidden bg-muted/20">
      <Sidebar projectId={project.id} />
      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader projects={projects.data} project={project} ontology={activeOntology} />
        <main className="flex min-h-0 flex-1 flex-col overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
