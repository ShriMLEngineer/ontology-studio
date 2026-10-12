import { createContext, useContext } from 'react'

/** Read-only semantic facts about the saved draft, shared by the canvas and the inspectors. */
export interface DesignerSemantics {
  /** Elements of the latest published version: their IRIs no longer follow renames. */
  lockedIds: ReadonlySet<string>
  /** Number of preserved (imported) axioms that reference each element. */
  axiomCounts: ReadonlyMap<string, number>
  latestVersion: string | null
}

export const DesignerSemanticsContext = createContext<DesignerSemantics>({
  lockedIds: new Set(),
  axiomCounts: new Map(),
  latestVersion: null,
})

export const useDesignerSemantics = () => useContext(DesignerSemanticsContext)
