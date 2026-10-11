import { Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { LoadingState } from '@/components/common/states'
import type { BuildDetail, BuildSummary, PublishedVersionOption } from '@/lib/api/types'
import { useBuild } from '../hooks'
import { BuildConfigPanel } from './BuildConfigPanel'
import { BuildHistory } from './BuildHistory'
import { BuildStatusPanel } from './BuildStatusPanel'

export function PipelineView({
  projectId,
  versions,
  builds,
  selectedId,
  creating,
  onSelect,
  onNew,
  onOpenTab,
}: {
  projectId: string
  versions: PublishedVersionOption[]
  builds: BuildSummary[]
  selectedId: string | undefined
  creating: boolean
  onSelect: (buildId: string) => void
  onNew: () => void
  onOpenTab: (tab: string) => void
}) {
  const build = useBuild(creating ? undefined : selectedId)
  const detail: BuildDetail | undefined = build.data

  const showConfig = creating || !selectedId || detail?.status === 'configured'
  return (
    <div className="mx-auto grid w-full max-w-7xl gap-5 p-6 lg:grid-cols-[minmax(0,460px)_minmax(0,1fr)]">
      <div className="space-y-4">
        {showConfig ? (
          selectedId && !creating && !detail ? (
            <LoadingState />
          ) : (
            <BuildConfigPanel
              key={creating || !detail ? 'new' : detail.id}
              projectId={projectId}
              versions={versions}
              build={creating ? null : (detail ?? null)}
              onSaved={(saved) => onSelect(saved.id)}
            />
          )
        ) : (
          <div className="flex items-center justify-between rounded-xl border bg-card px-4 py-3">
            <p className="text-sm text-muted-foreground">Configure another build from sources and a published version.</p>
            <Button size="sm" onClick={onNew}>
              <Plus /> New build
            </Button>
          </div>
        )}
        {builds.length > 0 && <BuildHistory builds={builds} selectedId={creating ? undefined : selectedId} onSelect={onSelect} />}
      </div>
      <div className="min-w-0 space-y-4">
        {detail && !creating ? (
          <BuildStatusPanel key={detail.id} build={detail} versions={versions} onOpenTab={onOpenTab} onSelectBuild={onSelect} />
        ) : (
          <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
            The nine pipeline stages and their logs appear here once a build is started: source loading, content parsing, entity
            extraction, relationship extraction, entity resolution, structural validation, evidence validation, graph persistence
            and evaluation.
          </div>
        )}
        {showConfig && !creating && detail && (
          <Button variant="outline" size="sm" onClick={onNew}>
            <Plus /> New build instead
          </Button>
        )}
      </div>
    </div>
  )
}
