export const TABS = [
  { id: 'metrics', label: 'Metrics' },
  { id: 'mr-review', label: 'MR Review' },
  { id: 'health', label: 'Health' },
  { id: 'docs', label: 'Docs' },
  { id: 'activity', label: 'Activity' },
  { id: 'portfolio', label: 'Portfolio' }
]

// The Support tab is on both ends of a support link (ADR 0073): the helper's counts what needs them, the helped
// person's counts replies waiting. No support link, no tab.
export function visibleTabs(supportRole) {
  return supportRole === 'helper' || supportRole === 'helped' ? [...TABS, { id: 'support', label: 'Support' }] : TABS
}
