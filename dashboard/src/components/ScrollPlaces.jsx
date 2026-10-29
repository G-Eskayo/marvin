import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import { createScrollArea } from '../lib/scroll_places.js'

// React side of lib/scroll_places.js (#755). The component that owns a scroll box calls useScrollArea, puts the ref it
// returns on the box (a callback ref, so a box drawn after a loading state is still found) and wraps the box's children
// in <ScrollArea value={area}>; any view inside that swaps what it shows (a list for an item) calls
// useScrollPlace(slot, key): its own fixed slot name, and a key for what it shows now (null when nothing of its own).
// The slot is a name, not useId: a client-rendered useId is a counter, so a remounted tab would never match its place. The box then opens each
// screen where it was last left, or at its top.

const STORE = new Map() // every area's places, for the life of the window
const AreaContext = createContext(null)
export const ScrollArea = AreaContext.Provider
const USER_INPUT = ['wheel', 'pointerdown', 'touchstart', 'keydown']
// Before paint in the app; a no-op in the tests' static render, which has no layout to measure.
const useBeforePaint = typeof document === 'undefined' ? useEffect : useLayoutEffect

export function useScrollArea(name, base = '') {
  const area = useMemo(() => createScrollArea({ name, store: STORE }), [name])
  const [el, ref] = useState(null)
  useBeforePaint(() => {
    if (!el) return
    area.attach(el)
    const onScroll = () => area.onScroll()
    const onInput = () => area.onUserInput()
    el.addEventListener('scroll', onScroll, { passive: true })
    for (const t of USER_INPUT) el.addEventListener(t, onInput, { passive: true })
    // A waiting restore needs to hear when the content grows. Content can grow inside a full-height child without that
    // child's box changing (MR Review's list loads inside an h-full column), so any DOM change under the box counts too,
    // not just a direct child's resize (images, fonts). Both are no-ops unless a restore is waiting.
    const grew = () => area.onContentResize()
    const resize = new ResizeObserver(grew)
    const watch = () => { resize.disconnect(); for (const c of el.children) resize.observe(c) }
    const changes = new MutationObserver((records) => {
      if (records.some((r) => r.target === el)) watch()
      grew()
    })
    changes.observe(el, { childList: true, subtree: true })
    watch()
    return () => {
      el.removeEventListener('scroll', onScroll)
      for (const t of USER_INPUT) el.removeEventListener(t, onInput)
      resize.disconnect()
      changes.disconnect()
      area.detach()
    }
  }, [area, el])
  useBeforePaint(() => area.setBase(base), [area, base])
  return { area, ref }
}

export function useScrollPlace(slot, value) {
  const area = useContext(AreaContext)
  useBeforePaint(() => { area?.setSegment(slot, value ?? null) }, [area, slot, value])
  useBeforePaint(() => () => area?.removeSegment(slot), [area, slot])
}

// For a deliberate jump inside the nearest area (a search hit, a flagged check): it wins over a waiting restore.
export function useScrollAreaControl() {
  return useContext(AreaContext)
}
