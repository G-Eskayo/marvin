import { describe, it, expect } from 'vitest'
import { parseHelperTabs, readHelperTabs } from '../electron/main/helper_tabs.js'

// MR Review's helper chip (marvin#848, the owner's "owner" answer on #767): the helper tabs come from `wezterm cli list`,
// titled "● <group> · <title>" by helper-tab (lib/helper_tab.py tab_title).
const pane = (tab_id, tab_title) => ({ window_id: 1, tab_id, pane_id: tab_id * 10, tab_title, title: 'zsh' })

describe('parseHelperTabs', () => {
  it('reads running, finished and failed helpers; other tabs are not helpers', () => {
    const tabs = parseHelperTabs([
      pane(1, '● MARVIN · #848 MR Review by project'),
      pane(2, '✓ Seal Speak · #216 wire: pick a language'),
      pane(3, '✗ MARVIN Voice · #7 build'),
      pane(4, 'zsh'),
      pane(5, ''),
      pane(6, '● no separator here')
    ])
    expect(tabs).toEqual([
      { state: 'running', group: 'MARVIN', title: '#848 MR Review by project' },
      { state: 'done', group: 'Seal Speak', title: '#216 wire: pick a language' },
      { state: 'failed', group: 'MARVIN Voice', title: '#7 build' }
    ])
  })
  it('a tab with several panes is one helper', () => {
    expect(parseHelperTabs([pane(1, '● MARVIN · #1 x'), { ...pane(1, '● MARVIN · #1 x'), pane_id: 11 }])).toHaveLength(1)
  })
  it('a title containing the separator keeps the rest in the title (group never has it: tab_title strips it)', () => {
    expect(parseHelperTabs([pane(1, '● MARVIN · #1 a · b')])[0]).toEqual({ state: 'running', group: 'MARVIN', title: '#1 a · b' })
  })
  it('garbage in, nothing out', () => {
    expect(parseHelperTabs(null)).toEqual([])
    expect(parseHelperTabs([null, 3, {}])).toEqual([])
  })
})

describe('readHelperTabs', () => {
  it('asks wezterm without starting it, and parses what it says', async () => {
    const calls = []
    const run = async (cmd, args) => { calls.push([cmd, ...args]); return JSON.stringify([pane(1, '● MARVIN · #848 x')]) }
    expect(await readHelperTabs({ run, wezterm: '/x/wezterm' })).toEqual([{ state: 'running', group: 'MARVIN', title: '#848 x' }])
    expect(calls[0]).toEqual(['/x/wezterm', 'cli', '--no-auto-start', 'list', '--format', 'json'])
  })
  it('no wezterm, or wezterm not running, means no chips, never an error', async () => {
    expect(await readHelperTabs({ run: async () => { throw new Error('ENOENT') } })).toEqual([])
    expect(await readHelperTabs({ run: async () => 'not json' })).toEqual([])
  })
})
