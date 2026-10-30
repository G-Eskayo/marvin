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
// point it at their own server, and must never reach the real one) without an explicit local one to fail over to
// (MARVIN_MR_LOCAL_WEBHOOK_URL, localExplicit: the failover evidence capture's stand-in for this Mac's webhook).
// marvin#940: `backups` ([{ id, url }], e.g. the Linux box, marvin#945) go between the primary and this Mac, in order.
export function mergeMachines({ primaryUrl, primaryId = null, localId = null, explicit = false, localUrl = LOCAL_APPROVE_URL, localExplicit = false, backups = [] }) {
  const here = { id: localId, label: localId ? machineLabel(localId) : 'this Mac', url: localUrl, here: true }
  const others = backups.filter((b) => b?.url && b.id !== primaryId && b.id !== localId).map((b) => ({ id: b.id, label: labelOf(b.id), url: b.url, here: false }))
  if (explicit && localExplicit) return [{ id: primaryId, label: labelOf(primaryId), url: primaryUrl, here: false }, here]
  if (explicit) return [{ id: isLocal(primaryUrl) ? localId : primaryId, label: isLocal(primaryUrl) ? here.label : labelOf(primaryId), url: primaryUrl, here: isLocal(primaryUrl) }]
  if (isLocal(primaryUrl)) return [{ ...here, url: primaryUrl }, ...others]
  return [{ id: primaryId, label: labelOf(primaryId), url: primaryUrl, here: false }, ...others, here]
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

// ── marvin#940 part 4: when the primary can't merge for memory ────────────────────────────────────────────────────
// The primary refused for memory and queued the approval (it would run there by itself). A later machine in the list
// takes it instead only when (1) it says it is fit (GET /merge-ready: awake, on power, at home, idle; lib/merge_backup.py)
// and (2) the primary has dropped its queued copy (POST /merge-forget answers forgotten: true, under its queue lock, so
// its own queue can never start it too). Any doubt -- no answer, not fit, not forgotten -- leaves it waiting on the
// primary. If the backup then can't be reached, it goes back to the primary, which queues it again.

const endpoint = (m, name) => m.url.replace(/\/approve$/, `/${name}`)
const repoOf = (prUrl) => (String(prUrl).match(/github\.com\/([^/]+\/[^/]+)\/pull\//) || [])[1] || ''

async function getJson(url, init, timeoutMs) {
  const res = await fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs) })
  if (!res.ok) throw new Error(`${url} answered ${res.status}`)
  return res.json()
}

// The machine's own answer, { ready, why, os }. Throws when it can't be asked.
export async function askReady(machine, repo, { timeoutMs = 5000 } = {}) {
  return getJson(`${machine.readyUrl || endpoint(machine, 'merge-ready')}?repo=${encodeURIComponent(repo)}`, {}, timeoutMs)
}

// True only when the machine says it dropped its queued copy of this PR.
export async function askForget(machine, prUrl, { timeoutMs = 5000 } = {}) {
  try {
    return (await getJson(endpoint(machine, 'merge-forget'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pr_url: prUrl }) }, timeoutMs))?.forgotten === true
  } catch {
    return false
  }
}

export function memoryFailoverNotice(busy, next) {
  return `The ${busy.label}'s memory is under pressure, merging on ${the(next)} instead.`
}

// #826 item 5: some tests depend on the machine. A merge whose tests ran on another OS than the primary's says so.
export function osNote(busy, busyOs, os) {
  if (!busyOs || !os || busyOs === os) return null
  return `Its tests ran on ${os}; the ${busy.label} runs ${busyOs}, so a test that depends on the machine may answer differently there.`
}

// Resolves { result, machine, note } from the backup that merged it, or null (it stays waiting on `busy`). Rethrows
// a backup's real answer (a refusal stands, as in approveOnAnyMachine). O(backups) small requests.
export async function backupForMemory(prUrl, busy, backups, { ready, forget, send, onSwitch = () => {} }) {
  const repo = repoOf(prUrl)
  for (const machine of backups) {
    let answer
    try { answer = await ready(machine, repo) } catch { continue }
    if (!answer?.ready) continue
    let busyOs = null
    try { busyOs = (await ready(busy, repo))?.os ?? null } catch { /* the note is optional */ }
    if (!(await forget(busy, prUrl))) return null
    try { onSwitch(memoryFailoverNotice(busy, machine), { from: busy, to: machine }) } catch { /* a listener never stops the merge */ }
    try {
      return { result: await send(prUrl, machine), machine, note: osNote(busy, busyOs, answer.os) }
    } catch (err) {
      if (!err?.unreachable) {
        if (err && typeof err === 'object') err.machine = machine
        throw err
      }
      // It went away after the primary dropped its copy: give it back to the primary, which queues it again.
      try {
        return { result: await send(prUrl, busy), machine: busy, note: null }
      } catch (back) {
        if (back && typeof back === 'object' && !back.machine) back.machine = busy
        throw back
      }
    }
  }
  return null
}

