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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { projectsApi, settingsApi } from '@/lib/api/endpoints'
import type { ConnectionTest, GraphConnection, GraphConnectionInput, GraphKind, LlmConfig, LlmConfigInput } from '@/lib/api/types'
import { relativeTime } from '@/lib/format'
import { NativeSelect } from '@/features/kg/fields'
import { useReviewerName } from '@/features/ontology/governance/reviewer'
import { useProjectScope } from '@/features/projects/hooks'
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

function Field({ id, label, hint, children }: { id: string; label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  )
}

// ------------------------------------------------------------------------------------ project defaults

function ProjectDefaultsCard({ projectId, projectName }: { projectId: string; projectName: string }) {
  const queryClient = useQueryClient()
  const [reviewer] = useReviewerName()
  const defaults = useProjectDefaults(projectId)
  const [draft, setDraft] = useState<{ llm: string; graph: string; namespace: string } | null>(null)
  const current = draft ?? {
    llm: defaults.data?.default_llm_config_id ?? '',
    graph: defaults.data?.default_graph_connection_id ?? '',
    namespace: defaults.data?.data_namespace ?? '',
  }
  const save = useMutation({
    mutationFn: () =>
      projectsApi.updateDefaults(
        projectId,
        { default_llm_config_id: current.llm, default_graph_connection_id: current.graph, data_namespace: current.namespace },
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
          <div className="grid gap-4 md:grid-cols-3">
            <Field id="default-llm" label="Default LLM">
              <LlmConfigSelect id="default-llm" allowProjectDefault={false} value={current.llm} onChange={(v) => set({ llm: v ?? '' })} />
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
            <div className="flex items-center justify-end gap-2 md:col-span-3">
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
  base_url: '',
  model: '',
  api_key_env: '',
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
  const valid = value.name.trim() && value.base_url.trim() && value.model.trim()
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="llm-dialog">
        <DialogHeader>
          <DialogTitle>{initial.name ? `Edit ${initial.name}` : 'Register an LLM'}</DialogTitle>
          <DialogDescription>
            Any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, Azure OpenAI, OpenAI). The API key stays on the
            server: enter the name of the environment variable that holds it.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field id="llm-name" label="Name">
            <Input id="llm-name" value={value.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field id="llm-base-url" label="Base URL">
            <Input
              id="llm-base-url"
              className="font-mono text-xs"
              placeholder="http://localhost:11434/v1"
              value={value.base_url}
              onChange={(e) => set({ base_url: e.target.value })}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field id="llm-model" label="Model">
              <Input id="llm-model" className="font-mono text-xs" placeholder="qwen2.5:7b" value={value.model} onChange={(e) => set({ model: e.target.value })} />
            </Field>
            <Field id="llm-key-env" label="API key environment variable">
              <Input
                id="llm-key-env"
                className="font-mono text-xs"
                placeholder="OLS_MY_LLM_KEY (optional)"
                value={value.api_key_env ?? ''}
                onChange={(e) => set({ api_key_env: e.target.value })}
              />
            </Field>
            <Field id="llm-structured" label="Structured output">
              <NativeSelect
                id="llm-structured"
                value={value.structured_output}
                onChange={(e) => set({ structured_output: e.target.value as LlmConfigInput['structured_output'] })}
              >
                <option value="json_schema">JSON schema</option>
                <option value="json_object">JSON object</option>
                <option value="prompt">Prompt only</option>
              </NativeSelect>
            </Field>
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
          <Button disabled={!valid || saving} onClick={() => onSave({ ...value, api_key_env: value.api_key_env?.trim() || null })}>
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
  return (
    <Card data-testid="llm-configurations">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Bot className="size-4" /> LLM models
          </CardTitle>
          <CardDescription>Shared by all projects. Tests call the endpoint's model list; no prompt is sent.</CardDescription>
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
                  {!c.configured && <Badge variant="outline">Not configured</Badge>}
                  <div className="ml-auto flex gap-1">
                    <Button
                      variant="outline"
                      size="xs"
                      onClick={() => test.mutate(c.id)}
                      disabled={!c.configured || (test.isPending && test.variables === c.id)}
                    >
                      {test.isPending && test.variables === c.id ? <Loader2 className="animate-spin" /> : <PlugZap />} Test
                    </Button>
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
                  api_key_env: editing.api_key_env ?? '',
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
  const [value, setValue] = useState<GraphConnectionInput>(initial.kind ? initial : { ...initial, kind: registrable[0]?.id ?? '' })
  const kind = kinds.find((k) => k.id === value.kind)
  const set = (patch: Partial<GraphConnectionInput>) => setValue((v) => ({ ...v, ...patch }))
  const valid = value.name.trim() && kind && kind.fields.every((f) => f.secret || !f.required || value.config[f.key]?.trim())
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="graph-dialog">
        <DialogHeader>
          <DialogTitle>{initial.name ? `Edit ${initial.name}` : 'Register a graph database'}</DialogTitle>
          <DialogDescription>Passwords stay on the server: enter the name of the environment variable that holds it.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field id="graph-name" label="Name">
            <Input id="graph-name" value={value.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field id="graph-kind" label="Database kind" hint={kind?.description}>
            <NativeSelect id="graph-kind" value={value.kind} disabled={Boolean(initial.name)} onChange={(e) => set({ kind: e.target.value, config: {} })}>
              {registrable.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          {kind?.fields.map((f) =>
            f.secret ? (
              <Field key={f.key} id={`graph-${f.key}`} label={f.label}>
                <Input
                  id={`graph-${f.key}`}
                  className="font-mono text-xs"
                  placeholder={f.placeholder}
                  value={value.secret_env ?? ''}
                  onChange={(e) => set({ secret_env: e.target.value })}
                />
              </Field>
            ) : (
              <Field key={f.key} id={`graph-${f.key}`} label={`${f.label}${f.required ? '' : ' (optional)'}`}>
                <Input
                  id={`graph-${f.key}`}
                  className="font-mono text-xs"
                  placeholder={f.placeholder}
                  value={value.config[f.key] ?? ''}
                  onChange={(e) => set({ config: { ...value.config, [f.key]: e.target.value } })}
                />
              </Field>
            ),
          )}
          <Field id="graph-description" label="Description">
            <Textarea id="graph-description" rows={2} value={value.description} onChange={(e) => set({ description: e.target.value })} />
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
          <Button
            disabled={!valid || saving}
            onClick={() =>
              onSave({
                ...value,
                config: Object.fromEntries(Object.entries(value.config).filter(([, v]) => v.trim())),
                secret_env: value.secret_env?.trim() || null,
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
  const unavailable = (kinds.data ?? []).filter((k) => !k.available)
  return (
    <Card data-testid="graph-connections">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Database className="size-4" /> Graph databases
          </CardTitle>
          <CardDescription>Targets for knowledge-graph deployment. Tests are read-only.</CardDescription>
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
              <li key={c.id} className="rounded-lg border p-3 text-sm" data-testid="graph-row">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.name}</span>
                  <Badge variant="outline">{c.model === 'rdf' ? 'RDF' : 'Property graph'}</Badge>
                  {c.builtin && <Badge variant="secondary">Built-in</Badge>}
                  <div className="ml-auto flex gap-1">
                    <Button variant="outline" size="xs" onClick={() => test.mutate(c.id)} disabled={test.isPending && test.variables === c.id}>
                      {test.isPending && test.variables === c.id ? <Loader2 className="animate-spin" /> : <PlugZap />} Test
                    </Button>
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
                  {c.kind_label}
                  {Object.entries(c.config).map(([k, v]) => (
                    <span key={k} className="block font-mono break-all">
                      {k}: {v}
                    </span>
                  ))}
                </p>
                {c.secret_env && (
                  <p className="mt-1 flex items-center gap-1 text-xs">
                    <KeyRound className="size-3" /> Password from <span className="font-mono">{c.secret_env}</span>
                    {c.secret_present ? ' (set on the server)' : ' (not set on the server)'}
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
              ? { name: '', kind: '', config: {}, secret_env: '', description: '' }
              : { name: editing.name, kind: editing.kind, config: editing.config, secret_env: editing.secret_env ?? '', description: editing.description }
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
              Data already deployed to the database is not removed. A connection that is a project default cannot be deleted.
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
