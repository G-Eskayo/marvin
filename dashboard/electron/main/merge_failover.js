import { machineLabel } from '../../src/lib/merge_progress.js'

// marvin#762: Approve when the Mac mini is down. Every approval used to go to the Mini's merge service only, so on
// 2026-10-29 seven clicks in two minutes all timed out and nothing remembered them. Now an approval tries the Mini
// first (the primary automation host, ADR 0032), and when it cannot be reached at all -- refused, no route, no answer
// within a few seconds -- the same merge gate on this machine (its own webhook on localhost:7878) runs it instead.
//
// Only "could not reach it" fails over. Any answer from a machine (merged, sent back, refused for low disk) stands:
// a request that arrived may be merging, and sending it to a second machine is how a PR would merge twice.

export const LOCAL_APPROVE_URL = 'http://localhost:7878/approve'
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]'])

function isLocal(url) {
  try { return LOCAL_HOSTS.has(new URL(url).hostname) } catch { return false }
}

// The machines an approval may go to, in order: [{ id, label, url, here }]. One entry when there is nowhere else to
// go: this machine is the primary, or the webhook URL was set explicitly (MARVIN_MR_WEBHOOK_URL: evidence captures
// point it at their own server, and must never reach the real one).
export function mergeMachines({ primaryUrl, primaryId = null, localId = null, explicit = false, localUrl = LOCAL_APPROVE_URL }) {
  const here = { id: localId, label: localId ? machineLabel(localId) : 'this Mac', url: localUrl, here: true }
  if (explicit) return [{ id: isLocal(primaryUrl) ? localId : primaryId, label: isLocal(primaryUrl) ? here.label : labelOf(primaryId), url: primaryUrl, here: isLocal(primaryUrl) }]
  if (isLocal(primaryUrl)) return [{ ...here, url: primaryUrl }]
  return [{ id: primaryId, label: labelOf(primaryId), url: primaryUrl, here: false }, here]
}

// The primary is a Mac mini unless the registry says otherwise; "the merge machine" reads oddly in "The … is offline".
function labelOf(id) {
  return id ? machineLabel(id) : 'Mac mini'
}

const the = (m) => (m.here ? `this ${m.label.replace(/^this /, '')}` : `the ${m.label}`)

export function failoverNotice(down, next) {
  return `The ${down.label} is offline, merging on ${the(next)} instead.`
}

// Why a machine could not take it, in words: this machine refusing a connection means its webhook isn't running;
// anything else (no answer, no route) reads as the machine being offline.
function whyDown({ machine, code }) {
  if (machine.here && code === 'ECONNREFUSED') return `${the(machine)}'s merge service isn't running`
  return `${the(machine)} is offline`
}

export function noMachineReason(failures) {
  if (failures.length === 1) {
    const w = whyDown(failures[0])
    return `${w[0].toUpperCase()}${w.slice(1)}, so nothing can merge right now. Your approval is saved and will merge by itself when it comes back.`
  }
  return `Neither Mac can merge right now: ${failures.map(whyDown).join(', and ')}. Your approval is saved and will merge by itself when one comes back.`
}

// Send to each machine in turn until one answers. Resolves { result, machine } with the answering machine's result;
// rethrows its error when it answered with one. When none could be reached, throws an Error with `noMachine: true`
// and a plain message (the caller keeps the approval queued). onSwitch(notice) is called once per hop to the next.
// O(machines) requests, at most one per machine.
export async function approveOnAnyMachine(prUrl, machines, { send, onSwitch = () => {} }) {
  const failures = []
  for (let i = 0; i < machines.length; i++) {
    const machine = machines[i]
    try {
      return { result: await send(prUrl, machine.url, machine), machine }
    } catch (err) {
      if (!err?.unreachable) {
        if (err && typeof err === 'object') err.machine = machine
        throw err
      }
      failures.push({ machine, code: err.code || null })
      const next = machines[i + 1]
      if (next) { try { onSwitch(failoverNotice(machine, next), { from: machine, to: next }) } catch { /* a listener never stops the merge */ } }
    }
  }
  throw Object.assign(new Error(noMachineReason(failures)), { noMachine: true, failures })
}
