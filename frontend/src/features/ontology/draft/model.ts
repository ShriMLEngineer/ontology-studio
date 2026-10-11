import type {
  ClassDefinition,
  ClassSemantics,
  DatatypePropertyDefinition,
  DatatypePropertySemantics,
  DiagramLayout,
  ObjectPropertyDefinition,
  ObjectPropertySemantics,
  OntologyDraft,
  OntologyMetadata,
  Position,
} from '@/lib/api/types'

/** The editable working copy of an ontology draft. */
export interface DraftDoc {
  metadata: OntologyMetadata
  classes: ClassDefinition[]
  object_properties: ObjectPropertyDefinition[]
  datatype_properties: DatatypePropertyDefinition[]
  layout: DiagramLayout
}

export type ElementSelection =
  | { kind: 'class'; id: string }
  | { kind: 'object_property'; id: string }
  | { kind: 'datatype_property'; id: string }
  | { kind: 'ontology' }

type Patch<T> = Partial<Omit<T, 'id'>>

export type DraftAction =
  | { type: 'updateMetadata'; patch: Partial<OntologyMetadata> }
  | { type: 'addClass'; value: ClassDefinition; position: Position }
  | { type: 'updateClass'; id: string; patch: Patch<ClassDefinition> }
  | { type: 'deleteClass'; id: string }
  | { type: 'moveClasses'; positions: Record<string, Position> }
  | { type: 'addObjectProperty'; value: ObjectPropertyDefinition }
  | { type: 'updateObjectProperty'; id: string; patch: Patch<ObjectPropertyDefinition> }
  | { type: 'deleteObjectProperty'; id: string }
  | { type: 'addDatatypeProperty'; value: DatatypePropertyDefinition }
  | { type: 'updateDatatypeProperty'; id: string; patch: Patch<DatatypePropertyDefinition> }
  | { type: 'deleteDatatypeProperty'; id: string }

export function toDoc(draft: OntologyDraft): DraftDoc {
  const { name, namespace, prefix, description, ontology_iri, prefixes, imports, require_domain_range } = draft.ontology
  return {
    metadata: { name, namespace, prefix, description, ontology_iri, prefixes, imports, require_domain_range },
    classes: draft.classes,
    object_properties: draft.object_properties,
    datatype_properties: draft.datatype_properties,
    layout: draft.layout,
  }
}

export function sameDoc(a: DraftDoc, b: DraftDoc): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

function patchById<T extends { id: string }>(items: T[], id: string, patch: NoInfer<Partial<T>>): T[] {
  return items.map((item) => (item.id === id ? { ...item, ...patch } : item))
}

function roundPosition({ x, y }: Position): Position {
  return { x: Math.round(x), y: Math.round(y) }
}

export function applyDraftAction(doc: DraftDoc, action: DraftAction): DraftDoc {
  switch (action.type) {
    case 'updateMetadata':
      return { ...doc, metadata: { ...doc.metadata, ...action.patch } }
    case 'addClass':
      return {
        ...doc,
        classes: [...doc.classes, action.value],
        layout: { positions: { ...doc.layout.positions, [action.value.id]: roundPosition(action.position) } },
      }
    case 'updateClass':
      return { ...doc, classes: patchById(doc.classes, action.id, action.patch) }
    case 'deleteClass': {
      // Same cascade semantics as the backend: remove dependent properties, detach subclasses.
      const { [action.id]: _removed, ...positions } = doc.layout.positions
      void _removed
      const next: DraftDoc = {
        ...doc,
        classes: doc.classes
          .filter((c) => c.id !== action.id)
          .map((c) =>
            c.parent_ids.includes(action.id) ? { ...c, parent_ids: c.parent_ids.filter((p) => p !== action.id) } : c,
          ),
        object_properties: doc.object_properties.filter((p) => p.domain_id !== action.id && p.range_id !== action.id),
        datatype_properties: doc.datatype_properties.filter((p) => p.domain_id !== action.id),
        layout: { positions },
      }
      const removed = new Set([
        action.id,
        ...doc.object_properties.filter((p) => p.domain_id === action.id || p.range_id === action.id).map((p) => p.id),
        ...doc.datatype_properties.filter((p) => p.domain_id === action.id).map((p) => p.id),
      ])
      return stripSemanticReferences(next, removed)
    }
    case 'moveClasses': {
      const positions = { ...doc.layout.positions }
      for (const [id, pos] of Object.entries(action.positions)) positions[id] = roundPosition(pos)
      return { ...doc, layout: { positions } }
    }
    case 'addObjectProperty':
      return { ...doc, object_properties: [...doc.object_properties, action.value] }
    case 'updateObjectProperty':
      return { ...doc, object_properties: patchById(doc.object_properties, action.id, action.patch) }
    case 'deleteObjectProperty':
      return stripSemanticReferences(
        { ...doc, object_properties: doc.object_properties.filter((p) => p.id !== action.id) },
        new Set([action.id]),
      )
    case 'addDatatypeProperty':
      return { ...doc, datatype_properties: [...doc.datatype_properties, action.value] }
    case 'updateDatatypeProperty':
      return { ...doc, datatype_properties: patchById(doc.datatype_properties, action.id, action.patch) }
    case 'deleteDatatypeProperty':
      return stripSemanticReferences(
        { ...doc, datatype_properties: doc.datatype_properties.filter((p) => p.id !== action.id) },
        new Set([action.id]),
      )
  }
}

type AnySemantics = ClassSemantics & ObjectPropertySemantics & DatatypePropertySemantics

function stripSemantics<T extends { semantics?: object }>(element: T, removed: Set<string>): T {
  const semantics = element.semantics as AnySemantics | undefined
  if (!semantics) return element
  const next: AnySemantics = { ...semantics }
  for (const key of ['equivalent_ids', 'disjoint_ids', 'parent_ids'] as const) {
    if (next[key]) next[key] = next[key]!.filter((id) => !removed.has(id))
  }
  if (next.inverse_id && removed.has(next.inverse_id)) next.inverse_id = null
  if (next.restrictions) {
    next.restrictions = next.restrictions.filter(
      (r) => !removed.has(r.property_id) && !(r.class_id && removed.has(r.class_id)),
    )
  }
  return JSON.stringify(next) === JSON.stringify(semantics) ? element : { ...element, semantics: next }
}

/** Mirror of the backend cascade: drop OWL semantics that refer to deleted elements. */
export function stripSemanticReferences(doc: DraftDoc, removed: Set<string>): DraftDoc {
  return {
    ...doc,
    classes: doc.classes.map((c) => stripSemantics(c, removed)),
    object_properties: doc.object_properties.map((p) => stripSemantics(p, removed)),
    datatype_properties: doc.datatype_properties.map((p) => stripSemantics(p, removed)),
  }
}

export function classDependents(doc: DraftDoc, classId: string) {
  return {
    objectProperties: doc.object_properties.filter((p) => p.domain_id === classId || p.range_id === classId),
    datatypeProperties: doc.datatype_properties.filter((p) => p.domain_id === classId),
    children: doc.classes.filter((c) => c.parent_ids.includes(classId)),
  }
}

/** Ids of all transitive subclasses of ``classId`` (used to prevent hierarchy cycles). */
export function descendantIds(doc: DraftDoc, classId: string): Set<string> {
  const result = new Set<string>()
  const stack = [classId]
  while (stack.length) {
    const current = stack.pop()!
    for (const c of doc.classes) {
      if (c.parent_ids.includes(current) && !result.has(c.id)) {
        result.add(c.id)
        stack.push(c.id)
      }
    }
  }
  return result
}

export function findLocalNameOwner(doc: DraftDoc, localName: string, excludeId?: string) {
  const all = [...doc.classes, ...doc.object_properties, ...doc.datatype_properties]
  return all.find((e) => e.local_name === localName && e.id !== excludeId)
}

export function classLabel(doc: DraftDoc, id: string | null | undefined): string {
  if (!id) return '—'
  return doc.classes.find((c) => c.id === id)?.label ?? `Unknown (${id})`
}
