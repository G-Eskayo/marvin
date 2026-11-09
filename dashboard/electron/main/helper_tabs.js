// The helper tabs on this machine (marvin#753), for MR Review's helper chip (marvin#848). helper-tab titles each tab
// "● <group> · <title>" (lib/helper_tab.py tab_title) and flips the mark to ✓ or ✗ when it ends. Read from
// `wezterm cli list` when the MR list is read, never on a timer of its own; no WezTerm means no chips.
import { execFile } from 'child_process'
import { promisify } from 'util'
import { existsSync } from 'fs'

const MARKS = { '●': 'running', '✓': 'done', '✗': 'failed' }
const SEP = ' · '

export function parseHelperTabs(panes) {
  if (!Array.isArray(panes)) return []
  const seen = new Set()
  const tabs = []
  for (const p of panes) {
    const raw = typeof p?.tab_title === 'string' ? p.tab_title : ''
    const state = MARKS[raw[0]]
    if (!state || raw[1] !== ' ' || seen.has(p.tab_id ?? raw)) continue
    const rest = raw.slice(2)
    const at = rest.indexOf(SEP)
    if (at <= 0) continue
    seen.add(p.tab_id ?? raw)
    tabs.push({ state, group: rest.slice(0, at), title: rest.slice(at + SEP.length) })
  }
  return tabs
}

const defaultWezterm = () => ['/opt/homebrew/bin/wezterm', '/usr/local/bin/wezterm', '/Applications/WezTerm.app/Contents/MacOS/wezterm'].find((p) => existsSync(p)) || 'wezterm'
const execFileAsync = promisify(execFile)
const defaultRun = async (cmd, args) => (await execFileAsync(cmd, args, { timeout: 3000, maxBuffer: 4 << 20 })).stdout

export async function readHelperTabs({ run = defaultRun, wezterm = defaultWezterm() } = {}) {
  try {
    return parseHelperTabs(JSON.parse(await run(wezterm, ['cli', '--no-auto-start', 'list', '--format', 'json'])))
  } catch {
    return []
  }
}
