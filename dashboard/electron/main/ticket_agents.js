import { readFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// What the ticket agents (lib/ticket_agents.py) would do or just did, for the review panel in
// Health -> Autonomous agents. The agents write the proposals file every hourly pass.
export const PROPOSALS_PATH = path.join(homedir(), '.claude', 'logs', 'ticket-agent-proposals.json')
export const CONFIG_PATH = path.join(homedir(), '.agents', 'config', 'ticket_agents.json')

const WORD = { add_label: (a) => `+ ${a}`, remove_label: (a) => `− ${a}`, comment: () => 'comment' }

export function groupProposals(proposals) {
  const out = {}
  const index = {}
  for (const x of proposals) {
    const key = `${x.agent}|${x.repo}#${x.number}`
    if (!index[key]) {
      index[key] = { repo: x.repo, number: x.number, title: x.title, changes: [], why: x.why }
      ;(out[x.agent] ||= []).push(index[key])
    }
    index[key].changes.push((WORD[x.op] || (() => x.op))(x.arg))
    // the add_label line carries the most useful explanation (the remove line repeats it)
    if (x.op === 'add_label') index[key].why = x.why
  }
  return out
}

export function readTicketAgents({ proposalsPath = PROPOSALS_PATH, configPath = CONFIG_PATH } = {}) {
  let p
  try {
    p = JSON.parse(readFileSync(proposalsPath, 'utf-8'))
  } catch {
    return null
  }
  let config = {}
  try {
    config = JSON.parse(readFileSync(configPath, 'utf-8'))
  } catch {
    // config unreadable: the agents themselves fall back to propose-only
  }
  return {
    generatedAt: p.generated_at,
    mode: config.mode || p.mode || 'propose',
    actAfter: p.act_after || config.act_after || null,
    pinned: config.agents || {},
    byAgent: p.by_agent || {},
    grouped: groupProposals(p.proposals || []),
    total: (p.proposals || []).length
  }
}
