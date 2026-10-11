import type { InternalNode, Node } from '@xyflow/react'

interface Point {
  x: number
  y: number
}

interface Rect extends Point {
  width: number
  height: number
}

export interface EdgeGeometry {
  path: string
  labelX: number
  labelY: number
}

export function rectOf(node: InternalNode<Node>): Rect | null {
  const width = node.measured.width
  const height = node.measured.height
  if (!width || !height) return null
  const { x, y } = node.internals.positionAbsolute
  return { x, y, width, height }
}

function center(r: Rect): Point {
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
}

/** Point where the ray from the rectangle's centre towards ``toward`` leaves the rectangle. */
function boundaryPoint(r: Rect, toward: Point, padding = 4): Point {
  const c = center(r)
  const dx = toward.x - c.x
  const dy = toward.y - c.y
  if (dx === 0 && dy === 0) return c
  const hw = r.width / 2 + padding
  const hh = r.height / 2 + padding
  const scale = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh)
  return { x: c.x + dx * scale, y: c.y + dy * scale }
}

/**
 * Edge between two nodes attached at the node boundaries. ``offset`` bends the edge
 * perpendicular to its direction so parallel edges between the same pair stay readable.
 */
export function floatingEdge(source: Rect, target: Rect, offset: number): EdgeGeometry {
  const sc = center(source)
  const tc = center(target)
  const dx = tc.x - sc.x
  const dy = tc.y - sc.y
  const length = Math.hypot(dx, dy) || 1
  const nx = -dy / length
  const ny = dx / length
  const control = { x: (sc.x + tc.x) / 2 + nx * offset * 2, y: (sc.y + tc.y) / 2 + ny * offset * 2 }
  const start = boundaryPoint(source, offset ? control : tc)
  const end = boundaryPoint(target, offset ? control : sc, 8)
  return {
    path: `M ${start.x},${start.y} Q ${control.x},${control.y} ${end.x},${end.y}`,
    labelX: 0.25 * start.x + 0.5 * control.x + 0.25 * end.x,
    labelY: 0.25 * start.y + 0.5 * control.y + 0.25 * end.y,
  }
}

/** Loop drawn from the top edge to the right edge of a node (e.g. Product hasComponent Product). */
export function selfLoop(r: Rect, index: number): EdgeGeometry {
  const grow = index * 22
  const start = { x: r.x + r.width - 48 - index * 12, y: r.y - 2 }
  const end = { x: r.x + r.width + 6, y: r.y + 34 + index * 12 }
  const c1 = { x: start.x - 4, y: r.y - 70 - grow }
  const c2 = { x: r.x + r.width + 70 + grow, y: end.y + 4 }
  return {
    path: `M ${start.x},${start.y} C ${c1.x},${c1.y} ${c2.x},${c2.y} ${end.x},${end.y}`,
    labelX: r.x + r.width + 18 + grow * 0.6,
    labelY: r.y - 38 - grow * 0.6,
  }
}
