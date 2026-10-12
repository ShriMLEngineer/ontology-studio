import type { ComponentProps } from 'react'

import { NativeSelect } from '@/features/kg/fields'
import type { GraphConnection, LlmConfig } from '@/lib/api/types'
import { useGraphConnections, useLlmConfigs } from './hooks'

const PROJECT_DEFAULT = ''

/** LLM configuration picker. The empty value means "use the project's default". */
export function LlmConfigSelect({
  value,
  onChange,
  projectDefault,
  allowProjectDefault = true,
  ...props
}: {
  value: string | null | undefined
  onChange: (value: string | null) => void
  projectDefault?: LlmConfig
  allowProjectDefault?: boolean
} & Omit<ComponentProps<'select'>, 'value' | 'onChange'>) {
  const configs = useLlmConfigs()
  return (
    <NativeSelect
      value={value ?? PROJECT_DEFAULT}
      onChange={(e) => onChange(e.target.value === PROJECT_DEFAULT ? null : e.target.value)}
      {...props}
    >
      {allowProjectDefault && (
        <option value={PROJECT_DEFAULT}>Project default{projectDefault ? ` (${projectDefault.name})` : ''}</option>
      )}
      {(configs.data ?? []).map((c) => (
        <option key={c.id} value={c.id} disabled={!c.configured || !c.enabled}>
          {c.name}
          {c.model ? ` · ${c.model}` : ''}
          {c.configured ? '' : ' (not configured)'}
        </option>
      ))}
    </NativeSelect>
  )
}

/** Graph target picker. The empty value means "use the project's default". Disabled registrations are not offered. */
export function GraphTargetSelect({
  value,
  onChange,
  projectDefault,
  allowProjectDefault = true,
  ...props
}: {
  value: string | null | undefined
  onChange: (value: string | null) => void
  projectDefault?: GraphConnection
  allowProjectDefault?: boolean
} & Omit<ComponentProps<'select'>, 'value' | 'onChange'>) {
  const connections = useGraphConnections()
  return (
    <NativeSelect
      value={value ?? PROJECT_DEFAULT}
      onChange={(e) => onChange(e.target.value === PROJECT_DEFAULT ? null : e.target.value)}
      {...props}
    >
      {allowProjectDefault && (
        <option value={PROJECT_DEFAULT}>Project default{projectDefault ? ` (${projectDefault.name})` : ''}</option>
      )}
      {(connections.data ?? [])
        .filter((c) => c.enabled || c.id === value)
        .map((c) => (
          <option key={c.id} value={c.id} title={graphTargetHint(c)}>
            {c.name} · {c.model === 'rdf' ? 'RDF' : 'property graph'}
            {graphTargetSuffix(c)}
          </option>
        ))}
    </NativeSelect>
  )
}

function isInternal(c: GraphConnection): boolean {
  return c.builtin || c.provider === 'local-sql'
}

/** A short, honest qualifier: a connection that was never tested or cannot receive deployments says so. */
function graphTargetSuffix(c: GraphConnection): string {
  if (!c.enabled) return ' (disabled)'
  if (c.capabilities.deployment_supported && !c.capabilities.write_configured) return ' (read-only)'
  if (!isInternal(c) && c.status === 'failed') return ' (connection failed)'
  if (!isInternal(c) && c.status === 'not_tested') return ' (not tested)'
  return ''
}

function graphTargetHint(c: GraphConnection): string {
  const cap = c.capabilities
  return [
    c.kind_label,
    cap.deployment_ready ? 'Ready for deployment' : 'Not ready for deployment',
    cap.deployment_verified ? 'A deployment was verified' : 'No verified deployment yet',
    cap.live_tested ? 'Adapter live-tested' : 'Adapter not live-tested',
  ].join(' · ')
}
