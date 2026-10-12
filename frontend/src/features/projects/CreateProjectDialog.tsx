import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage } from '@/lib/api/client'
import { projectsApi } from '@/lib/api/endpoints'
import { slugify } from '@/lib/naming'
import { queryKeys } from '@/lib/query'
import { GraphTargetSelect, LlmConfigSelect } from '@/features/settings/selectors'

interface FormState {
  name: string
  businessDomain: string
  description: string
  ontologyName: string
  namespace: string
  prefix: string
  discoveryLlmConfigId: string
  kgLlmConfigId: string
  graphConnectionId: string
}

const EMPTY: FormState = {
  name: '',
  businessDomain: '',
  description: '',
  ontologyName: '',
  namespace: '',
  prefix: '',
  discoveryLlmConfigId: 'env-default',
  kgLlmConfigId: 'env-default',
  graphConnectionId: 'local-sql',
}

function derivePrefix(name: string): string {
  const initials = name
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((w) => w[0]!.toLowerCase())
    .join('')
  const prefix = initials.length >= 2 ? initials : slugify(name).replace(/-/g, '').slice(0, 4)
  return /^[a-z]/.test(prefix) ? prefix : `o${prefix}`
}

export function CreateProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [form, setForm] = useState<FormState>(EMPTY)
  const [ontologyTouched, setOntologyTouched] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const derived = (name: string) => ({
    ontologyName: name.trim() ? `${name.trim()} Core` : '',
    namespace: name.trim() ? `https://example.com/ontology/${slugify(name) || 'domain'}#` : '',
    prefix: name.trim() ? derivePrefix(name) : '',
  })

  const mutation = useMutation({
    mutationFn: () =>
      projectsApi.create({
        name: form.name,
        business_domain: form.businessDomain,
        description: form.description,
        initial_ontology: {
          name: form.ontologyName,
          namespace: form.namespace,
          prefix: form.prefix,
          description: '',
        },
        default_discovery_llm_config_id: form.discoveryLlmConfigId,
        default_kg_llm_config_id: form.kgLlmConfigId,
        default_graph_connection_id: form.graphConnectionId,
      }),
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects })
      toast.success(`Project "${project.name}" created`)
      onOpenChange(false)
      setForm(EMPTY)
      setOntologyTouched(false)
      navigate(`/projects/${project.id}/workspace`)
    },
  })

  const update = (patch: Partial<FormState>) => setForm((prev) => ({ ...prev, ...patch }))
  const canSubmit = form.name.trim() && form.ontologyName.trim() && form.namespace.trim() && form.prefix.trim()

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (canSubmit && !mutation.isPending) mutation.mutate()
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) mutation.reset()
        onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>Create project</DialogTitle>
            <DialogDescription>
              A project groups the governed ontology, data sources and knowledge graph for one business domain.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor="project-name">Project name</Label>
              <Input
                id="project-name"
                autoFocus
                value={form.name}
                placeholder="e.g. Clinical Trials"
                onChange={(e) =>
                  update({ name: e.target.value, ...(ontologyTouched ? {} : derived(e.target.value)) })
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="project-domain">Business domain</Label>
              <Input
                id="project-domain"
                value={form.businessDomain}
                placeholder="e.g. Life Sciences"
                onChange={(e) => update({ businessDomain: e.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="project-description">Description</Label>
              <Textarea
                id="project-description"
                rows={2}
                value={form.description}
                onChange={(e) => update({ description: e.target.value })}
              />
            </div>

            <div className="rounded-lg border bg-muted/30 p-4">
              <p className="text-sm font-medium">Initial ontology</p>
              <p className="mb-3 text-xs text-muted-foreground">An empty draft ontology is created with the project.</p>
              <div className="grid gap-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="ontology-name">Ontology name</Label>
                  <Input
                    id="ontology-name"
                    value={form.ontologyName}
                    onChange={(e) => {
                      setOntologyTouched(true)
                      update({ ontologyName: e.target.value })
                    }}
                  />
                </div>
                <div className="grid grid-cols-[1fr_96px] gap-3">
                  <div className="grid gap-1.5">
                    <Label htmlFor="ontology-namespace">Namespace IRI</Label>
                    <Input
                      id="ontology-namespace"
                      className="font-mono text-xs"
                      value={form.namespace}
                      onChange={(e) => {
                        setOntologyTouched(true)
                        update({ namespace: e.target.value })
                      }}
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="ontology-prefix">Prefix</Label>
                    <Input
                      id="ontology-prefix"
                      className="font-mono text-xs"
                      value={form.prefix}
                      onChange={(e) => {
                        setOntologyTouched(true)
                        update({ prefix: e.target.value })
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 rounded-lg border bg-muted/30 p-4">
            <p className="col-span-2 text-sm font-medium">
              Defaults <span className="text-xs font-normal text-muted-foreground">(registered in Settings; changeable later)</span>
            </p>
            <div className="grid gap-1.5">
              <Label htmlFor="project-discovery-llm">Ontology Discovery LLM</Label>
              <LlmConfigSelect
                id="project-discovery-llm"
                allowProjectDefault={false}
                value={form.discoveryLlmConfigId}
                onChange={(v) => update({ discoveryLlmConfigId: v ?? 'env-default' })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="project-kg-llm">KG Extraction LLM</Label>
              <LlmConfigSelect
                id="project-kg-llm"
                allowProjectDefault={false}
                value={form.kgLlmConfigId}
                onChange={(v) => update({ kgLlmConfigId: v ?? 'env-default' })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="project-graph">Graph database</Label>
              <GraphTargetSelect
                id="project-graph"
                allowProjectDefault={false}
                value={form.graphConnectionId}
                onChange={(v) => update({ graphConnectionId: v ?? 'local-sql' })}
              />
            </div>
          </div>

          {mutation.isError && (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(mutation.error)}</AlertDescription>
            </Alert>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit || mutation.isPending}>
              {mutation.isPending && <Loader2 className="animate-spin" />}
              Create project
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
