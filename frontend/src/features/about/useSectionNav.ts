import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

export const PAGE_TOP_ID = 'about-top'
export const PAGE_END_ID = 'about-end'

function scrollParent(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node)
    if ((overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight) return node
  }
  return null
}

// Scrolls only the page's own scroll container, vertically, so other overflow containers are never nudged.
function scrollToElement(element: HTMLElement, smooth: boolean) {
  const behavior = smooth ? 'smooth' : 'auto'
  const container = scrollParent(element)
  if (!container) {
    element.scrollIntoView({ behavior, block: 'start' })
    return
  }
  const margin = Number.parseFloat(getComputedStyle(element).scrollMarginTop) || 0
  const top = element.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - margin
  container.scrollTo({ top, behavior })
}

/**
 * In-page navigation for a long, sectioned page: highlights the section being read (scroll spy),
 * scrolls smoothly to a section (respecting reduced motion) and keeps the URL hash in sync so a
 * section can be linked to or reloaded.
 */
export function useSectionNav<T extends string>(ids: readonly T[]) {
  const [active, setActive] = useState<T>(ids[0])
  const navigate = useNavigate()
  const location = useLocation()
  // While a programmatic scroll is running the observers must not override the chosen section.
  const lockedUntil = useRef(0)
  // The hash this hook last wrote, so its own URL updates are not mistaken for external changes.
  const ownedHash = useRef<string | null>(null)

  useEffect(() => {
    const visible = new Set<string>()
    const sections = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id)
          else visible.delete(entry.target.id)
        }
        if (Date.now() < lockedUntil.current) return
        // Above the first section (the page header) the first entry stays highlighted.
        const current = ids.find((id) => visible.has(id)) ?? (visible.has(PAGE_TOP_ID) ? ids[0] : undefined)
        if (current) setActive(current)
      },
      // A thin band near the top of the viewport decides which section is being read.
      { rootMargin: '-15% 0px -70% 0px' },
    )
    const end = new IntersectionObserver((entries) => {
      if (Date.now() < lockedUntil.current) return
      if (entries.some((entry) => entry.isIntersecting)) setActive(ids[ids.length - 1])
    })
    for (const id of [PAGE_TOP_ID, ...ids]) {
      const element = document.getElementById(id)
      if (element) sections.observe(element)
    }
    const sentinel = document.getElementById(PAGE_END_ID)
    if (sentinel) end.observe(sentinel)
    return () => {
      sections.disconnect()
      end.disconnect()
    }
  }, [ids])

  const scrollTo = useCallback(
    (id: string) => {
      const element = document.getElementById(id)
      if (!element) return
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      lockedUntil.current = Date.now() + (reduceMotion ? 150 : 1000)
      if (id === PAGE_TOP_ID) setActive(ids[0])
      else if ((ids as readonly string[]).includes(id)) setActive(id as T)
      scrollToElement(element, !reduceMotion)
      ownedHash.current = id === PAGE_TOP_ID ? '' : id
      navigate({ hash: ownedHash.current }, { replace: true, preventScrollReset: true })
    },
    [ids, navigate],
  )

  // Follows hash changes made from outside the page: first load, a link or the address bar.
  useEffect(() => {
    const id = location.hash.slice(1)
    if (id === ownedHash.current || !(ids as readonly string[]).includes(id)) return
    requestAnimationFrame(() => scrollTo(id))
  }, [ids, location.hash, scrollTo])

  return { active, scrollTo }
}
