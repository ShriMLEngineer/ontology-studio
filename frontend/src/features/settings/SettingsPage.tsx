import { useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  CheckCircle2,
  Database,
  KeyRound,
  Loader2,
  Pencil,
  PlugZap,
  Plus,
  Settings as SettingsIcon,
  SlidersHorizontal,
  Trash2,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'

import { ErrorState, LoadingState } from '@/components/common/states'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { projectsApi, settingsApi } from '@/lib/api/endpoints'
import type {
  ConnectionTest,
  GraphConnection,
  GraphConnectionInput,
  GraphKind,
  GraphKindField,
  LlmConfig,
  LlmConfigInput,
} from '@/lib/api/types'
import { relativeTime } from '@/lib/format'
import { NativeSelect } from '@/features/kg/fields'
import { useReviewerName } from '@/features/ontology/governance/reviewer'
import { useProjectScope } from '@/features/projects/hooks'
import { GraphCapabilityChips, GraphStatusBadge } from './GraphCapabilities'
import { useGraphConnections, useGraphKinds, useLlmConfigs, useProjectDefaults } from './hooks'
import { GraphTargetSelect, LlmConfigSelect } from './selectors'

function TestResult({ test }: { test: ConnectionTest | null }) {
  if (!test) return <span className="text-xs text-muted-foreground">Not tested</span>
  return (
    <span className="flex items-start gap-1.5 text-xs" data-testid="connection-test" data-ok={test.ok}>
      {test.ok ? (
        <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />
      ) : (
        <XCircle className="mt-0.5 size-3.5 shrink-0 text-red-600" />
      )}
      <span>
        {test.message}
        <span className="text-muted-foreground">
          {' '}
          · {test.latency_ms} ms{test.tested_at ? ` · ${relativeTime(test.tested_at)}` : ''}
        </span>
      </span>
    </span>
  )
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string
  label: string
  hint?: ReactNode
  error?: string | null
  children: ReactNode
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      {children}
      {error ? (
        <p role="alert" className="text-[11px] text-destructive">
          {error}
        </p>
      ) : (
        hint && <p className="text-[11px] text-muted-foreground">{hint}</p>
      )}
    </div>
  )
}

const ENV_VAR_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,119}$/

/** Credentials are referenced by environment-variable name; the value must never be typed into Settings. */
function envNameProblem(value: string | null | undefined): string | null {
  const name = (value ?? '').trim()
  if (!name || ENV_VAR_NAME.test(name)) return null
  return 'Enter the NAME of a server environment variable (e.g. OPENAI_API_KEY), not the key itself. Set the key in the backend’s environment.'
}

// ------------------------------------------------------------------------------------ project defaults

function ProjectDefaultsCard({ projectId, projectName }: { projectId: string; projectName: string }) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const defaults = useProjectDefaults(projectId)
  const [draft, setDraft] = useState<{ discoveryLlm: string; kgLlm: string; graph: string; namespace: string } | null>(null)
  const current = draft ?? {
    discoveryLlm: defaults.data?.default_discovery_llm_config_id ?? '',
    kgLlm: defaults.data?.default_kg_llm_config_id ?? '',
    graph: defaults.data?.default_graph_connection_id ?? '',
    namespace: defaults.data?.data_namespace ?? '',
  }
  const save = useMutation({
    mutationFn: () =>
      projectsApi.updateDefaults(
        projectId,
        {
          default_discovery_llm_config_id: current.discoveryLlm,
          default_kg_llm_config_id: current.kgLlm,
          default_graph_connection_id: current.graph,
          data_namespace: current.namespace,
        },
        reviewer,
      ),
    onSuccess: () => {
      toast.success('Project defaults saved')
      setDraft(null)
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['llm-status'] })
    },
  })
  const set = (patch: Partial<typeof current>) => setDraft({ ...current, ...patch })
  return (
    <Card data-testid="project-defaults">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SlidersHorizontal className="size-4" /> Defaults for {projectName}
        </CardTitle>
        <CardDescription>
          Used by AI discovery and knowledge-graph builds of this project unless a run or build selects another
          configuration. Builds record the configuration they actually used.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {defaults.isPending ? (
          <LoadingState className="min-h-16" />
        ) : defaults.isError ? (
          <ErrorState error={defaults.error} onRetry={() => defaults.refetch()} />
        ) : (
          <div className="grid gap-4 md:grid-cols-4">
            <Field id="default-discovery-llm" label="Ontology Discovery LLM">
              <LlmConfigSelect
                id="default-discovery-llm"
                allowProjectDefault={false}
                value={current.discoveryLlm}
                onChange={(v) => set({ discoveryLlm: v ?? '' })}
              />
            </Field>
            <Field id="default-kg-llm" label="KG Extraction LLM">
              <LlmConfigSelect
                id="default-kg-llm"
                allowProjectDefault={false}
                value={current.kgLlm}
                onChange={(v) => set({ kgLlm: v ?? '' })}
              />
            </Field>
            <Field id="default-graph" label="Default graph database">
              <GraphTargetSelect
                id="default-graph"
                allowProjectDefault={false}
                value={current.graph}
                onChange={(v) => set({ graph: v ?? '' })}
              />
            </Field>
            <Field
              id="data-namespace"
              label="Data namespace (instance IRIs)"
              hint="Empty = {ontology IRI}/data/ of the version a build uses. Frozen per build."
            >
              <Input
                id="data-namespace"
                className="font-mono text-xs"
                placeholder="https://data.example.org/project/"
                value={current.namespace}
                onChange={(e) => set({ namespace: e.target.value })}
              />
            </Field>
            <div className="flex items-center justify-end gap-2 md:col-span-4">
              {save.isError && <span className="text-xs text-destructive">{errorMessage(save.error)}</span>}
              <Button onClick={() => save.mutate()} disabled={!draft || !reviewer || save.isPending} title={reviewer ? undefined : 'Set your reviewer name first'}>
                {save.isPending && <Loader2 className="animate-spin" />} Save defaults
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------------------------ LLM configurations

const EMPTY_LLM: LlmConfigInput = {
  name: '',
  provider: 'ollama',
  base_url: 'http://localhost:11434',
  model: '',
  api_key_env: '',
  provider_config: {},
  structured_output: 'json_schema',
  temperature: 0,
  timeout_seconds: 600,
  max_output_tokens: 4096,
  description: '',
}

function LlmDialog({
  initial,
  onClose,
  onSave,
  saving,
  error,
}: {
  initial: LlmConfigInput
  onClose: () => void
  onSave: (value: LlmConfigInput) => void
  saving: boolean
  error: unknown
}) {
  const [value, setValue] = useState(initial)
  const set = (patch: Partial<LlmConfigInput>) => setValue((v) => ({ ...v, ...patch }))
  const azure = value.provider === 'azure-foundry'
  const needsEndpoint = azure || value.provider === 'ollama' || value.provider === 'openai-compatible'
  const needsKey = value.provider === 'openai' || value.provider === 'anthropic' ||
    (azure && (value.provider_config.auth_method ?? 'api_key') === 'api_key')
  const keyProblem = needsKey ? envNameProblem(value.api_key_env) : null
  const valid = value.name.trim() && value.model.trim() && (!needsEndpoint || value.base_url?.trim()) && !keyProblem
  const selectProvider = (provider: LlmConfigInput['provider']) => {
    const defaults: Partial<LlmConfigInput> = {
      provider,
      base_url:
        provider === 'openai' ? 'https://api.openai.com/v1' :
          provider === 'anthropic' ? 'https://api.anthropic.com' :
            provider === 'ollama' ? 'http://localhost:11434' : '',
      api_key_env:
        provider === 'openai' ? 'OPENAI_API_KEY' :
          provider === 'anthropic' ? 'ANTHROPIC_API_KEY' :
            provider === 'azure-foundry' ? 'AZURE_FOUNDRY_API_KEY' : '',
      provider_config: provider === 'azure-foundry'
        ? { deployment_type: 'azure-openai', auth_method: 'api_key', inference_parameters: {} }
        : { inference_parameters: {} },
    }
    set(defaults)
  }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="llm-dialog">
        <DialogHeader>
          <DialogTitle>{initial.name ? `Edit ${initial.name}` : 'Register an LLM'}</DialogTitle>
          <DialogDescription>
            Choose a provider-specific adapter. Credentials remain on the server; store only the environment-variable
            name here. Connection testing checks model access, not extraction quality.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field id="llm-name" label="Name">
            <Input id="llm-name" value={value.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field id="llm-provider" label="Provider">
            <NativeSelect
              id="llm-provider"
              value={value.provider}
              disabled={initial.provider === 'openai-compatible'}
              onChange={(e) => selectProvider(e.target.value as LlmConfigInput['provider'])}
            >
              {value.provider === 'openai-compatible' && <option value="openai-compatible">OpenAI-compatible (legacy)</option>}
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="azure-foundry">Azure AI Foundry</option>
              <option value="ollama">Ollama</option>
            </NativeSelect>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field id="llm-model" label="Model">
              <Input id="llm-model" className="font-mono text-xs" placeholder="qwen2.5:7b" value={value.model} onChange={(e) => set({ model: e.target.value })} />
            </Field>
            {needsKey && <Field id="llm-key-env" label="Credential environment variable" error={keyProblem}>
              <Input
                id="llm-key-env"
                className="font-mono text-xs"
                placeholder="SERVER_SIDE_API_KEY"
                autoComplete="off"
                aria-invalid={Boolean(keyProblem)}
                value={value.api_key_env ?? ''}
                onChange={(e) => set({ api_key_env: e.target.value })}
              />
            </Field>}
            {needsEndpoint && <Field id="llm-base-url" label={azure ? 'Foundry endpoint URL' : 'Base URL'}>
              <Input
                id="llm-base-url"
                className="font-mono text-xs"
                placeholder={value.provider === 'ollama' ? 'http://localhost:11434' : 'https://resource.services.ai.azure.com'}
                value={value.base_url ?? ''}
                onChange={(e) => set({ base_url: e.target.value })}
              />
            </Field>}
            {azure && <>
              <Field id="llm-azure-api" label="Deployment/API type">
                <NativeSelect
                  id="llm-azure-api"
                  value={String(value.provider_config.deployment_type ?? 'azure-openai')}
                  onChange={(e) => set({ provider_config: { ...value.provider_config, deployment_type: e.target.value } })}
                >
                  <option value="azure-openai">Azure OpenAI deployment</option>
                  <option value="openai-compatible">Foundry OpenAI-compatible model</option>
                  <option value="anthropic">Anthropic Claude in Foundry</option>
                </NativeSelect>
              </Field>
              <Field id="llm-azure-auth" label="Authentication">
                <NativeSelect
                  id="llm-azure-auth"
                  value={String(value.provider_config.auth_method ?? 'api_key')}
                  onChange={(e) => set({
                    provider_config: { ...value.provider_config, auth_method: e.target.value },
                    api_key_env: e.target.value === 'api_key' ? 'AZURE_FOUNDRY_API_KEY' : '',
                  })}
                >
                  <option value="api_key">API key</option>
                  <option value="entra_id">Microsoft Entra ID (server DefaultAzureCredential)</option>
                </NativeSelect>
              </Field>
            </>}
            <Field id="llm-temperature" label="Temperature">
              <Input
                id="llm-temperature"
                type="number"
                step={0.1}
                min={0}
                max={2}
                value={value.temperature}
                onChange={(e) => set({ temperature: Number(e.target.value) })}
              />
            </Field>
            <Field id="llm-timeout" label="Timeout (seconds)">
              <Input id="llm-timeout" type="number" min={5} value={value.timeout_seconds} onChange={(e) => set({ timeout_seconds: Number(e.target.value) })} />
            </Field>
            <Field id="llm-tokens" label="Max output tokens">
              <Input
                id="llm-tokens"
                type="number"
                min={256}
                value={value.max_output_tokens}
                onChange={(e) => set({ max_output_tokens: Number(e.target.value) })}
              />
            </Field>
          </div>
          <details className="rounded-md border px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium">Advanced inference settings</summary>
            <div className="grid grid-cols-2 gap-3 pt-3">
              <Field id="llm-top-p" label="Top P (optional)">
                <Input
                  id="llm-top-p"
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={String((value.provider_config.inference_parameters as Record<string, unknown> | undefined)?.top_p ?? '')}
                  onChange={(e) => set({
                    provider_config: {
                      ...value.provider_config,
                      inference_parameters: {
                        ...(value.provider_config.inference_parameters as Record<string, unknown> | undefined),
                        top_p: e.target.value === '' ? undefined : Number(e.target.value),
                      },
                    },
                  })}
                />
              </Field>
              {value.provider === 'anthropic' && <Field id="llm-top-k" label="Top K (optional)">
                <Input
                  id="llm-top-k"
                  type="number"
                  min={0}
                  value={String((value.provider_config.inference_parameters as Record<string, unknown> | undefined)?.top_k ?? '')}
                  onChange={(e) => set({
                    provider_config: {
                      ...value.provider_config,
                      inference_parameters: {
                        ...(value.provider_config.inference_parameters as Record<string, unknown> | undefined),
                        top_k: e.target.value === '' ? undefined : Number(e.target.value),
                      },
                    },
                  })}
                />
              </Field>}
            </div>
            <p className="pt-2 text-[11px] text-muted-foreground">Only parameters supported by the selected provider adapter are sent.</p>
          </details>
          <Field id="llm-description" label="Description">
            <Textarea id="llm-description" rows={2} value={value.description} onChange={(e) => set({ description: e.target.value })} />
          </Field>
        </div>
        {Boolean(error) && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(error)}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!valid || saving} onClick={() => onSave({
            ...value,
            base_url: value.base_url?.trim() || null,
            api_key_env: value.api_key_env?.trim() || null,
            provider_config: {
              ...value.provider_config,
              inference_parameters: Object.fromEntries(
                Object.entries((value.provider_config.inference_parameters as Record<string, unknown> | undefined) ?? {})
                  .filter(([, item]) => item !== undefined && item !== ''),
              ),
            },
          })}>
            {saving && <Loader2 className="animate-spin" />} Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function LlmCard() {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const configs = useLlmConfigs()
  const [editing, setEditing] = useState<LlmConfig | 'new' | null>(null)
  const [deleting, setDeleting] = useState<LlmConfig | null>(null)
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['settings'] })
    void queryClient.invalidateQueries({ queryKey: ['llm-status'] })
  }
  const save = useMutation({
    mutationFn: (value: LlmConfigInput) =>
      editing && editing !== 'new' ? settingsApi.updateLlm(editing.id, value, reviewer) : settingsApi.createLlm(value, reviewer),
    onSuccess: (config) => {
      toast.success(`LLM '${config.name}' saved`, { description: 'Test the connection to verify it.' })
      setEditing(null)
      refresh()
    },
  })
  const test = useMutation({
    mutationFn: (id: string) => settingsApi.testLlm(id),
    onSuccess: (config) => {
      if (config.last_test?.ok) toast.success(`${config.name}: connection OK`)
      else toast.error(`${config.name}: connection failed`, { description: config.last_test?.message })
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => settingsApi.deleteLlm(id, reviewer),
    onSuccess: () => {
      toast.success('LLM configuration deleted')
      refresh()
    },
    onError: (error) => toast.error('Cannot delete', { description: errorMessage(error) }),
    onSettled: () => setDeleting(null),
  })
  const activation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => settingsApi.setLlmEnabled(id, enabled, reviewer),
    onSuccess: (config) => {
      toast.success(config.enabled ? 'LLM configuration activated' : 'LLM configuration deactivated')
      refresh()
    },
    onError: (error) => toast.error('Cannot change activation', { description: errorMessage(error) }),
  })
  return (
    <Card data-testid="llm-configurations">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Bot className="size-4" /> LLM models
          </CardTitle>
          <CardDescription>Shared by projects. Test Connection verifies authenticated access to the selected model.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setEditing('new')} disabled={!reviewer} title={reviewer ? undefined : 'Set your reviewer name first'}>
          <Plus /> Register LLM
        </Button>
      </CardHeader>
      <CardContent>
        {configs.isPending ? (
          <LoadingState className="min-h-16" />
        ) : configs.isError ? (
          <ErrorState error={configs.error} onRetry={() => configs.refetch()} />
        ) : (
          <ul className="space-y-2">
            {configs.data.map((c) => (
              <li key={c.id} className="rounded-lg border p-3 text-sm" data-testid="llm-row">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.name}</span>
                  {c.builtin && <Badge variant="secondary">Built-in</Badge>}
                  {!c.enabled && <Badge variant="outline">Deactivated</Badge>}
                  {!c.configured && <Badge variant="outline">Not configured</Badge>}
                  <div className="ml-auto flex gap-1">
                    <Button
                      variant="outline"
                      size="xs"
                      onClick={() => test.mutate(c.id)}
                      disabled={!c.enabled || (test.isPending && test.variables === c.id)}
                    >
                      {test.isPending && test.variables === c.id ? <Loader2 className="animate-spin" /> : <PlugZap />} Test
                    </Button>
                    {!c.builtin && (
                      <>
                        <Button
                          variant="outline"
                          size="xs"
                          onClick={() => activation.mutate({ id: c.id, enabled: !c.enabled })}
                          disabled={!reviewer || activation.isPending}
                        >
                          {c.enabled ? 'Deactivate' : 'Activate'}
                        </Button>
                        <Button variant="ghost" size="icon-sm" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c)} disabled={!reviewer}>
                          <Pencil />
                        </Button>
                        <Button variant="ghost" size="icon-sm" aria-label={`Delete ${c.name}`} onClick={() => setDeleting(c)} disabled={!reviewer}>
                          <Trash2 />
                        </Button>
                      </>
                    )}
                  </div>
                </div>
                <p className="mt-1 font-mono text-xs text-muted-foreground break-all">
                  {c.model ?? '—'} · {c.base_url ?? 'no endpoint'} · {c.structured_output}
                </p>
                {c.api_key_env && (
                  <p className="mt-1 flex items-center gap-1 text-xs">
                    <KeyRound className="size-3" /> API key from <span className="font-mono">{c.api_key_env}</span>
                    {c.api_key_present ? ' (set on the server)' : ' (not set on the server)'}
                  </p>
                )}
                {c.used_by_projects.length > 0 && (
                  <p className="mt-1 text-xs text-muted-foreground">Default of: {c.used_by_projects.join(', ')}</p>
                )}
                <div className="mt-1.5">
                  <TestResult test={c.last_test} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      {editing && (
        <LlmDialog
          initial={
            editing === 'new'
              ? EMPTY_LLM
              : {
                  name: editing.name,
                  base_url: editing.base_url ?? '',
                  model: editing.model ?? '',
                    provider: editing.provider,
                    api_key_env: editing.api_key_env ?? '',
                    provider_config: editing.provider_config ?? {},
                  structured_output: editing.structured_output as LlmConfigInput['structured_output'],
                  temperature: editing.temperature,
                  timeout_seconds: editing.timeout_seconds,
                  max_output_tokens: editing.max_output_tokens,
                  description: editing.description,
                }
          }
          onClose={() => {
            setEditing(null)
            save.reset()
          }}
          onSave={(value) => save.mutate(value)}
          saving={save.isPending}
          error={save.error}
        />
      )}
      <AlertDialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete "{deleting?.name}"?</AlertDialogTitle>
            <AlertDialogDescription>
              Earlier builds and discovery runs keep the provider and model they recorded. A configuration that is the
              default of a project cannot be deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => deleting && remove.mutate(deleting.id)}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

// ------------------------------------------------------------------------------------ graph connections

/** Initial values of a provider's form: every visible-by-default, non-secret field with a catalogue default. */
function defaultsOf(kind: GraphKind | undefined): Record<string, string> {
  return Object.fromEntries((kind?.fields ?? []).filter((f) => !f.secret && f.default).map((f) => [f.key, f.default]))
}

function GraphDialog({
  kinds,
  initial,
  onClose,
  onSave,
  saving,
  error,
}: {
  kinds: GraphKind[]
  initial: GraphConnectionInput
  onClose: () => void
  onSave: (value: GraphConnectionInput) => void
  saving: boolean
  error: unknown
}) {
  const registrable = kinds.filter((k) => k.registrable && k.available)
  const [value, setValue] = useState<GraphConnectionInput>(() =>
    initial.kind ? initial : { ...initial, kind: registrable[0]?.id ?? '', config: defaultsOf(registrable[0]) },
  )
  const kind = kinds.find((k) => k.id === value.kind)
  const set = (patch: Partial<GraphConnectionInput>) => setValue((v) => ({ ...v, ...patch }))
  const setField = (key: string, fieldValue: string) => setValue((v) => ({ ...v, config: { ...v.config, [key]: fieldValue } }))
  const selectProvider = (id: string) =>
    setValue((v) => ({ ...v, kind: id, config: defaultsOf(kinds.find((k) => k.id === id)), secret_env: '' }))
  const visible = (f: GraphKindField) => !f.visible_when || f.visible_when.values.includes(value.config[f.visible_when.field] ?? '')
  const shown = (kind?.fields ?? []).filter(visible)
  const secretField = shown.find((f) => f.secret)
  const secretProblem = secretField ? envNameProblem(value.secret_env) : null
  const valid =
    value.name.trim() &&
    kind &&
    !secretProblem &&
    shown.every((f) => !f.required || (f.secret ? Boolean(value.secret_env?.trim()) : Boolean(value.config[f.key]?.trim())))
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-h-[90vh] sm:max-w-lg overflow-y-auto" data-testid="graph-dialog">
        <DialogHeader>
          <DialogTitle>{initial.name ? `Edit ${initial.name}` : 'Register a graph database'}</DialogTitle>
          <DialogDescription>
            Choose a provider; its connection fields appear below. Credentials stay on the server: enter the name of the
            environment variable that holds them, never the secret itself. Testing verifies connectivity and authentication
            only, not write permission.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field id="graph-name" label="Configuration name">
            <Input id="graph-name" value={value.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field id="graph-kind" label="Graph database provider">
            <NativeSelect id="graph-kind" value={value.kind} disabled={Boolean(initial.name)} onChange={(e) => selectProvider(e.target.value)}>
              {registrable.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          {kind && (
            <div className="space-y-1 rounded-md border bg-muted/30 p-3 text-xs" data-testid="provider-summary">
              <p>{kind.description}</p>
              <p>
                <span className="font-medium">Graph data model:</span> {kind.model === 'rdf' ? 'RDF graph' : 'Property graph'}
                {' · '}
                <span className="font-medium">Protocol:</span> {kind.protocol}
              </p>
              <p className={kind.live_tested ? 'text-emerald-700' : 'text-amber-700'}>
                {kind.live_tested ? 'Adapter verified against a live server. ' : 'Adapter not yet verified against a live server. '}
                {kind.verification_note}
              </p>
            </div>
          )}
          {shown.map((f) => {
            const id = `graph-${f.key}`
            const label = `${f.label}${f.required ? '' : ' (optional)'}`
            if (f.secret) {
              return (
                <Field key={f.key} id={id} label={label} hint={f.help} error={secretProblem}>
                  <Input
                    id={id}
                    className="font-mono text-xs"
                    placeholder={f.placeholder}
                    autoComplete="off"
                    aria-invalid={Boolean(secretProblem)}
                    value={value.secret_env ?? ''}
                    onChange={(e) => set({ secret_env: e.target.value })}
                  />
                </Field>
              )
            }
            if (f.type === 'select') {
              return (
                <Field key={f.key} id={id} label={label}>
                  <NativeSelect id={id} value={value.config[f.key] ?? f.default} onChange={(e) => setField(f.key, e.target.value)}>
                    {f.options.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
              )
            }
            const numeric = f.type === 'number' || f.type === 'integer'
            return (
              <Field key={f.key} id={id} label={label} hint={f.help}>
                <Input
                  id={id}
                  className="font-mono text-xs"
                  type={numeric ? 'number' : 'text'}
                  min={f.minimum ?? undefined}
                  max={f.maximum ?? undefined}
                  step={f.type === 'integer' ? 1 : undefined}
                  placeholder={f.placeholder}
                  autoComplete="off"
                  value={value.config[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                />
              </Field>
            )
          })}
          <Field id="graph-description" label="Description (optional)">
            <Textarea id="graph-description" rows={2} value={value.description} onChange={(e) => set({ description: e.target.value })} />
          </Field>
          <label className="flex items-center gap-2 text-xs">
            <Checkbox checked={value.enabled} onCheckedChange={(checked) => set({ enabled: checked === true })} aria-label="Enabled" />
            Enabled (selectable for projects and deployments)
          </label>
        </div>
        {Boolean(error) && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(error)}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!valid || saving}
            onClick={() =>
              onSave({
                ...value,
                config: Object.fromEntries(
                  shown.filter((f) => !f.secret).map((f) => [f.key, (value.config[f.key] ?? '').trim()] as const).filter(([, v]) => v),
                ),
                secret_env: secretField ? value.secret_env?.trim() || null : null,
              })
            }
          >
            {saving && <Loader2 className="animate-spin" />} Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function GraphCard() {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const connections = useGraphConnections()
  const kinds = useGraphKinds()
  const [editing, setEditing] = useState<GraphConnection | 'new' | null>(null)
  const [deleting, setDeleting] = useState<GraphConnection | null>(null)
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['settings'] })
  const save = useMutation({
    mutationFn: (value: GraphConnectionInput) =>
      editing && editing !== 'new'
        ? settingsApi.updateGraph(editing.id, value, reviewer)
        : settingsApi.createGraph(value, reviewer),
    onSuccess: (connection) => {
      toast.success(`Graph database '${connection.name}' saved`, { description: 'Test the connection to verify it.' })
      setEditing(null)
      refresh()
    },
  })
  const test = useMutation({
    mutationFn: (id: string) => settingsApi.testGraph(id),
    onSuccess: (connection) => {
      if (connection.last_test?.ok) toast.success(`${connection.name}: connection OK`)
      else toast.error(`${connection.name}: connection failed`, { description: connection.last_test?.message })
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => settingsApi.deleteGraph(id, reviewer),
    onSuccess: () => {
      toast.success('Graph connection deleted')
      refresh()
    },
    onError: (error) => toast.error('Cannot delete', { description: errorMessage(error) }),
    onSettled: () => setDeleting(null),
  })
  const activation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => settingsApi.setGraphEnabled(id, enabled, reviewer),
    onSuccess: (connection) => {
      toast.success(`${connection.name} ${connection.enabled ? 'enabled' : 'disabled'}`)
      refresh()
    },
    onError: (error) => toast.error('Cannot change activation', { description: errorMessage(error) }),
  })
  const makeDefault = useMutation({
    mutationFn: (id: string) => settingsApi.setDefaultGraph(id, reviewer),
    onSuccess: (connection) => {
      toast.success(`${connection.name} is now preselected for new projects`, { description: 'Existing projects are unchanged.' })
      refresh()
    },
    onError: (error) => toast.error('Cannot set the default', { description: errorMessage(error) }),
  })
  const unavailable = (kinds.data ?? []).filter((k) => !k.available)
  return (
    <Card data-testid="graph-connections">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Database className="size-4" /> Graph databases
          </CardTitle>
          <CardDescription>
            Targets for knowledge-graph deployment. Test Connection runs a read-only, provider-specific check on the server and
            verifies connectivity and authentication, not write permission or deployment readiness.
          </CardDescription>
        </div>
        <Button size="sm" onClick={() => setEditing('new')} disabled={!reviewer || !kinds.data} title={reviewer ? undefined : 'Set your reviewer name first'}>
          <Plus /> Register database
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {connections.isPending ? (
          <LoadingState className="min-h-16" />
        ) : connections.isError ? (
          <ErrorState error={connections.error} onRetry={() => connections.refetch()} />
        ) : (
          <ul className="space-y-2">
            {connections.data.map((c) => (
              <li key={c.id} className="rounded-lg border p-3 text-sm" data-testid="graph-row" data-provider={c.provider} data-status={c.status}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.name}</span>
                  <Badge variant="outline">{c.kind_label}</Badge>
                  <Badge variant="outline">{c.model === 'rdf' ? 'RDF graph' : 'Property graph'}</Badge>
                  {c.builtin && <Badge variant="secondary">Built-in</Badge>}
                  {c.is_default && <Badge variant="secondary">Default for new projects</Badge>}
                  {!c.enabled && <Badge variant="outline">Disabled</Badge>}
                  <GraphStatusBadge status={c.status} />
                  <div className="ml-auto flex flex-wrap gap-1">
                    <Button variant="outline" size="xs" onClick={() => test.mutate(c.id)} disabled={test.isPending && test.variables === c.id}>
                      {test.isPending && test.variables === c.id ? <Loader2 className="animate-spin" /> : <PlugZap />} Test
                    </Button>
                    {!c.builtin && (
                      <Button
                        variant="outline"
                        size="xs"
                        onClick={() => activation.mutate({ id: c.id, enabled: !c.enabled })}
                        disabled={!reviewer || activation.isPending}
                      >
                        {c.enabled ? 'Disable' : 'Enable'}
                      </Button>
                    )}
                    {!c.is_default && c.id !== 'oxigraph-embedded' && c.enabled && (
                      <Button variant="outline" size="xs" onClick={() => makeDefault.mutate(c.id)} disabled={!reviewer || makeDefault.isPending}>
                        Set default
                      </Button>
                    )}
                    {!c.builtin && (
                      <>
                        <Button variant="ghost" size="icon-sm" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c)} disabled={!reviewer}>
                          <Pencil />
                        </Button>
                        <Button variant="ghost" size="icon-sm" aria-label={`Delete ${c.name}`} onClick={() => setDeleting(c)} disabled={!reviewer}>
                          <Trash2 />
                        </Button>
                      </>
                    )}
                  </div>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {c.protocol}
                  {Object.entries(c.config).map(([k, v]) => (
                    <span key={k} className="block font-mono break-all">
                      {k}: {v}
                    </span>
                  ))}
                  {Object.entries(c.effective_endpoints)
                    .filter(([k]) => !(`${k}_url` in c.config))
                    .map(([k, v]) => (
                      <span key={k} className="block font-mono break-all">
                        {k} endpoint: {v ?? 'none (read-only)'}
                      </span>
                    ))}
                </p>
                {c.secret_env && (
                  <p className="mt-1 flex items-center gap-1 text-xs">
                    <KeyRound className="size-3" /> Credential from <span className="font-mono">{c.secret_env}</span>
                    {c.secret_present ? ' (set on the server)' : ' (not set on the server)'}
                  </p>
                )}
                {c.used_by_projects.length > 0 && (
                  <p className="mt-1 text-xs text-muted-foreground">Default of: {c.used_by_projects.join(', ')}</p>
                )}
                <GraphCapabilityChips connection={c} />
                <div className="mt-1.5">
                  <TestResult test={c.last_test} />
                </div>
                {c.capabilities.deployment_verified && (
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {c.deployment_count} deployment{c.deployment_count === 1 ? '' : 's'} recorded
                    {c.capabilities.last_deployment_at ? ` · last verified ${relativeTime(c.capabilities.last_deployment_at)}` : ''}.
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        {unavailable.length > 0 && (
          <div className="rounded-lg border border-dashed p-3 text-xs" data-testid="unavailable-kinds">
            <p className="font-medium">Not available in this installation</p>
            <ul className="mt-1 space-y-1 text-muted-foreground">
              {unavailable.map((k) => (
                <li key={k.id}>
                  <span className="font-medium text-foreground">{k.label}</span>: {k.unavailable_reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
      {editing && kinds.data && (
        <GraphDialog
          kinds={kinds.data}
          initial={
            editing === 'new'
              ? { name: '', kind: '', config: {}, secret_env: '', enabled: true, description: '' }
              : {
                  name: editing.name,
                  kind: editing.kind,
                  config: editing.config,
                  secret_env: editing.secret_env ?? '',
                  enabled: editing.enabled,
                  description: editing.description,
                }
          }
          onClose={() => {
            setEditing(null)
            save.reset()
          }}
          onSave={(value) => save.mutate(value)}
          saving={save.isPending}
          error={save.error}
        />
      )}
      <AlertDialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete "{deleting?.name}"?</AlertDialogTitle>
            <AlertDialogDescription>
              Data already deployed to the database is not removed, and its {deleting?.deployment_count ?? 0} recorded
              deployment(s) stay readable through the settings they were written with. A connection that is a project default
              cannot be deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => deleting && remove.mutate(deleting.id)}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

export function SettingsPage() {
  const { projectId, project } = useProjectScope()
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-7xl space-y-6 p-6" data-testid="settings-page">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <SettingsIcon className="size-5" /> Settings
          </h1>
          <p className="text-sm text-muted-foreground">
            Register, test and manage LLM models and graph databases. Secrets are referenced by environment-variable name
            and never stored or shown.
          </p>
        </div>
        <ProjectDefaultsCard projectId={projectId} projectName={project?.name ?? 'this project'} />
        <div className="grid gap-6 xl:grid-cols-2">
          <LlmCard />
          <GraphCard />
        </div>
      </div>
    </div>
  )
}
