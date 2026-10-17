import { useEffect, useRef, useState } from 'react'

/**
 * Adds a reveal flag once the element scrolls into view. Used for the
 * how-it-works sequence; purely decorative, so reduced motion simply skips it.
 */
export function useInView<T extends HTMLElement>(options?: IntersectionObserverInit) {
  const ref = useRef<T>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setInView(true)
            observer.disconnect()
          }
        })
      },
      options ?? { threshold: 0.25 },
    )
    observer.observe(node)

    // Safety net: content that is revealed on scroll must never stay hidden,
    // so it appears anyway if the observer has not fired shortly after mount.
    const fallback = window.setTimeout(() => setInView(true), 2000)

    return () => {
      window.clearTimeout(fallback)
      observer.disconnect()
    }
  }, [options])

  return { ref, inView }
}
