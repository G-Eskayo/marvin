import { approveOnAnyMachine } from './merge_failover.js'

// One Approve, from the click (or a retry of a saved click) to its outcome (marvin#762). The IPC handler and the
// retry both run this, so a retried approval is exactly a click: the same in-flight op (mergeOps.start refuses a PR
// already merging here, which is what stops the Mini coming back from merging it a second time), the same record,
// the same failover.
//
//   start the op -> confirm (clicks only, opt-in popup) -> record in the ledger -> send to the first machine that
//   answers -> conclude the ledger and the op with that answer. No machine: queued, said plainly, retried later.
//
// An interrupted merge's retry (owner decision on #766) passes `machine`, the Mac it was interrupted on, and goes to
// that Mac only: it may have slept mid-merge and still be running it, so no other Mac may start it. That Mac
// unreachable, missing from the list, or answering ALREADY_MERGING (its webhook still has the merge) means nothing
// started: the approval stays interrupted and waiting, the try not counted, and the card goes back to "interrupted".
//
// marvin#940: a machine that refuses for memory AND queues it (MEMORY_PRESSURE, action retry) has kept the approval:
// it runs there by itself when pressure drops. That is waiting-memory, not a failure: saved in the ledger with the
// machine, the card says "Approved: waiting for memory on the Mac mini". A retry of it that finds that machine already
// merging it (ALREADY_MERGING: its queued copy just started) stays waiting, the try not counted.
//
// send(prUrl, url, { onEvent }) is approveMrStream's shape; push(url, op) forwards an op change to the card.
export function createApproveFlow({ mergeOps, ledger, machines, send, push = () => {}, confirm = async () => true, after = () => {} }) {
  return async function approve(url, { number = null, head = null, retry = false, machine: pinned } = {}) {
    const pin = pinned !== undefined
    const targets = pin ? machines().filter((m) => m.id === pinned) : machines()
    const before = pin || retry ? ledger.get(url) : null
    const stillInterrupted = (why) => {
      ledger.conclude(url, 'interrupted', { machine: pinned, reason: before?.reason ?? why, unsent: true })
      push(url, mergeOps.interrupt(url))
      return { merged: false, interrupted: true, waiting: true, reason: why, cancelled: false }
    }
    if (pin && !targets.length) return { merged: false, interrupted: true, waiting: true, reason: `${pinned} is not a merge machine here`, cancelled: false }
    if (!mergeOps.start(url, Date.now(), head)) return { merged: false, cancelled: true, alreadyMerging: true }
    push(url, mergeOps.get(url))
    if (!retry && !(await confirm({ number, url }))) {
      mergeOps.cancel(url)
      push(url, { state: 'idle' })
      return { merged: false, cancelled: true }
    }
    ledger.record(url, { number, head })
    try {
      const { result, machine } = await approveOnAnyMachine(url, targets, {
        send: (prUrl, target) => send(prUrl, target, { onEvent: (event) => push(url, mergeOps.event(url, event)) }),
        onSwitch: (notice) => push(url, mergeOps.notice(url, notice))
      })
      if (result?.interrupted) {
        ledger.conclude(url, 'interrupted', { machine: machine.id, reason: result.reason })
        push(url, mergeOps.interrupt(url))
        return { ...result, cancelled: false }
      }
      ledger.conclude(url, result?.merged ? 'merged' : 'reengaged', { machine: machine.id, reason: result?.reason })
      push(url, mergeOps.finish(url, result))
      try { after(url, result) } catch { /* list bookkeeping never turns a merge into an error */ }
      return { ...result, cancelled: false }
    } catch (err) {
      const queuedForMemory = err?.payload?.code === 'MEMORY_PRESSURE' && err.payload.action === 'retry'
      const stillQueuedThere = retry && before?.outcome === 'waiting-memory' && err?.payload?.code === 'ALREADY_MERGING'
      if (queuedForMemory || stillQueuedThere) {
        const id = err.machine?.id ?? before?.machine ?? null
        const reason = queuedForMemory ? err.payload.message : before?.reason ?? err.payload.message
        ledger.conclude(url, 'waiting-memory', { machine: id, reason, unsent: stillQueuedThere })
        push(url, mergeOps.waitMemory(url, reason, err.machine?.label ?? null))
        return { merged: false, waitingMemory: true, machine: id, machineLabel: err.machine?.label ?? null, reason, cancelled: false }
      }
      if (pin && (err?.noMachine || err?.payload?.code === 'ALREADY_MERGING')) return stillInterrupted(err.message)
      if (err?.noMachine) {
        ledger.conclude(url, 'queued', { reason: err.message })
        push(url, mergeOps.queue(url, err.message))
        return { merged: false, queued: true, reason: err.message, cancelled: false }
      }
      ledger.conclude(url, 'refused', { machine: err?.machine?.id ?? null, reason: err?.message })
      push(url, mergeOps.fail(url, err?.message))
      throw err
    }
  }
}
