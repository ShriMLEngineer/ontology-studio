import { useCallback, useSyncExternalStore } from 'react'

const KEY = 'ols.reviewerName'
const EVENT = 'ols:reviewer-changed'

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(EVENT, callback)
  window.addEventListener('storage', callback)
  return () => {
    window.removeEventListener(EVENT, callback)
    window.removeEventListener('storage', callback)
  }
}

/**
 * Name recorded on SME decisions, comments, applications and publications.
 * There is no authentication in the MVP, so the reviewer identifies themselves explicitly.
 */
export function useReviewerName(): [string, (name: string) => void] {
  const name = useSyncExternalStore(subscribe, read, () => '')
  const setName = useCallback((value: string) => {
    try {
      localStorage.setItem(KEY, value.trim())
    } catch {
      /* storage unavailable - keep the in-memory value only */
    }
    window.dispatchEvent(new Event(EVENT))
  }, [])
  return [name, setName]
}
