import type { ReactNode } from 'react'
import { CheckCircle2, MinusCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { GraphConnection, GraphConnectionStatus } from '@/lib/api/types'

const STATUS_STYLE: Record<GraphConnectionStatus, { label: string; className: string }> = {
  connected: { label: 'Connected', className: 'border-emerald-300 bg-emerald-50 text-emerald-800' },
  failed: { label: 'Connection failed', className: 'border-red-300 bg-red-50 text-red-800' },
  not_tested: { label: 'Not tested', className: 'text-muted-foreground' },
}

export function GraphStatusBadge({ status }: { status: GraphConnectionStatus }) {
  return (
    <Badge variant="outline" className={STATUS_STYLE[status].className} data-testid="graph-status">
      {STATUS_STYLE[status].label}
    </Badge>
  )
}

function Chip({ ok, children, hint }: { ok: boolean; children: ReactNode; hint?: string }) {
  return (
    <span
      title={hint}
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] ${
        ok ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-dashed text-muted-foreground'
      }`}
    >
      {ok ? <CheckCircle2 className="size-3" /> : <MinusCircle className="size-3" />}
      {children}
    </span>
  )
}

/** Registered, connected, deployment supported and deployment verified are four different facts. */
export function GraphCapabilityChips({ connection }: { connection: GraphConnection }) {
  const c = connection.capabilities
  const internal = connection.builtin || connection.provider === 'local-sql'
  return (
    <div className="mt-2 flex flex-wrap gap-1.5" data-testid="graph-capabilities">
      <Chip ok={c.registered}>Registered</Chip>
      <Chip ok={internal || c.connected} hint={internal ? 'Internal store: no connection test needed' : 'The last connection test succeeded'}>
        {internal ? 'Internal' : 'Connected'}
      </Chip>
      <Chip
        ok={c.deployment_supported && c.write_configured}
        hint={
          c.deployment_supported && !c.write_configured
            ? 'The provider supports deployment, but this registration has no update endpoint (read-only).'
            : 'The provider adapter can write and verify a build'
        }
      >
        {c.deployment_supported && !c.write_configured ? 'Read-only registration' : 'Deployment supported'}
      </Chip>
      <Chip ok={c.deployment_verified} hint="A deployment to this registration was written and read back">
        Deployment verified
      </Chip>
      <Chip ok={c.live_tested} hint={c.verification_note}>
        {c.live_tested ? 'Adapter live-tested' : 'Adapter not live-tested'}
      </Chip>
    </div>
  )
}
