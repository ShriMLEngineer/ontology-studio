import { MarkerType, type Edge, type Node } from '@xyflow/react'

import type { ClassDefinition, DatatypePropertyDefinition, Position, Severity } from '@/lib/api/types'
import type { DraftDoc, ElementSelection } from '../draft/model'

export interface ClassNodeData extends Record<string, unknown> {
  cls: ClassDefinition
  prefix: string
  attributes: DatatypePropertyDefinition[]
  isSelected: boolean
  selectedAttributeId: string | null
  severity: Severity | null
  onSelectAttribute: (id: string) => void
}
export type ClassFlowNode = Node<ClassNodeData, 'ontologyClass'>

export interface OntologyEdgeData extends Record<string, unknown> {
  kind: 'relation' | 'subclass'
  label: string
  offset: number
  loopIndex: number
  isSelected: boolean
  severity: Severity | null
  onSelect: () => void
}
export type OntologyFlowEdge = Edge<OntologyEdgeData, 'floating'>

const PARALLEL_SPACING = 46
const RELATION_COLOR = 'oklch(0.55 0.12 264)'
const SELECTED_COLOR = 'oklch(0.488 0.217 264)'
const SUBCLASS_COLOR = 'oklch(0.6 0 0)'

export function fallbackPosition(index: number): Position {
  return { x: (index % 4) * 300, y: 1100 + Math.floor(index / 4) * 260 }
}

interface Rect {
  x: number
  y: number
  width: number
  height: number
}

/** Nearest position to ``desired`` (searching outward in rings) where a new class node fits without overlap. */
export function findFreePosition(desired: Position, occupied: Rect[], size = { width: 232, height: 120 }): Position {
  const gap = 32
  const fits = (p: Position) =>
    !occupied.some(
      (r) =>
        p.x < r.x + r.width + gap && p.x + size.width + gap > r.x && p.y < r.y + r.height + gap && p.y + size.height + gap > r.y,
    )
  if (fits(desired)) return desired
  const stepX = size.width / 2
  const stepY = size.height / 2
  for (let ring = 1; ring <= 16; ring += 1) {
    const candidates: Position[] = []
    for (let dx = -ring; dx <= ring; dx += 1) {
      for (let dy = -ring; dy <= ring; dy += 1) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) === ring) candidates.push({ x: desired.x + dx * stepX, y: desired.y + dy * stepY })
      }
    }
    candidates.sort((a, b) => Math.hypot(a.x - desired.x, a.y - desired.y) - Math.hypot(b.x - desired.x, b.y - desired.y))
    const free = candidates.find(fits)
    if (free) return free
  }
  return desired
}

export function buildNodes(
  doc: DraftDoc,
  previous: ClassFlowNode[],
  selection: ElementSelection | null,
  severityById: Map<string, Severity>,
  onSelectAttribute: (id: string) => void,
): ClassFlowNode[] {
  const prior = new Map(previous.map((n) => [n.id, n]))
  const attributesByClass = new Map<string, DatatypePropertyDefinition[]>()
  for (const attr of doc.datatype_properties) {
    if (!attr.domain_id) continue
    attributesByClass.set(attr.domain_id, [...(attributesByClass.get(attr.domain_id) ?? []), attr])
  }
  const selectedAttribute =
    selection?.kind === 'datatype_property' ? doc.datatype_properties.find((p) => p.id === selection.id) : undefined
  const selectedClassId = selection?.kind === 'class' ? selection.id : (selectedAttribute?.domain_id ?? null)

  return doc.classes.map((cls, index) => {
    const existing = prior.get(cls.id)
    const attributes = attributesByClass.get(cls.id) ?? []
    const attributeSeverity = attributes.map((a) => severityById.get(a.id)).find(Boolean) ?? null
    return {
      ...existing,
      id: cls.id,
      type: 'ontologyClass',
      position: doc.layout.positions[cls.id] ?? existing?.position ?? fallbackPosition(index),
      selected: cls.id === selectedClassId,
      data: {
        cls,
        prefix: doc.metadata.prefix,
        attributes,
        isSelected: cls.id === selectedClassId,
        selectedAttributeId: selectedAttribute?.id ?? null,
        severity: severityById.get(cls.id) ?? attributeSeverity,
        onSelectAttribute,
      },
    }
  })
}

interface EdgeSpec {
  id: string
  source: string
  target: string
  kind: 'relation' | 'subclass'
  label: string
  select: ElementSelection
}

export function buildEdges(
  doc: DraftDoc,
  selection: ElementSelection | null,
  severityById: Map<string, Severity>,
  onSelect: (selection: ElementSelection) => void,
): OntologyFlowEdge[] {
  const classIds = new Set(doc.classes.map((c) => c.id))
  const specs: EdgeSpec[] = []

  for (const cls of doc.classes) {
    for (const parentId of cls.parent_ids) {
      if (classIds.has(parentId) && parentId !== cls.id) {
        specs.push({
          id: `subclass:${cls.id}->${parentId}`,
          source: cls.id,
          target: parentId,
          kind: 'subclass',
          label: 'subclass of',
          select: { kind: 'class', id: cls.id },
        })
      }
    }
  }
  for (const prop of doc.object_properties) {
    // Dangling relationships cannot be drawn; they remain visible in the outline and validation.
    if (prop.domain_id && prop.range_id && classIds.has(prop.domain_id) && classIds.has(prop.range_id)) {
      specs.push({
        id: prop.id,
        source: prop.domain_id,
        target: prop.range_id,
        kind: 'relation',
        // ⇄ marks an owl:inverseOf declaration (details in the relationship inspector).
        label: prop.semantics?.inverse_id ? `${prop.label} ⇄` : prop.label,
        select: { kind: 'object_property', id: prop.id },
      })
    }
  }

  const groups = new Map<string, EdgeSpec[]>()
  for (const spec of specs) {
    const key = [spec.source, spec.target].sort().join('|')
    groups.set(key, [...(groups.get(key) ?? []), spec])
  }

  const edges: OntologyFlowEdge[] = []
  for (const group of groups.values()) {
    group.forEach((spec, index) => {
      const isSelected =
        spec.kind === 'relation' && selection?.kind === 'object_property' && selection.id === spec.id
      let offset = 0
      if (spec.source !== spec.target && group.length > 1) {
        offset = (index - (group.length - 1) / 2) * PARALLEL_SPACING
        if (spec.source > spec.target) offset = -offset
      }
      const relation = spec.kind === 'relation'
      edges.push({
        id: spec.id,
        source: spec.source,
        target: spec.target,
        type: 'floating',
        className: `${relation ? 'edge-relation' : 'edge-subclass'}${isSelected ? ' is-selected' : ''}`,
        zIndex: isSelected ? 10 : relation ? 1 : 0,
        markerEnd: relation
          ? { type: MarkerType.ArrowClosed, width: 16, height: 16, color: isSelected ? SELECTED_COLOR : RELATION_COLOR }
          : { type: MarkerType.Arrow, width: 22, height: 22, color: SUBCLASS_COLOR },
        data: {
          kind: spec.kind,
          label: spec.label,
          offset,
          loopIndex: index,
          isSelected,
          severity: relation ? (severityById.get(spec.id) ?? null) : null,
          onSelect: () => onSelect(spec.select),
        },
      })
    })
  }
  return edges
}
