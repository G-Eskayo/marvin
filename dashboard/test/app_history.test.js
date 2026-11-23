import { describe, it, expect } from 'vitest'
import { historyKeyAction, applyHistoryKey } from '../src/lib/app_history.js'
import { startHistory, visit } from '../src/lib/nav_history.js'

describe('historyKeyAction: keyboard to history action', () => {
  it('Cmd/Ctrl+[ = back, Cmd/Ctrl+] = forward', () => {
    expect(historyKeyAction({ metaKey: true, key: '[', shiftKey: false, target: {} })).toBe('back')
    expect(historyKeyAction({ ctrlKey: true, key: '[', shiftKey: false, target: {} })).toBe('back')
    expect(historyKeyAction({ metaKey: true, key: ']', shiftKey: false, target: {} })).toBe('forward')
    expect(historyKeyAction({ ctrlKey: true, key: ']', shiftKey: false, target: {} })).toBe('forward')
  })
  it('skips editable targets (input, textarea, select, contenteditable)', () => {
    for (const target of [
      { tagName: 'INPUT' },
      { tagName: 'TEXTAREA' },
      { tagName: 'SELECT' },
      { isContentEditable: true }
    ]) {
      expect(historyKeyAction({ metaKey: true, key: '[', target })).toBeNull()
    }
  })
  it('rejects other keys and modifier combos', () => {
    const target = {}
    for (const e of [
      { metaKey: false, ctrlKey: false, key: '[', target },
      { metaKey: true, key: 'Enter', target },
      { key: '[', target },
      { metaKey: true, key: 'Backspace', target }
    ]) {
      expect(historyKeyAction(e)).toBeNull()
    }
  })
})

describe('applyHistoryKey: move through history', () => {
  const start = startHistory({ tab: 'workshop', item: null })
  const withOne = visit(start, { tab: 'docs' })
  const withTwo = visit(withOne, { tab: 'mr-review' })

  it('back moves to the prior screen', () => {
    const result = applyHistoryKey('back', withTwo)
    expect(result).not.toBeNull()
    expect(result.screen.tab).toBe('docs')
    expect(result.history.index).toBe(1)
  })
  it('forward moves to the next screen', () => {
    const back = applyHistoryKey('back', withTwo)
    const fwd = applyHistoryKey('forward', back.history)
    expect(fwd.screen.tab).toBe('mr-review')
    expect(fwd.history.index).toBe(2)
  })
  it('at the start, back returns null; at the end, forward returns null', () => {
    expect(applyHistoryKey('back', start)).toBeNull()
    expect(applyHistoryKey('forward', withTwo)).toBeNull()
  })
  it('null history or action returns null', () => {
    expect(applyHistoryKey(null, withTwo)).toBeNull()
    expect(applyHistoryKey('back', null)).toBeNull()
  })
})
