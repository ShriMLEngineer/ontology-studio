import type { ShapeSeverity } from '@/lib/api/types'

export const SEVERITY_STYLE: Record<ShapeSeverity, string> = {
  Violation: 'border-red-200 bg-red-50 text-red-700',
  Warning: 'border-amber-200 bg-amber-50 text-amber-800',
  Info: 'border-sky-200 bg-sky-50 text-sky-700',
}

export const OUTCOME_STYLE: Record<string, string> = {
  reject: 'border-red-200 bg-red-50 text-red-700',
  quarantine: 'border-amber-200 bg-amber-50 text-amber-800',
  warn: 'border-amber-200 bg-amber-50 text-amber-800',
  info: 'border-slate-200 bg-slate-50 text-slate-600',
}
