import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useNodesInitialized,
  useReactFlow,
  type Connection,
  type NodeChange,
} from '@xyflow/react'
import { Box, Loader2, PanelLeft, Plus, RefreshCw, RotateCcw, Save, Settings2, Spline } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from 'cn'

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
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, errorMessage } from '@/lib/api/client'
import { semanticsApi } from '@/lib/api/endpoints'
import type { Severity, ValidationReport } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import type { DraftDoc, ElementSelection } from '../draft/model'
import type { DraftEditor } from '../draft/useDraftEditor'
import { AddClassDialog } from './AddClassDialog'
import { AddRelationshipDialog, type RelationshipPrefill } from './AddRelationshipDialog'
import { ClassInspector } from './ClassInspector'
import { ClassNode } from './ClassNode'
import { ElementOutline } from './ElementOutline'
import { FloatingEdge } from './FloatingEdge'
import { buildEdges, buildNodes, findFreePosition, type ClassFlowNode, type OntologyFlowEdge } from './flow'
import { OntologyInspector } from './OntologyInspector'
import { DesignerSemanticsContext, type DesignerSemantics } from './semanticContext'
import { describeChanges } from './presentation'
import { AttributeInspector, RelationshipInspector } from './RelationshipInspector'

const nodeTypes = { ontologyClass: ClassNode }
const edgeTypes = { floating: FloatingEdge }
const NODE_HALF_WIDTH = 116

export interface FocusRequest {
  id: string
  nonce: number
}

interface DesignerProps {
  editor: DraftEditor
  doc: DraftDoc
  selection: ElementSelection | null
  onSelect: (selection: ElementSelection | null) => void
  focusRequest: FocusRequest | null
  onFocusHandled: () => void
  report: ValidationReport | null | undefined
}

export function DesignerView(props: DesignerProps) {
  const semantics = useDesignerSemanticsValue(props.editor)
  return (
    <DesignerSemanticsContext.Provider value={semantics}>
      <ReactFlowProvider>
        <DesignerWorkspace {...props} />
      </ReactFlowProvider>
    </DesignerSemanticsContext.Provider>
  )
}

/** Locked IRIs come with the saved draft; preserved axioms are read once per ontology. */
function useDesignerSemanticsValue(editor: DraftEditor): DesignerSemantics {
  const ontologyId = editor.base?.ontology.id
  const axioms = useQuery({
    queryKey: queryKeys.axioms(ontologyId ?? ''),
    queryFn: () => semanticsApi.axioms(ontologyId!),
    enabled: Boolean(ontologyId),
  })
  const locked = editor.base?.locked_iri_ids
  const latestVersion = editor.base?.ontology.latest_version?.version ?? null
  return useMemo(() => {
    const axiomCounts = new Map<string, number>()
    for (const axiom of axioms.data ?? []) {
      for (const id of axiom.anchor_ids) axiomCounts.set(id, (axiomCounts.get(id) ?? 0) + 1)
    }
    return { lockedIds: new Set(locked ?? []), axiomCounts, latestVersion }
  }, [axioms.data, locked, latestVersion])
}

function DesignerWorkspace({ editor, doc, selection, onSelect, focusRequest, onFocusHandled, report }: DesignerProps) {
  const reactFlow = useReactFlow()
  const canvasRef = useRef<HTMLDivElement>(null)
  const [showOutline, setShowOutline] = useState(true)
  const [addClassOpen, setAddClassOpen] = useState(false)
  const [relationshipDialog, setRelationshipDialog] = useState<{ open: boolean; key: number; prefill: RelationshipPrefill }>({
    open: false,
    key: 0,
    prefill: {},
  })
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  const issuesStale = Boolean(report && !report.is_current)
  const severityById = useMemo(() => {
    const map = new Map<string, Severity>()
    if (!report?.is_current) return map
    const rank: Record<Severity, number> = { error: 0, warning: 1, info: 2 }
    for (const issue of report.issues) {
      if (!issue.element_id) continue
      const current = map.get(issue.element_id)
      if (!current || rank[issue.severity] < rank[current]) map.set(issue.element_id, issue.severity)
    }
    return map
  }, [report])
  const issuesFor = useCallback((id: string) => report?.issues.filter((i) => i.element_id === id) ?? [], [report])

  const selectAttribute = useCallback((id: string) => onSelect({ kind: 'datatype_property', id }), [onSelect])
  const [nodes, setNodes] = useState<ClassFlowNode[]>(() => buildNodes(doc, [], selection, severityById, selectAttribute))
  // Re-derive nodes when the working copy changes while keeping React Flow's measured sizes
  // (adjusting state during render avoids an extra commit with stale nodes).
  const [syncedInputs, setSyncedInputs] = useState({ doc, selection, severityById })
  if (syncedInputs.doc !== doc || syncedInputs.selection !== selection || syncedInputs.severityById !== severityById) {
    setSyncedInputs({ doc, selection, severityById })
    setNodes((previous) => buildNodes(doc, previous, selection, severityById, selectAttribute))
  }
  const edges = useMemo(() => buildEdges(doc, selection, severityById, onSelect), [doc, selection, severityById, onSelect])

  const onNodesChange = useCallback((changes: NodeChange<ClassFlowNode>[]) => {
    // Selection and deletion are owned by the editor (deletion requires confirmation).
    setNodes((current) => applyNodeChanges(changes.filter((c) => c.type !== 'remove' && c.type !== 'select'), current))
  }, [])

  const { dispatch } = editor
  const onNodeDragStop = useCallback(
    (_event: unknown, _node: ClassFlowNode, dragged: ClassFlowNode[]) => {
      dispatch({ type: 'moveClasses', positions: Object.fromEntries(dragged.map((n) => [n.id, n.position])) })
    },
    [dispatch],
  )

  const onConnect = useCallback((connection: Connection) => {
    setRelationshipDialog((d) => ({
      open: true,
      key: d.key + 1,
      prefill: { domainId: connection.source, rangeId: connection.target },
    }))
  }, [])

  const openRelationshipDialog = useCallback((prefill: RelationshipPrefill = {}) => {
    setRelationshipDialog((d) => ({ open: true, key: d.key + 1, prefill }))
  }, [])

  const nodesInitialized = useNodesInitialized()
  // Skip the automatic initial fit when opened to show a specific element (e.g. from validation).
  const [fitOnInit] = useState(() => focusRequest === null)

  const centerOn = (classId: string | null | undefined) => {
    if (!classId) return
    const position = doc.layout.positions[classId] ?? reactFlow.getNode(classId)?.position
    if (position) {
      void reactFlow.setCenter(position.x + NODE_HALF_WIDTH, position.y + 80, {
        zoom: Math.max(reactFlow.getZoom(), 0.9),
        duration: 400,
      })
    }
  }

  const selectFromOutline = (target: ElementSelection) => {
    onSelect(target)
    if (target.kind === 'class') centerOn(target.id)
    else if (target.kind === 'object_property') centerOn(doc.object_properties.find((p) => p.id === target.id)?.domain_id)
    else if (target.kind === 'datatype_property') centerOn(doc.datatype_properties.find((p) => p.id === target.id)?.domain_id)
  }

  useEffect(() => {
    if (!focusRequest || !nodesInitialized) return
    centerOn(focusRequest.id)
    onFocusHandled()
    // Only respond to explicit focus requests once nodes are measured.
  }, [focusRequest, nodesInitialized]) // eslint-disable-line react-hooks/exhaustive-deps

  const placementForNewClass = () => {
    const bounds = canvasRef.current?.getBoundingClientRect()
    if (!bounds) return { x: 0, y: 0 }
    const center = reactFlow.screenToFlowPosition({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 })
    const occupied = reactFlow.getNodes().map((n) => ({
      x: n.position.x,
      y: n.position.y,
      width: n.measured?.width ?? NODE_HALF_WIDTH * 2,
      height: n.measured?.height ?? 120,
    }))
    return findFreePosition({ x: center.x - NODE_HALF_WIDTH, y: center.y - 60 }, occupied)
  }

  const blankElements = [...doc.classes, ...doc.object_properties, ...doc.datatype_properties].filter(
    (e) => !e.label.trim() || !e.local_name.trim(),
  ).length
  const metadataIncomplete = !doc.metadata.name.trim() || !doc.metadata.namespace.trim() || !doc.metadata.prefix.trim()
  const saveBlockedReason = blankElements
    ? `${blankElements} element(s) have an empty label or local name.`
    : metadataIncomplete
      ? 'Ontology name, namespace and prefix are required.'
      : null

  const { save, dirty, saving } = editor
  const handleSave = useCallback(async () => {
    if (!dirty || saving) return
    if (saveBlockedReason) {
      toast.error('Cannot save draft', { description: saveBlockedReason })
      return
    }
    try {
      const result = await save()
      toast.success(
        result.revision_incremented ? `Draft saved as revision ${result.draft.draft_revision}` : 'Diagram layout saved',
        { description: describeChanges(result.changes) },
      )
    } catch {
      /* surfaced through editor.saveError */
    }
  }, [dirty, saving, save, saveBlockedReason])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void handleSave()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [handleSave])

  const conflict = editor.saveError instanceof ApiError && editor.saveError.code === 'DRAFT_REVISION_CONFLICT'

  const selectedClass = selection?.kind === 'class' ? doc.classes.find((c) => c.id === selection.id) : undefined
  const selectedRelationship =
    selection?.kind === 'object_property' ? doc.object_properties.find((p) => p.id === selection.id) : undefined
  const selectedAttribute =
    selection?.kind === 'datatype_property' ? doc.datatype_properties.find((p) => p.id === selection.id) : undefined
  const attributeClass = selectedAttribute ? doc.classes.find((c) => c.id === selectedAttribute.domain_id) : undefined

  useEffect(() => {
    const missing =
      (selection?.kind === 'class' && !selectedClass) ||
      (selection?.kind === 'object_property' && !selectedRelationship) ||
      (selection?.kind === 'datatype_property' && !selectedAttribute)
    if (missing) onSelect(null)
  }, [selection, selectedClass, selectedRelationship, selectedAttribute, onSelect])

  let inspector = null
  if (selectedClass) {
    inspector = (
      <ClassInspector
        key={selectedClass.id}
        doc={doc}
        cls={selectedClass}
        dispatch={dispatch}
        onSelect={onSelect}
        onClose={() => onSelect(null)}
        onAddRelationship={(domainId) => openRelationshipDialog({ domainId })}
        issuesFor={issuesFor}
        issuesStale={issuesStale}
      />
    )
  } else if (selectedRelationship) {
    inspector = (
      <RelationshipInspector
        key={selectedRelationship.id}
        doc={doc}
        prop={selectedRelationship}
        dispatch={dispatch}
        onSelect={onSelect}
        onClose={() => onSelect(null)}
        issues={issuesFor(selectedRelationship.id)}
        issuesStale={issuesStale}
      />
    )
  } else if (selectedAttribute && attributeClass) {
    inspector = (
      <ClassInspector
        key={`${attributeClass.id}:${selectedAttribute.id}`}
        doc={doc}
        cls={attributeClass}
        dispatch={dispatch}
        onSelect={onSelect}
        onClose={() => onSelect(null)}
        onAddRelationship={(domainId) => openRelationshipDialog({ domainId })}
        issuesFor={issuesFor}
        issuesStale={issuesStale}
        initialAttributeId={selectedAttribute.id}
      />
    )
  } else if (selectedAttribute) {
    inspector = (
      <AttributeInspector
        key={selectedAttribute.id}
        doc={doc}
        attr={selectedAttribute}
        dispatch={dispatch}
        onClose={() => onSelect(null)}
        issues={issuesFor(selectedAttribute.id)}
      />
    )
  } else if (selection?.kind === 'ontology') {
    inspector = (
      <OntologyInspector
        doc={doc}
        dispatch={dispatch}
        onClose={() => onSelect(null)}
        issues={report?.issues.filter((i) => i.element_kind === 'ontology') ?? []}
        issuesStale={issuesStale}
      />
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b bg-background px-4">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setShowOutline((v) => !v)}
              aria-label="Toggle outline"
              aria-pressed={showOutline}
            >
              <PanelLeft />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Toggle outline</TooltipContent>
        </Tooltip>
        <Separator orientation="vertical" className="mx-1 h-5!" />
        <Button size="sm" onClick={() => setAddClassOpen(true)}>
          <Plus /> Class
        </Button>
        <Button size="sm" variant="outline" onClick={() => openRelationshipDialog()} disabled={doc.classes.length === 0}>
          <Spline /> Relationship
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onSelect({ kind: 'ontology' })}>
          <Settings2 /> Ontology settings
        </Button>

        <div className="ml-auto flex items-center gap-2">
          {dirty ? (
            <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-800" role="status">
              <span className="size-1.5 rounded-full bg-amber-500" /> Unsaved changes
            </Badge>
          ) : (
            <span className="text-xs text-muted-foreground" role="status">
              All changes saved · revision {editor.base?.draft_revision}
            </span>
          )}
          {dirty && (
            <Button size="sm" variant="ghost" onClick={() => setConfirmDiscard(true)} disabled={saving}>
              <RotateCcw /> Discard
            </Button>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="sm"
                variant="outline"
                aria-label="Reload draft from server"
                onClick={() => (dirty ? setConfirmDiscard(true) : void editor.reload())}
                disabled={editor.reloading || saving}
              >
                <RefreshCw className={cn(editor.reloading && 'animate-spin')} /> Reload
              </Button>
            </TooltipTrigger>
            <TooltipContent>Reload the latest saved draft from the server</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <Button size="sm" onClick={() => void handleSave()} disabled={!dirty || saving || Boolean(saveBlockedReason)}>
                  {saving ? <Loader2 className="animate-spin" /> : <Save />} Save draft
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>{saveBlockedReason ?? 'Save draft (Ctrl+S)'}</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {editor.saveError && (
        <div className="border-b bg-background px-4 py-3">
          <Alert variant="destructive">
            <AlertTitle>{conflict ? 'This draft was changed elsewhere' : 'The draft could not be saved'}</AlertTitle>
            <AlertDescription>
              {conflict
                ? `Another change created revision ${String((editor.saveError as ApiError).details.current_revision)}. Reload the latest draft to continue; your unsaved changes will be discarded.`
                : errorMessage(editor.saveError)}
            </AlertDescription>
            {conflict && (
              <AlertAction>
                <Button size="sm" variant="outline" onClick={() => void editor.reload()}>
                  Reload latest
                </Button>
              </AlertAction>
            )}
          </Alert>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {showOutline && <ElementOutline doc={doc} selection={selection} onSelect={selectFromOutline} severityById={severityById} />}
        <div ref={canvasRef} className="ontology-canvas relative min-w-0 flex-1 bg-muted/30" data-testid="ontology-canvas">
          <ReactFlow<ClassFlowNode, OntologyFlowEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onNodeDragStop={onNodeDragStop}
            onNodeClick={(_, node) => onSelect({ kind: 'class', id: node.id })}
            onEdgeClick={(_, edge) => edge.data?.onSelect()}
            onPaneClick={() => onSelect(null)}
            onConnect={onConnect}
            deleteKeyCode={null}
            connectionRadius={36}
            minZoom={0.2}
            maxZoom={2}
            fitView={fitOnInit}
            fitViewOptions={{ padding: 0.15 }}
          >
            <Background gap={24} size={1} />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap pannable zoomable position="bottom-right" nodeColor="oklch(0.85 0.05 264)" className="rounded-md border" />
            <Panel position="top-left" className="rounded-lg border bg-background/90 px-3 py-2 text-[11px] text-muted-foreground shadow-xs">
              <div className="flex items-center gap-2">
                <svg width="28" height="8" aria-hidden>
                  <line x1="0" y1="4" x2="22" y2="4" stroke="oklch(0.55 0.12 264)" strokeWidth="1.6" />
                  <path d="M22 0 L28 4 L22 8 z" fill="oklch(0.55 0.12 264)" />
                </svg>
                Relationship (domain → range)
              </div>
              <div className="mt-1 flex items-center gap-2">
                <svg width="28" height="8" aria-hidden>
                  <line x1="0" y1="4" x2="22" y2="4" stroke="oklch(0.6 0 0)" strokeWidth="1.4" strokeDasharray="4 3" />
                  <path d="M21 0 L28 4 L21 8" fill="none" stroke="oklch(0.6 0 0)" />
                </svg>
                Subclass of
              </div>
              <div className="mt-1">Drag a class's right handle onto another class to relate them.</div>
            </Panel>
          </ReactFlow>
          {doc.classes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="pointer-events-auto rounded-xl border bg-background p-6 text-center shadow-sm">
                <Box className="mx-auto size-6 text-muted-foreground" />
                <p className="mt-2 font-medium">This ontology has no classes yet</p>
                <p className="mt-1 text-sm text-muted-foreground">Start by adding the core business concepts.</p>
                <Button className="mt-4" size="sm" onClick={() => setAddClassOpen(true)}>
                  <Plus /> Add first class
                </Button>
              </div>
            </div>
          )}
        </div>
        {inspector}
      </div>

      <AddClassDialog
        open={addClassOpen}
        onOpenChange={setAddClassOpen}
        doc={doc}
        onCreate={(value) => {
          dispatch({ type: 'addClass', value, position: placementForNewClass() })
          onSelect({ kind: 'class', id: value.id })
        }}
      />
      <AddRelationshipDialog
        key={relationshipDialog.key}
        open={relationshipDialog.open}
        onOpenChange={(open) => setRelationshipDialog((d) => ({ ...d, open }))}
        doc={doc}
        prefill={relationshipDialog.prefill}
        onCreate={(value) => {
          dispatch({ type: 'addObjectProperty', value })
          onSelect({ kind: 'object_property', id: value.id })
        }}
      />
      <AlertDialog open={confirmDiscard} onOpenChange={setConfirmDiscard}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Your working copy will be replaced with the latest saved draft. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                onSelect(null)
                void editor.reload()
              }}
            >
              Discard changes
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
