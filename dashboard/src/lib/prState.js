// What a PR card should SAY and which buttons it should offer, decided once.
//
// MR Review used to render one paragraph per condition, so a single PR could show six messages at once, some
// contradicting each other ("nothing to approve" beside "approve once checks finish", 2026-10-06). Now the
// conditions are ranked and the first one that applies is the whole story: one headline, one explanation, and
// only the buttons that make sense. A button that cannot be used is hidden, not left looking clickable; the
// exception is a PR that is only WAITING (checks running, an older PR first), where a disabled Approve tells
// you it is coming.

// Refusals the screen already explains with a state of its own. If one of these is left over from an earlier
// click it is stale as soon as the state changes, so it is never shown as an error.
const MIRRORED_REFUSALS = /^(SENT_BACK|CI_PENDING|CI_FAILED|WRONG_BASE)\b/

export function describePrState(pr, { status = 'idle', errorMessage = null } = {}) {
  const ci = pr.checks || { state: 'none', failing: [], pending: [] }
  const waiting = pr.waitingOn || []
  const base = (kind, tone, headline, detail, approve, deny, extra = {}) => ({ kind, tone, headline, detail, approve, deny, actions: [], note: null, rework: null, ...extra })
  const main = pr.baseProblem?.expected || 'main'

  if (status === 'approving') {
    return base('merging', 'working', 'Merging…', 'Rebasing onto main, retesting and merging. You can leave this screen; it carries on.', 'hidden', 'hidden')
  }

  if (pr.sentBack) {
    return base('sent-back', 'blocked', 'Sent back for rework',
      "This PR's ticket was rejected, and a reworked version will update this same PR, so there is nothing to approve.",
      'hidden', 'hidden',
      { rework: pr.rework || null, actions: [{ id: 'clearSentBack', label: 'The rework is already in? Clear the sent-back label' }] })
  }

  if (status === 'reengaged') {
    return base('sent-back-now', 'blocked', 'Not merged: sent back for rework',
      `${errorMessage || 'The merge gate rejected it.'} The ticket will be rebuilt and this PR updated.`, 'hidden', 'hidden')
  }

  if (pr.conflicts) {
    return base('conflict', 'blocked', `Conflicts with ${main}`,
      `It can't merge as it is. Its ticket is sent back automatically and rebuilt on the current ${main}, updating this same PR. Nothing to do here.`, 'hidden', 'hidden')
  }

  if (ci.state === 'failing') {
    return base('checks-failed', 'blocked', 'GitHub checks failed',
      `${ci.failing.join(', ')}. It is sent back for rework automatically, so there is nothing to approve.`, 'hidden', 'hidden')
  }

  if (pr.baseProblem) {
    const b = pr.baseProblem
    return base('wrong-base', 'blocked', `Targets ${b.base}, not ${b.expected}`,
      `Merging it here would not put the work on ${b.expected}. ` +
        (b.parent ? `It is stacked on #${b.parent.number}: merge that first, then change this PR's base to ${b.expected}.` : `Change its base to ${b.expected} on GitHub first.`),
      'hidden', 'enabled')
  }

  if (waiting.length) {
    const first = waiting.map((w) => `#${w.number}`).join(', ')
    return base('waiting-order', 'wait', `Waiting for ${first} to merge first`,
      `It changes the same files (${(waiting[0].shared || []).slice(0, 2).join(', ')}), so merging this one now would conflict.`, 'disabled', 'enabled')
  }

  if (ci.state === 'pending') {
    return base('waiting-checks', 'wait', 'Waiting for GitHub checks',
      `${ci.pending.join(', ')} still running. Approve becomes available when they finish.`, 'disabled', 'enabled')
  }

  if (status === 'error' && errorMessage && !MIRRORED_REFUSALS.test(errorMessage)) {
    return base('error', 'blocked', 'The last merge attempt failed', errorMessage, 'enabled', 'enabled')
  }

  return base('ready', 'ready', 'Ready to merge', null, 'enabled', 'enabled',
    { note: ci.state === 'passing' ? 'GitHub checks passed' : null })
}
