import { describe, it, expect } from 'vitest'
import { untilArgs, defaultBackup, doneMessage, toggleLabel, SNOOZE_OPTIONS } from '../src/lib/proposals_view.js'

const TODAY = new Date('2026-10-15T12:00:00')

describe('dismiss-until form', () => {
  const base = { mode: 'ticket', ticket: '', createTitle: '', text: '', backup: '2027-01-13' }

  it('a ticket number, with or without #', () => {
    expect(untilArgs({ ...base, ticket: '#123' }, TODAY)).toEqual({ ok: true, args: { ticket: 123, backup: '2027-01-13' } })
    expect(untilArgs({ ...base, ticket: ' 45 ' }, TODAY)).toEqual({ ok: true, args: { ticket: 45, backup: '2027-01-13' } })
  })

  it('a ticket to create, or a description', () => {
    expect(untilArgs({ ...base, mode: 'create', createTitle: ' Run Ollama on both Macs ' }, TODAY).args)
      .toEqual({ create_ticket: 'Run Ollama on both Macs', backup: '2027-01-13' })
    expect(untilArgs({ ...base, mode: 'text', text: 'the phone app ships' }, TODAY).args)
      .toEqual({ text: 'the phone app ships', backup: '2027-01-13' })
  })

  it('says what is wrong instead of sending something the store will refuse', () => {
    const bad = [
      { ...base, ticket: '' }, { ...base, ticket: 'abc' }, { ...base, ticket: '0' }, { ...base, ticket: '12.5' },
      { ...base, mode: 'create', createTitle: '   ' }, { ...base, mode: 'text', text: '' },
      { ...base, mode: 'text', text: 'x'.repeat(501) },
      { ...base, ticket: '5', backup: '' }, { ...base, ticket: '5', backup: '2026-10-15' }, { ...base, ticket: '5', backup: '2026-10-01' },
      { ...base, ticket: '5', backup: '2029-01-01' }, { ...base, ticket: '5', backup: 'soon' }, { ...base, mode: 'nope', ticket: '5' }
    ]
    for (const form of bad) {
      const r = untilArgs(form, TODAY)
      expect(r.ok, JSON.stringify(form)).toBe(false)
      expect(r.error.length).toBeGreaterThan(5)
    }
  })

  it('backup date defaults to 90 days out', () => {
    expect(defaultBackup(TODAY)).toBe('2027-01-13')
  })
})

describe('what a card says after an action', () => {
  const p = (status) => ({ id: 'a', title: 'T', status })
  it('covers every outcome in plain words', () => {
    expect(doneMessage(p({ state: 'ticketed', ticket: 777 }))).toBe('Made ticket #777')
    expect(doneMessage(p({ state: 'snoozed', until: '2026-10-22' }))).toBe('Snoozed until Oct 22, 2026')
    expect(doneMessage(p({ state: 'dismissed', reason: 'Covered elsewhere' }))).toBe('Dismissed: Covered elsewhere')
    expect(doneMessage(p({ state: 'dismissed_until', ticket: 9, backup: '2027-01-15' }))).toBe('Dismissed until #9 is done (back by Jan 15, 2027 at the latest)')
    expect(doneMessage(p({ state: 'dismissed_until', text: 'the phone app ships', backup: '2027-01-15' }))).toBe('Dismissed until “the phone app ships” (back by Jan 15, 2027 at the latest)')
    expect(doneMessage(p({ state: 'weird' }))).toBe('Done')
    expect(doneMessage(null)).toBe('Done')
  })
})

describe('toggle label', () => {
  it('shows a count only when there is something', () => {
    expect(toggleLabel(3)).toBe('Proposals (3)')
    expect(toggleLabel(0)).toBe('Proposals')
    expect(toggleLabel(null)).toBe('Proposals')
  })
  it('offers week, month and quarter snoozes', () => {
    expect(SNOOZE_OPTIONS.map((o) => o.days)).toEqual([7, 30, 90])
  })
})
