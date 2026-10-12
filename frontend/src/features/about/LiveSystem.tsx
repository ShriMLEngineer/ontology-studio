import { useQuery } from '@tanstack/react-query'
import { ArrowRight, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { cn } from 'cn'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/api/client'
import { systemApi } from '@/lib/api/endpoints'
import { queryKeys } from '@/lib/query'
import { appHref } from './content'

type Tone = 'ok' | 'bad' | 'idle'

const DOT: Record<Tone, string> = { ok: 'bg-emerald-500', bad: 'bg-red-500', idle: 'bg-muted-foreground/40' }

function Tile({ label, tone, value, detail, testId }: { label: string; tone: Tone; value: string; detail?: ReactNode; testId: string }) {
  return (
    <Card size="sm" data-testid={testId}>
      <CardContent className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="flex items-center gap-2 text-sm font-semibold">
          <span className={cn('size-2 shrink-0 rounded-full', DOT[tone])} />
          {value}
        </p>
        {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
      </CardContent>
    </Card>
  )
}

/** Real status of the running instance, read from the same endpoints the application header uses. */
export function LiveSystem({ projectId }: { projectId: string }) {
  const health = useQuery({ queryKey: queryKeys.health, queryFn: systemApi.health, refetchInterval: 30_000, retry: false })
  const llm = useQuery({
    queryKey: queryKeys.llmStatusFor(projectId, null),
    queryFn: () => systemApi.llmStatus(false, { projectId }),
    retry: false,
  })
  const refreshing = health.isFetching || llm.isFetching

  const api = health.isPending
    ? { tone: 'idle' as const, value: 'Connecting…', detail: 'Checking backend health' }
    : health.isError
      ? { tone: 'bad' as const, value: 'Unavailable', detail: errorMessage(health.error) }
      : health.data.status === 'ok'
        ? { tone: 'ok' as const, value: 'Online', detail: 'The API answers and the database is reachable' }
        : { tone: 'bad' as const, value: 'Degraded', detail: 'The API answers but a dependency is failing' }

  const database = health.data?.database
  const ai = llm.data

  return (
    <div className="space-y-3" data-testid="about-system">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {health.isPending ? (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)
        ) : (
          <>
            <Tile label="API" tone={api.tone} value={api.value} detail={api.detail} testId="about-system-api" />
            <Tile
              label="Application"
              tone={health.isSuccess ? 'ok' : 'idle'}
              value={health.isSuccess ? `${health.data.app} v${health.data.version}` : '—'}
              detail={health.isSuccess ? `Environment: ${health.data.environment}` : undefined}
              testId="about-system-app"
            />
            <Tile
              label="Database"
              tone={database === undefined ? 'idle' : database === 'ok' ? 'ok' : 'bad'}
              value={database === undefined ? '—' : database === 'ok' ? 'Healthy' : database}
              detail="Application database used for drafts, builds and the audit trail"
              testId="about-system-db"
            />
            <Tile
              label="AI provider"
              tone={llm.isPending ? 'idle' : ai?.configured ? 'ok' : 'idle'}
              value={llm.isPending ? 'Checking…' : ai?.configured ? [ai.provider, ai.model].filter(Boolean).join(' · ') || 'Configured' : 'Not configured'}
              detail={
                ai?.configured ? (
                  ai.config_name ?? ai.endpoint_host ?? undefined
                ) : (
                  <Link className="inline-flex items-center gap-1 text-primary hover:underline" to={appHref(projectId, { area: 'settings' })}>
                    Register a model in Settings <ArrowRight className="size-3" />
                  </Link>
                )
              }
              testId="about-system-ai"
            />
          </>
        )}
      </div>
      <Button
        variant="outline"
        size="sm"
        disabled={refreshing}
        onClick={() => {
          void health.refetch()
          void llm.refetch()
        }}
      >
        <RefreshCw className={cn(refreshing && 'animate-spin')} /> Refresh status
      </Button>
    </div>
  )
}
