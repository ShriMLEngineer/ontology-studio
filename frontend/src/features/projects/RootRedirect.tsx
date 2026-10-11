import { useState } from 'react'
import { FolderPlus, Network } from 'lucide-react'
import { Navigate } from 'react-router'

import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { CreateProjectDialog } from '@/features/projects/CreateProjectDialog'
import { lastProjectId, useProjects } from '@/features/projects/hooks'

/** Entry route: opens the last used project, else the first, else offers to create one. */
export function RootRedirect() {
  const projects = useProjects()
  const [creating, setCreating] = useState(false)

  if (projects.isPending) return <LoadingState label="Loading projects…" className="min-h-screen" />
  if (projects.isError)
    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <ErrorState title="Unable to load projects" error={projects.error} onRetry={() => projects.refetch()} />
      </div>
    )

  const remembered = lastProjectId()
  const target = projects.data.find((p) => p.id === remembered) ?? projects.data[0]
  if (target) return <Navigate to={`/projects/${target.id}/workspace`} replace />

  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <EmptyState
        className="max-w-lg bg-background"
        icon={<Network />}
        title="Welcome to Ontology Lifecycle Studio"
        description="Create your first project to start designing a governed ontology."
        action={
          <Button onClick={() => setCreating(true)}>
            <FolderPlus /> Create project
          </Button>
        }
      />
      <CreateProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  )
}
