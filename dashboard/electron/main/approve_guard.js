import { assertInOrder } from './pr_order.js'
import { parseTicketRef } from './mr_review.js'
import { remediationFor, needsYouFor, CODE_INFO } from './failure.js'

// The Approve click's own checks: the project may be merged from here, and the PR is in order and targets the base
// branch. A refusal is recorded (#215) before it reaches the screen; an error without a refusal code (a lookup that
// failed) is passed on as it is.
export async function guardApprove(url, { assertMergeable, loadPrs, record }) {
  let prs = []
  try {
    assertMergeable(url)
    prs = await loadPrs()
    assertInOrder(prs, url)
  } catch (err) {
    if (err.code) {
      const ref = parseTicketRef(prs.find((p) => p.url === url)?.body || '')
      record({ prUrl: url, ticket: ref === null ? null : Number(ref), code: err.code, message: err.message, stage: 'request' })
    }
    throw err
  }
}

// Wrapper that runs guardApprove then approveFlow, catching any thrown error (coded or not) and
// resolving to a consistent {merged:false, code, message, remediation, stage, cancelled:false} shape.
// Used by the IPC handler to ensure consistent error handling across all failure paths.
export async function runApprove(url, opts, { assertMergeable, loadPrs, record, approveFlow }) {
  try {
    await guardApprove(url, { assertMergeable, loadPrs, record })
    return await approveFlow(url, opts)
  } catch (error) {
    const payload = error?.payload || {}
    // Codes can be on error?.code (from guardApprove / pr_order checks) or error?.payload?.code (from approveFlow/webhook)
    const code = payload.code || error?.code || 'UNKNOWN'
    const message = payload.message || error?.message || 'Unknown error'
    const stage = payload.stage || 'request'
    const remediation = remediationFor(code)
    const needsYou = needsYouFor(code)
    return {
      merged: false,
      code,
      message,
      remediation,
      stage,
      cancelled: false,
      technicalDetails: code,
      ...(needsYou && { needsYou })
    }
  }
}
