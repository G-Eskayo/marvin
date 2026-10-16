// Pure helpers for MR Review → Proposals (#102, ADR 0068). The store (lib/proposals.py) re-checks everything;
// these exist so a mistake is explained on the form instead of coming back as a store refusal.

export const SNOOZE_OPTIONS = [
  { label: '1 week', days: 7 },
  { label: '1 month', days: 30 },
  { label: '3 months', days: 90 }
]

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }

export function defaultBackup(today = new Date()) {
  return iso(addDays(today, 90))
}

export function prettyDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ''))
  if (!m) return String(s || '')
  return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function checkBackup(backup, today) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(backup || ''))
  if (!m) return 'Pick a date to bring it back anyway.'
  const d = new Date(+m[1], +m[2] - 1, +m[3])
  if (iso(d) !== backup) return 'That date doesn’t exist.'
  if (backup <= iso(today)) return 'The bring-back date has to be in the future.'
  if (backup > iso(addDays(today, 730))) return 'The bring-back date can be at most 2 years out.'
  return null
}

export function untilArgs(form, today = new Date()) {
  const backupError = checkBackup(form.backup, today)
  if (form.mode === 'ticket') {
    const raw = String(form.ticket || '').trim().replace(/^#/, '')
    if (!/^\d+$/.test(raw) || Number(raw) <= 0) return { ok: false, error: 'Enter a ticket number like 123, or create one.' }
    if (backupError) return { ok: false, error: backupError }
    return { ok: true, args: { ticket: Number(raw), backup: form.backup } }
  }
  if (form.mode === 'create' || form.mode === 'text') {
    const value = String((form.mode === 'create' ? form.createTitle : form.text) || '').trim()
    if (!value) return { ok: false, error: form.mode === 'create' ? 'Say what the new ticket is for.' : 'Describe what needs to exist first.' }
    if (value.length > 500) return { ok: false, error: 'Keep it under 500 characters.' }
    if (backupError) return { ok: false, error: backupError }
    return { ok: true, args: { [form.mode === 'create' ? 'create_ticket' : 'text']: value, backup: form.backup } }
  }
  return { ok: false, error: 'Choose a ticket or a description.' }
}

export function doneMessage(proposal) {
  const s = proposal?.status
  if (!s) return 'Done'
  const back = s.backup ? ` (back by ${prettyDate(s.backup)} at the latest)` : ''
  switch (s.state) {
    case 'ticketed': return `Made ticket #${s.ticket}`
    case 'snoozed': return `Snoozed until ${prettyDate(s.until)}`
    case 'dismissed': return `Dismissed: ${s.reason}`
    case 'dismissed_until': return s.ticket ? `Dismissed until #${s.ticket} is done${back}` : `Dismissed until “${s.text}”${back}`
    default: return 'Done'
  }
}

export function toggleLabel(count) {
  return count > 0 ? `Proposals (${count})` : 'Proposals'
}
