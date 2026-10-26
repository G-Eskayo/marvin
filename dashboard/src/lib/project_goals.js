// Project goals (Gil, 2026-10-26): each private profile's goal, signals and status (readGoals in
// electron/main/profiles.js). Display rules shared by the board header and Activity's projects list.

export const arrowOf = (better) => (better === 'up' ? '↑' : better === 'down' ? '↓' : '')

const STATUS_LABEL = { parked: 'Parked', 'done (handed off)': 'Done', archived: 'Archived' }
export const statusLabel = (status) => STATUS_LABEL[status] || null
export const isActive = (g) => !statusLabel(g?.status)

export function clip(text, max) {
  const s = String(text ?? '')
  return s.length <= max ? s : `${s.slice(0, max - 1).trimEnd()}…`
}

// The first clause of a goal (up to the first colon, semicolon, comma, full stop or dash), at most 40 characters.
export function shortGoal(goal) {
  if (typeof goal !== 'string' || !goal.trim()) return null
  const first = goal.split(/[:;,.—–]/)[0].trim() || goal.trim()
  return clip(first, 40)
}

// No signal is measured yet: every value is "—" with the tooltip "not measured yet".
export const UNMEASURED = { value: '—', title: 'not measured yet' }
