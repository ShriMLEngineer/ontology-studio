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
        <option key={c.id} value={c.id} disabled={!c.configured}>
          {c.name}
          {c.model ? ` · ${c.model}` : ''}
          {c.configured ? '' : ' (not configured)'}
        </option>
      ))}
    </NativeSelect>
  )
}

/** Graph target picker. The empty value means "use the project's default". */
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
      {(connections.data ?? []).map((c) => (
        <option key={c.id} value={c.id}>
          {c.name} · {c.model === 'rdf' ? 'RDF' : 'property graph'}
        </option>
      ))}
    </NativeSelect>
  )
}
