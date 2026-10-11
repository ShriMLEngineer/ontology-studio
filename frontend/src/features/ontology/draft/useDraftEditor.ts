import { useCallback, useEffect, useMemo, useReducer } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ontologiesApi } from '@/lib/api/endpoints'
import type { DraftSaveResponse, OntologyDraft } from '@/lib/api/types'
import { queryKeys } from '@/lib/query'
import { applyDraftAction, sameDoc, toDoc, type DraftAction, type DraftDoc } from './model'

interface EditorState {
  ontologyId: string
  base: OntologyDraft
  baseDoc: DraftDoc
  doc: DraftDoc
}

type InternalAction =
  | { type: 'load'; draft: OntologyDraft }
  | { type: 'saved'; draft: OntologyDraft; sentDoc: DraftDoc }
  | { type: 'edit'; action: DraftAction }

function reducer(state: EditorState | null, action: InternalAction): EditorState | null {
  switch (action.type) {
    case 'load': {
      const doc = toDoc(action.draft)
      return { ontologyId: action.draft.ontology.id, base: action.draft, baseDoc: doc, doc }
    }
    case 'saved': {
      if (!state) return state
      const savedDoc = toDoc(action.draft)
      // Keep edits made while the save request was in flight.
      const doc = sameDoc(state.doc, action.sentDoc) ? savedDoc : state.doc
      return { ...state, base: action.draft, baseDoc: savedDoc, doc }
    }
    case 'edit':
      return state ? { ...state, doc: applyDraftAction(state.doc, action.action) } : state
  }
}

/**
 * Working-copy editor for an ontology draft. Edits are applied locally and persisted atomically
 * with "Save draft"; the backend rejects saves based on a stale revision (optimistic locking).
 */
export function useDraftEditor(ontologyId: string | undefined) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: queryKeys.draft(ontologyId ?? ''),
    queryFn: () => ontologiesApi.getDraft(ontologyId!),
    enabled: Boolean(ontologyId),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  const [state, dispatchInternal] = useReducer(reducer, null)
  const current = state && state.ontologyId === ontologyId ? state : null

  const dirty = useMemo(() => (current ? !sameDoc(current.doc, current.baseDoc) : false), [current])

  useEffect(() => {
    const data = query.data
    if (!data) return
    // Only react to new server data; local edits are never overwritten implicitly.
    if (!state || state.ontologyId !== data.ontology.id || (!dirty && data !== state.base)) {
      dispatchInternal({ type: 'load', draft: data })
    }
  }, [query.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const invalidateRelated = useCallback(
    (draft: OntologyDraft) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ontologies(draft.ontology.project_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.activity(draft.ontology.project_id) })
      // Everything derived from the draft (validation, preserved-axiom status, RDF export, publish
      // preview, comparisons) - but not the draft query itself, which was just updated in place.
      void queryClient.invalidateQueries({
        predicate: (q) => q.queryKey[0] === 'ontologies' && q.queryKey[1] === draft.ontology.id && q.queryKey[2] !== 'draft',
      })
    },
    [queryClient],
  )

  const saveMutation = useMutation({
    mutationFn: async ({ ontologyId: id, baseRevision, doc }: { ontologyId: string; baseRevision: number; doc: DraftDoc }) =>
      ontologiesApi.saveDraft(id, { base_revision: baseRevision, ...doc }),
    onSuccess: (response: DraftSaveResponse, variables) => {
      queryClient.setQueryData(queryKeys.draft(response.draft.ontology.id), response.draft)
      dispatchInternal({ type: 'saved', draft: response.draft, sentDoc: variables.doc })
      invalidateRelated(response.draft)
    },
  })

  const dispatch = useCallback((action: DraftAction) => dispatchInternal({ type: 'edit', action }), [])

  const save = useCallback(() => {
    if (!current) return Promise.reject(new Error('Draft is not loaded'))
    return saveMutation.mutateAsync({
      ontologyId: current.ontologyId,
      baseRevision: current.base.draft_revision,
      doc: current.doc,
    })
  }, [current, saveMutation])

  const discard = useCallback(() => {
    if (current) dispatchInternal({ type: 'load', draft: current.base })
    saveMutation.reset()
  }, [current, saveMutation])

  const reload = useCallback(async () => {
    const result = await query.refetch()
    if (result.data) {
      dispatchInternal({ type: 'load', draft: result.data })
      invalidateRelated(result.data)
    }
    saveMutation.reset()
  }, [query, saveMutation, invalidateRelated])

  return {
    query,
    doc: current?.doc,
    base: current?.base,
    dirty,
    dispatch,
    save,
    saving: saveMutation.isPending,
    saveError: saveMutation.error,
    lastSave: saveMutation.data,
    discard,
    reload,
    reloading: query.isFetching,
  }
}

export type DraftEditor = ReturnType<typeof useDraftEditor>
