import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FolderPlus, GitBranch } from 'lucide-react'
import { useNavigate } from 'react-router'
import { cn } from 'cn'

import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { CreateProjectDialog } from '@/features/projects/CreateProjectDialog'
import type { Ontology, Project } from '@/lib/api/types'
import { systemApi } from '@/lib/api/endpoints'
import { errorMessage } from '@/lib/api/client'
import { queryKeys } from '@/lib/query'

const NEW_PROJECT = '__new__'

function ApiStatus() {
  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: systemApi.health,
    refetchInterval: 30_000,
    retry: false,
  })
  const online = health.isSuccess && health.data.status === 'ok'
  const label = health.isPending ? 'Connecting…' : online ? 'API online' : 'API unavailable'
  const detail = health.isSuccess
    ? `${health.data.app} v${health.data.version} · ${health.data.environment} · database ${health.data.database}`
    : health.isError
      ? errorMessage(health.error)
      : 'Checking backend health'

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs whitespace-nowrap text-muted-foreground" role="status">
          <span
            className={cn(
              'size-2 rounded-full',
              health.isPending ? 'bg-muted-foreground/40' : online ? 'bg-emerald-500' : 'bg-red-500',
            )}
          />
          {label}
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom">{detail}</TooltipContent>
    </Tooltip>
  )
}

export function AppHeader({
  projects,
  project,
  ontology,
}: {
  projects: Project[]
  project: Project
  ontology: Ontology | undefined
}) {
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b bg-background px-6">
      <Select
        value={project.id}
        onValueChange={(value) => {
          if (value === NEW_PROJECT) setCreating(true)
          else navigate(`/projects/${value}/workspace`)
        }}
      >
        <SelectTrigger className="w-60 shrink-0" aria-label="Select project">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {projects.map((p) => (
            <SelectItem key={p.id} value={p.id}>
              {p.name}
            </SelectItem>
          ))}
          <SelectSeparator />
          <SelectItem value={NEW_PROJECT}>
            <FolderPlus /> New project…
          </SelectItem>
        </SelectContent>
      </Select>

      {ontology ? (
        <div className="flex min-w-0 items-center gap-2 text-sm" aria-label="Current ontology version">
          <GitBranch className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-16 truncate font-medium">{ontology.name}</span>
          <Badge variant="secondary" className="shrink-0">
            Draft r{ontology.draft_revision}
          </Badge>
          {ontology.latest_version ? (
            <Badge variant="outline" className="hidden shrink-0 font-mono xl:inline-flex" data-testid="header-published-version">
              Published v{ontology.latest_version.version}
            </Badge>
          ) : (
            <Badge variant="outline" className="hidden shrink-0 text-muted-foreground xl:inline-flex">
              No published version
            </Badge>
          )}
        </div>
      ) : (
        <span className="text-sm text-muted-foreground">No ontology in this project</span>
      )}

      <div className="ml-auto shrink-0">
        <ApiStatus />
      </div>
      <CreateProjectDialog open={creating} onOpenChange={setCreating} />
    </header>
  )
}
