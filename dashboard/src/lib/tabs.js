export const TABS = [
  { id: 'metrics', label: 'Metrics' },
  // Workshop (#862, ADR 0080) ships beside Activity and MR Review until it covers everything they show.
  { id: 'workshop', label: 'Workshop' },
  { id: 'mr-review', label: 'MR Review' },
  { id: 'health', label: 'Health' },
  { id: 'docs', label: 'Docs' },
  { id: 'activity', label: 'Activity' },
  { id: 'portfolio', label: 'Portfolio' }
]

// The Support tab is on both ends of a support link (ADR 0073): the helper's counts what needs them, the helped
// person's counts replies waiting. No support link, no tab.
// The Vitals tab mock-up (marvin#873) shows only while its switch (Health's view row) is on, just before Health; no tab is
// removed until Gil approves it (#878).
export function visibleTabs(supportRole, { vitals = false } = {}) {
  let tabs = vitals ? TABS.flatMap((t) => (t.id === 'health' ? [{ id: 'vitals', label: 'Vitals (mock-up)' }, t] : [t])) : TABS
  if (supportRole === 'helper' || supportRole === 'helped') tabs = [...tabs, { id: 'support', label: 'Support' }]
  return tabs
}

// The switch is remembered on this Mac (this window's storage), off by default; storage that fails reads as off.
export const VITALS_SWITCH_KEY = 'vitals.mockup'
export function readVitalsSwitch(storage) {
  try { return storage?.getItem(VITALS_SWITCH_KEY) === 'on' } catch { return false }
}
export function writeVitalsSwitch(storage, on) {
  try { storage?.setItem(VITALS_SWITCH_KEY, on ? 'on' : 'off') } catch { /* private window or full: the switch just won't stick */ }
}
