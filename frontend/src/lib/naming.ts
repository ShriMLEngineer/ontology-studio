const WORD_SPLIT = /[^A-Za-z0-9]+/

function words(label: string): string[] {
  return label.trim().split(WORD_SPLIT).filter(Boolean)
}

/** 'purchase order' -> 'PurchaseOrder' (mirrors the backend derivation). */
export function toClassLocalName(label: string): string {
  const name = words(label)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join('')
  return name && !/^\d/.test(name) ? name : `C${name}`
}

/** 'ships to' -> 'shipsTo' (mirrors the backend derivation). */
export function toPropertyLocalName(label: string): string {
  const [first, ...rest] = words(label)
  if (!first) return 'p'
  const name = first.charAt(0).toLowerCase() + first.slice(1) + rest.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join('')
  return /^\d/.test(name) ? `p${name}` : name
}

export const LOCAL_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_-]*$/

export function newElementId(prefix: 'cls' | 'op' | 'dp'): string {
  return `${prefix}_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`
}

export function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
