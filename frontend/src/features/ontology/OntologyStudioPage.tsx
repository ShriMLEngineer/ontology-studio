import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Network } from 'lucide-react'
import { useBlocker, useSearchParams } from 'react-router'

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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { governanceApi, validationApi } from '@/lib/api/endpoints'
import type { ValidationIssue } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import { useProjectScope } from '@/features/projects/hooks'
import type { ElementSelection } from './draft/model'
import { useDraftEditor } from './draft/useDraftEditor'
import { DesignerView, type FocusRequest } from './designer/DesignerView'
import { DiscoveryView } from './discovery/DiscoveryView'
import { ReviewerControl } from './governance/ReviewerControl'
import { RegistryView } from './registry/RegistryView'
import { ReviewView } from './review/ReviewView'
import { SemanticsView } from './semantics/SemanticsView'
import { ShapesView } from './shapes/ShapesView'
import { ValidationView } from './validation/ValidationView'

const TABS = ['designer', 'discovery', 'review', 'validation', 'semantics', 'shapes', 'registry'] as const
type StudioTab = (typeof TABS)[number]
type ElementKind = 'class' | 'object_property' | 'datatype_property'

export function OntologyStudioPage() {
  const { projectId, ontologies, activeOntology } = useProjectScope()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab') as StudioTab | null
  const tab: StudioTab = requestedTab && TABS.includes(requestedTab) ? requestedTab : 'designer'

  const editor = useDraftEditor(activeOntology?.id)
  const [selection, setSelection] = useState<ElementSelection | null>(null)
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null)
  const [runFilter, setRunFilter] = useState<string | null>(null)

  const latestValidation = useQuery({
    queryKey: queryKeys.latestValidation(activeOntology?.id ?? ''),
    queryFn: () => validationApi.latest(activeOntology!.id),
    enabled: Boolean(activeOntology),
  })
  const proposalStats = useQuery({
    queryKey: queryKeys.proposalStats(activeOntology?.id ?? ''),
    queryFn: () => governanceApi.stats(activeOntology!.id),
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

  const switchOntology = useCallback(
    (ontologyId: string) =>
      setSearchParams((prev) => {
        const params = new URLSearchParams(prev)
        params.set('ontology', ontologyId)
        return params
      }),
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

  const showElement = useCallback(
    (kind: ElementKind | 'ontology', elementId: string | null) => {
      const doc = editor.doc
      let target: ElementSelection = { kind: 'ontology' }
      let focusId: string | null = null
      if (elementId && kind !== 'ontology') {
        target = { kind, id: elementId }
        if (kind === 'class') focusId = elementId
        if (kind === 'object_property') focusId = doc?.object_properties.find((p) => p.id === elementId)?.domain_id ?? null
        if (kind === 'datatype_property') focusId = doc?.datatype_properties.find((p) => p.id === elementId)?.domain_id ?? null
      }
      setSelection(target)
      if (focusId) setFocusRequest({ id: focusId, nonce: Date.now() })
      setTab('designer')
    },
    [editor.doc, setTab],
  )
  const showIssue = useCallback(
    (issue: ValidationIssue) => showElement(issue.element_kind, issue.element_id),
    [showElement],
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
          {(ontologies.data?.length ?? 0) > 1 && (
            <Select value={activeOntology.id} onValueChange={switchOntology} disabled={editor.dirty}>
              <SelectTrigger
                size="sm"
                className="h-7 w-auto max-w-56 text-xs"
                aria-label="Switch ontology"
                title={editor.dirty ? 'Save or discard changes before switching ontology' : 'Switch ontology'}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ontologies.data?.map((o) => (
                  <SelectItem key={o.id} value={o.id}>
                    {o.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Badge variant="secondary">Draft · revision {editor.base?.draft_revision ?? activeOntology.draft_revision}</Badge>
          {editor.dirty && (
            <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-800">
              Unsaved changes
            </Badge>
          )}
          <span className="font-mono text-xs text-muted-foreground">{editor.doc?.metadata.namespace ?? activeOntology.namespace}</span>
          {activeOntology.latest_version && (
            <Badge variant="outline" className="font-mono">
              Published v{activeOntology.latest_version.version}
            </Badge>
          )}
          <div className="ml-auto">
            <ReviewerControl />
          </div>
        </div>
        <TabsList variant="line" className="mt-3 h-10">
          <TabsTrigger value="designer">Ontology Designer</TabsTrigger>
          <TabsTrigger value="discovery">AI Discovery</TabsTrigger>
          <TabsTrigger value="review">
            SME Review
            {(proposalStats.data?.awaiting_review ?? 0) > 0 && (
              <span className="ml-1 rounded-full bg-primary/10 px-1.5 text-[10px] font-semibold text-primary" data-testid="review-count">
                {proposalStats.data?.awaiting_review}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="validation">
            Validation
            {latestValidation.data && !latestValidation.data.is_valid && (
              <span className="ml-1 rounded-full bg-red-100 px-1.5 text-[10px] font-semibold text-red-700">
                {latestValidation.data.error_count}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="semantics">RDF / OWL</TabsTrigger>
          <TabsTrigger value="shapes">SHACL Shapes</TabsTrigger>
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
      <TabsContent value="discovery" className="min-h-0 flex-1 overflow-y-auto">
        <DiscoveryView
          projectId={projectId}
          ontologyId={activeOntology.id}
          draftRevision={editor.base?.draft_revision ?? activeOntology.draft_revision}
          onReviewRun={(runId) => {
            setRunFilter(runId)
            setTab('review')
          }}
        />
      </TabsContent>
      <TabsContent value="review" className="min-h-0 flex-1">
        {body ?? (
          <ReviewView
            projectId={projectId}
            ontologyId={activeOntology.id}
            editor={editor}
            runFilter={runFilter}
            onClearRunFilter={() => setRunFilter(null)}
            onOpenInDesigner={(elementId, kind) => showElement(kind, elementId)}
          />
        )}
      </TabsContent>
      <TabsContent value="semantics" className="min-h-0 flex-1 overflow-y-auto">
        {body ?? <SemanticsView projectId={projectId} ontologyId={activeOntology.id} editor={editor} />}
      </TabsContent>
      <TabsContent value="shapes" className="min-h-0 flex-1 overflow-y-auto">
        {body ?? <ShapesView ontologyId={activeOntology.id} editor={editor} />}
      </TabsContent>
      <TabsContent value="registry" className="min-h-0 flex-1 overflow-y-auto">
        {body ?? <RegistryView projectId={projectId} ontologyId={activeOntology.id} editor={editor} />}
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
