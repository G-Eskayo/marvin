import { parseTicketRef } from './mr_review.js'

// The Approve click's own checks: the project may be merged from here.
// Order is now checked in the merge queue (webhook), so desktop and mobile share the same guard.
// A refusal is recorded (#215) before it reaches the screen; an error without a refusal code (a lookup that
// failed) is passed on as it is.
export async function guardApprove(url, { assertMergeable, loadPrs, record }) {
  let prs = []
  try {
    assertMergeable(url)
    prs = await loadPrs()
  } catch (err) {
    if (err.code) {
      const ref = parseTicketRef(prs.find((p) => p.url === url)?.body || '')
      record({ prUrl: url, ticket: ref === null ? null : Number(ref), code: err.code, message: err.message, stage: 'request' })
    }
    throw err
  }
}
