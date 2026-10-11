import { useEffect, useRef } from 'react'
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'

import type { GraphEdge, GraphNode } from '@/lib/api/types'

const STYLE: cytoscape.StylesheetJson = [
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)',
      label: 'data(name)',
      'font-size': 10,
      color: '#1f2937',
      'text-valign': 'bottom',
      'text-margin-y': 4,
      'text-wrap': 'ellipsis',
      'text-max-width': '140px',
      width: 26,
      height: 26,
      'border-width': 2,
      'border-color': '#ffffff',
    },
  },
  {
    selector: 'edge',
    style: {
      width: 1.6,
      'line-color': '#94a3b8',
      'target-arrow-color': '#94a3b8',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 1.1,
      'curve-style': 'bezier',
      label: 'data(label)',
      'font-size': 9,
      color: '#475569',
      'text-rotation': 'autorotate',
      'text-background-color': '#ffffff',
      'text-background-opacity': 0.85,
      'text-background-padding': '2px',
    },
  },
  { selector: 'edge[factCount > 1]', style: { width: 2.8 } },
  {
    selector: 'node:selected',
    style: { 'border-color': '#0f172a', 'border-width': 3, width: 32, height: 32 },
  },
  {
    selector: 'edge:selected',
    style: { 'line-color': '#0f172a', 'target-arrow-color': '#0f172a', width: 3.2, color: '#0f172a' },
  },
]

declare global {
  interface Window {
    __kgCy?: Core
  }
}

/** Fit the graph, but never magnify a small graph beyond a readable zoom level. */
function fitCapped(cy: Core) {
  cy.fit(undefined, 48)
  if (cy.zoom() > 1.1) {
    cy.zoom(1.1)
    cy.center()
  }
}

function zoomBy(cy: Core | null, factor: number) {
  if (!cy) return
  cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } })
}

export function GraphCanvas({
  nodes,
  edges,
  colors,
  selectedId,
  layoutNonce,
  onSelect,
}: {
  nodes: GraphNode[]
  edges: GraphEdge[]
  colors: Record<string, string>
  selectedId: string | null
  layoutNonce: number
  onSelect: (id: string | null) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const onSelectRef = useRef(onSelect)
  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    if (!containerRef.current) return
    const cy = cytoscape({
      container: containerRef.current,
      style: STYLE,
      wheelSensitivity: 0.25,
      minZoom: 0.15,
      maxZoom: 3,
      selectionType: 'single',
    })
    cy.on('tap', 'node, edge', (event) => onSelectRef.current(event.target.id()))
    cy.on('tap', (event) => {
      if (event.target === cy) onSelectRef.current(null)
    })
    cyRef.current = cy
    // Exposed in development so end-to-end tests can drive the real canvas.
    if (import.meta.env.DEV) window.__kgCy = cy
    const resize = new ResizeObserver(() => cy.resize())
    resize.observe(containerRef.current)
    return () => {
      resize.disconnect()
      cy.destroy()
      cyRef.current = null
      if (import.meta.env.DEV && window.__kgCy === cy) delete window.__kgCy
    }
  }, [])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    const elements: ElementDefinition[] = [
      ...nodes.map((node) => ({
        group: 'nodes' as const,
        data: { id: node.id, name: node.name, classId: node.class_id, color: colors[node.class_id] ?? '#64748b' },
      })),
      ...edges.map((edge) => ({
        group: 'edges' as const,
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.predicate_label,
          factCount: edge.fact_count,
        },
      })),
    ]
    cy.batch(() => {
      cy.elements().remove()
      cy.add(elements)
    })
    cy.layout({
      name: 'cose',
      animate: false,
      randomize: true,
      fit: false,
      nodeDimensionsIncludeLabels: true,
      nodeRepulsion: () => 400_000,
      nodeOverlap: 20,
      idealEdgeLength: () => 140,
      edgeElasticity: () => 100,
      componentSpacing: 120,
      gravity: 60,
      numIter: 1500,
    }).run()
    fitCapped(cy)
  }, [nodes, edges, colors, layoutNonce])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements(':selected').unselect()
    if (!selectedId) return
    const element = cy.getElementById(selectedId)
    if (element.nonempty()) {
      element.select()
      cy.animate({ center: { eles: element }, duration: 200 })
    }
  }, [selectedId, nodes, edges])

  return (
    <div className="relative h-full w-full">
      {/* Cytoscape forces position: relative on its container, so it fills an absolutely positioned wrapper. */}
      <div className="absolute inset-0">
        <div ref={containerRef} className="h-full w-full" data-testid="graph-canvas" aria-label="Knowledge graph canvas" role="img" />
      </div>
      <div className="absolute right-3 bottom-3 flex gap-1">
        <button
          type="button"
          className="rounded-md border bg-background px-2 py-1 text-xs shadow-sm hover:bg-muted"
          onClick={() => cyRef.current && fitCapped(cyRef.current)}
        >
          Fit
        </button>
        <button
          type="button"
          className="rounded-md border bg-background px-2 py-1 text-xs shadow-sm hover:bg-muted"
          onClick={() => zoomBy(cyRef.current, 1.25)}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className="rounded-md border bg-background px-2 py-1 text-xs shadow-sm hover:bg-muted"
          onClick={() => zoomBy(cyRef.current, 0.8)}
          aria-label="Zoom out"
        >
          −
        </button>
      </div>
    </div>
  )
}
