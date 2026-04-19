import { useEffect, useRef, RefObject } from 'react'

// Sticky-scroll: stays pinned to the bottom while new content streams in,
// but releases when the user scrolls up. Re-pins when they scroll back down.
//
// How it works:
//   - Scroll events on the container track whether the user is "at bottom"
//   - A ResizeObserver on the inner content detects ANY size change (new
//     entries, markdown reflow, image loads, code block expansion)
//   - When content grows while pinned → scroll to bottom
//
// This is resize-driven, not render-driven — it fires on actual DOM changes
// regardless of React batching or async rendering.
export function useAutoScroll(ref: RefObject<HTMLDivElement | null>): void {
  const pinned = useRef(true)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const content = el.firstElementChild as HTMLElement | null
    if (!content) return

    // Track whether user is near the bottom.
    // 60px threshold forgives small overscroll / rounding.
    const onScroll = () => {
      pinned.current =
        el.scrollTop + el.clientHeight >= el.scrollHeight - 60
    }

    // When content grows and we're pinned, scroll to bottom.
    const ro = new ResizeObserver(() => {
      if (pinned.current) {
        el.scrollTop = el.scrollHeight
      }
    })

    el.addEventListener('scroll', onScroll, { passive: true })
    ro.observe(content)

    // Initial scroll to bottom.
    el.scrollTop = el.scrollHeight

    return () => {
      el.removeEventListener('scroll', onScroll)
      ro.disconnect()
    }
  }, [ref])
}
