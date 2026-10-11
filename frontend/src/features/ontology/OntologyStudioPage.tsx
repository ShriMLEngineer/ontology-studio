import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Network } from 'lucide-react'
import { useBlocker, useSearchParams } from 'react-router'

import { PhaseNotice } from '@/components/common/PhaseNotice'
import { EmptyState, ErrorState, LoadingState } from '@/components/common/states'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { validationApi } from '@/lib/api/endpoints'
import type { ValidationIssue } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import { useProjectScope } from '@/features/projects/hooks'
import type { ElementSelection } from './draft/model'
import { useDraftEditor } from './draft/useDraftEditor'
import { DesignerView, type FocusRequest } from './designer/DesignerView'
import { ValidationView } from './validation/ValidationView'

const TABS = ['designer', 'discovery', 'review', 'validation', 'registry'] as const
type StudioTab = (typeof TABS)[number]

export function OntologyStudioPage() {
  const { projectId, ontologies, activeOntology } = useProjectScope()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab') as StudioTab | null
  const tab: StudioTab = requestedTab && TABS.includes(requestedTab) ? requestedTab : 'designer'

  const editor = useDraftEditor(activeOntology?.id)
  const [selection, setSelection] = useState<ElementSelection | null>(null)
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null)

  const latestValidation = useQuery({
    queryKey: queryKeys.latestValidation(activeOntology?.id ?? ''),
    queryFn: () => validationApi.latest(activeOntology!.id),
    enabled: Boolean(activeOntology),
  })

  const setTab = useCallback(
    (next: string) =>
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          params.set('tab', next)
          return params
        },
        { replace: true },
      ),
    [setSearchParams],
  )

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => editor.dirty && currentLocation.pathname !== nextLocation.pathname,
  )

  useEffect(() => {
    if (!editor.dirty) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [editor.dirty])

  const showIssue = useCallback(
    (issue: ValidationIssue) => {
      const doc = editor.doc
      let target: ElementSelection = { kind: 'ontology' }
      let focusId: string | null = null
      if (issue.element_id && issue.element_kind !== 'ontology') {
        target = { kind: issue.element_kind, id: issue.element_id }
        if (issue.element_kind === 'class') focusId = issue.element_id
        if (issue.element_kind === 'object_property')
          focusId = doc?.object_properties.find((p) => p.id === issue.element_id)?.domain_id ?? null
        if (issue.element_kind === 'datatype_property')
          focusId = doc?.datatype_properties.find((p) => p.id === issue.element_id)?.domain_id ?? null
      }
      setSelection(target)
      if (focusId) setFocusRequest({ id: focusId, nonce: Date.now() })
      setTab('designer')
    },
    [editor.doc, setTab],
  )

  if (ontologies.isPending) return <LoadingState label="Loading ontology…" />
  if (ontologies.isError)
    return <ErrorState className="m-6" title="Unable to load ontologies" error={ontologies.error} onRetry={() => ontologies.refetch()} />
  if (!activeOntology)
    return (
      <EmptyState
        className="m-6"
        icon={<Network />}
        title="This project has no ontology"
        description="Ontologies are created together with a project."
      />
    )

  const body = (() => {
    if (editor.query.isError)
      return <ErrorState className="m-6" title="Unable to load the ontology draft" error={editor.query.error} onRetry={() => editor.query.refetch()} />
    if (!editor.doc) return <LoadingState label="Loading ontology draft…" />
    return null
  })()

  return (
    <Tabs value={tab} onValueChange={setTab} className="flex h-full min-h-0 flex-col gap-0">
      <div className="shrink-0 border-b bg-background px-6 pt-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="text-xl font-semibold tracking-tight">{editor.doc?.metadata.name ?? activeOntology.name}</h1>
          <Badge variant="secondary">Draft · revision {editor.base?.draft_revision ?? activeOntology.draft_revision}</Badge>
          {editor.dirty && (
            <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-800">
              Unsaved changes
            </Badge>
          )}
          <span className="font-mono text-xs text-muted-foreground">{editor.doc?.metadata.namespace ?? activeOntology.namespace}</span>
        </div>
        <TabsList variant="line" className="mt-3 h-10">
          <TabsTrigger value="designer">Ontology Designer</TabsTrigger>
          <TabsTrigger value="discovery">AI Discovery</TabsTrigger>
          <TabsTrigger value="review">SME Review</TabsTrigger>
          <TabsTrigger value="validation">
            Validation
            {latestValidation.data && !latestValidation.data.is_valid && (
              <span className="ml-1 rounded-full bg-red-100 px-1.5 text-[10px] font-semibold text-red-700">
                {latestValidation.data.error_count}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="registry">Registry</TabsTrigger>
        </TabsList>
      </div>

      <TabsContent value="designer" className="min-h-0 flex-1">
        {body ??
          (editor.doc && (
            <DesignerView
              editor={editor}
              doc={editor.doc}
              selection={selection}
              onSelect={setSelection}
              focusRequest={focusRequest}
              onFocusHandled={() => setFocusRequest(null)}
              report={latestValidation.data}
            />
          ))}
      </TabsContent>
      <TabsContent value="validation" className="min-h-0 flex-1 overflow-y-auto">
        {body ?? (
          <ValidationView
            projectId={projectId}
            ontologyId={activeOntology.id}
            editor={editor}
            latest={latestValidation}
            onShowIssue={showIssue}
          />
        )}
      </TabsContent>
      <TabsContent value="discovery" className="min-h-0 flex-1 overflow-y-auto p-6">
        <PhaseNotice
          phase={2}
          title="AI-assisted discovery"
          description="Use an LLM to propose ontology content from source documents. Proposals are never applied automatically - they enter SME review."
          capabilities={[
            'Generate a seed ontology from document content',
            'Analyse documents against the current ontology',
            'Propose reuse, additions, modifications and aliases',
            'Flag potential conflicts with evidence and explanations',
          ]}
        />
      </TabsContent>
      <TabsContent value="review" className="min-h-0 flex-1 overflow-y-auto p-6">
        <PhaseNotice
          phase={2}
          title="SME review & governance"
          description="Domain experts review proposed ontology changes and decide what becomes governed meaning."
          capabilities={[
            'Compare current and proposed definitions',
            'Edit proposals before deciding',
            'Approve, reject or request refinement',
            'Record comments and an auditable decision trail',
          ]}
        />
      </TabsContent>
      <TabsContent value="registry" className="min-h-0 flex-1 overflow-y-auto p-6">
        <PhaseNotice
          phase={2}
          title="Ontology registry"
          description="Publish validated drafts as immutable versions that knowledge graph construction can depend on."
          capabilities={[
            'Publish immutable ontology versions',
            'Browse version history and compare versions',
            'Export to JSON and Turtle / OWL',
            'Select an approved version for KG construction',
          ]}
        />
      </TabsContent>

      <AlertDialog open={blocker.state === 'blocked'}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave with unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Your ontology draft has changes that have not been saved. If you leave now they will be lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.reset?.()}>Stay and keep editing</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => blocker.proceed?.()}>
              Discard and leave
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Tabs>
  )
}
