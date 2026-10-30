import { readFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Vitals > Accounts (marvin#974, the card is #640): every credential MARVIN depends on, per machine, from
// lib/accounts.py. The Mini's health sweep (every 15 min) writes accounts-status.json for every machine; on open the
// card shows that saved view first, and a fresh check of THIS machine's accounts (`accounts.py check --json`) replaces
// its own rows when it lands. Renewing opens a labelled helper tab running bin/marvin-renew: the person approves or
// pastes the login there; no credential ever passes through this process, its IPC or its logs.

const HOME = homedir()
export const ACCOUNTS_STATUS_PATH = path.join(HOME, '.claude', 'logs', 'accounts-status.json')
const PY = path.join(HOME, '.agents', 'venv', 'bin', 'python')
const ACCOUNTS_PY = path.join(HOME, '.agents', 'lib', 'accounts.py')
const HELPER_TAB = path.join(HOME, '.agents', 'bin', 'helper-tab')
const RENEW = path.join(HOME, '.agents', 'bin', 'marvin-renew')

// Inventory id -> marvin-renew's account name. Only these can be renewed from the dashboard; anything else (Tailscale,
// the interactive Claude login, ngrok) shows its exact command instead. A fixed table, so the renderer can never
// choose what runs.
export const RENEWABLE = Object.freeze({
  'github-token': 'github',
  'gh-login': 'github',
  'claude-setup-token': 'claude-setup-token',
  'anthropic-api-key': 'anthropic-api-key',
  'marvin-bot': 'marvin-bot-token'
})
const TITLES = {
  github: 'Renew GitHub',
  'claude-setup-token': 'Renew Claude setup-token',
  'anthropic-api-key': 'Renew Anthropic API key',
  'marvin-bot-token': 'Renew MARVIN-bot token'
}

export function readAccountsStatus(file = ACCOUNTS_STATUS_PATH, read = (p) => readFileSync(p, 'utf-8')) {
  try {
    const d = JSON.parse(read(file))
    if (!d || !Array.isArray(d.accounts)) return { generatedAt: null, by: null, accounts: [], problem: 'unreadable' }
    return { generatedAt: d.generated_at || null, by: d.by || null, accounts: d.accounts.filter((r) => r && typeof r.id === 'string'), problem: null }
  } catch (err) {
    return { generatedAt: null, by: null, accounts: [], problem: err?.code === 'ENOENT' ? 'missing' : 'unreadable' }
  }
}

// The saved view with this machine's rows replaced by a fresh local check (rows of other machines are kept).
export function mergeLocal(saved, fresh, machine) {
  if (!fresh || !Array.isArray(fresh.accounts) || !fresh.accounts.length) return saved
  const others = saved.accounts.filter((r) => r.machine !== machine)
  return { ...saved, accounts: [...fresh.accounts.map((r) => ({ ...r, machine })), ...others] }
}

// What pressing Renew does for one row, as data: a helper tab here (fixed argv), or the exact command and where to
// run it. Never throws for a known row; null for an id outside the inventory.
export function renewPlan(row, thisMachine) {
  const account = RENEWABLE[row?.id]
  const renew = row?.renew || {}
  if (!row || typeof row.id !== 'string') return null
  if (!account) return { how: 'command', command: renew.command || null, where: renew.where || row.machine || 'that machine' }
  const cmd = `~/.agents/bin/marvin-renew ${account}`
  if (row.machine && thisMachine && row.machine !== thisMachine) return { how: 'command', command: cmd, where: row.machine }
  return {
    how: 'tab',
    title: TITLES[account],
    argv: [HELPER_TAB, '--group', 'Accounts', '--title', TITLES[account], '--on-exit', `${PY} ${ACCOUNTS_PY} sweep >/dev/null 2>&1`, '--', RENEW, account],
    steps: renew.steps || null
  }
}

export function createAccounts({ machine = () => null, execFile, statusPath = ACCOUNTS_STATUS_PATH, read } = {}) {
  return {
    // fresh=false: the saved view at once. fresh=true: this machine checked now (a few seconds), merged in.
    async list({ fresh = false } = {}) {
      const saved = readAccountsStatus(statusPath, read)
      if (!fresh) return saved
      try {
        const { stdout } = await execFile(PY, [ACCOUNTS_PY, 'check', '--json'], { timeout: 90_000 })
        return mergeLocal(saved, JSON.parse(stdout), machine())
      } catch (err) {
        return { ...saved, freshProblem: String(err?.message || err).split('\n')[0].slice(0, 200) }
      }
    },
    // Renew one account. Only ids from the inventory; the row comes from the saved view, never from the renderer.
    async renew(id, rowMachine) {
      if (typeof id !== 'string' || !(id in RENEWABLE || /^[a-z][a-z-]{1,40}$/.test(id))) throw new Error('unknown account')
      const saved = readAccountsStatus(statusPath, read)
      const here = machine()
      const row = saved.accounts.find((r) => r.id === id && (rowMachine ? r.machine === rowMachine : r.machine === here)) ||
        (RENEWABLE[id] ? { id, machine: rowMachine || here, renew: {} } : null)
      const plan = renewPlan(row, here)
      if (!plan) throw new Error('unknown account')
      if (plan.how !== 'tab') return plan
      await execFile(plan.argv[0], plan.argv.slice(1), { timeout: 45_000 }) // helper-tab returns once the tab is open
      return { how: 'tab', title: plan.title, steps: plan.steps, started: true }
    }
  }
}
