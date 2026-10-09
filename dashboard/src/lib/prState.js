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
const MIRRORED_REFUSALS = /^(SENT_BACK|CI_PENDING|CI_FAILED|WRONG_BASE|NO_UI_EVIDENCE)\b/

export function describePrState(pr, { status = 'idle', errorMessage = null } = {}) {
  const ci = pr.checks || { state: 'none', failing: [], pending: [] }
  const waiting = pr.waitingOn || []
  const base = (kind, tone, headline, detail, approve, deny, extra = {}) => ({ kind, tone, headline, detail, approve, deny, actions: [], note: null, rework: null, ...extra })
  const main = pr.baseProblem?.expected || 'main'

  if (status === 'approving') {
    return base('merging', 'working', 'Merging…', 'Merging. It is rebased and retested first only if main changed files this PR also changes. You can leave this screen; it carries on.', 'hidden', 'hidden')
  }

  if (pr.sentBack) {
    return base('sent-back', 'blocked', 'Sent back for rework',
      "This PR's ticket was rejected, and a reworked version will update this same PR, so there is nothing to approve.",
      'hidden', 'hidden',
      { rework: pr.rework || null, actions: [{ id: 'clearSentBack', label: 'The rework is already in? Clear the sent-back label' }] })
  }

  // Its ticket is closed: the work landed another way (built directly, or by another PR), so this one is probably a
  // duplicate (#319, 2026-10-09). Close it on GitHub once main is confirmed to have the change.
  if (pr.ticketClosed) {
    return base('ticket-closed', 'blocked', 'Its ticket is already closed',
      `Ticket ${pr.ticketRef ? `#${pr.ticketRef} ` : ''}was closed, so this PR is probably superseded: the work reached ${main} another way. Check that ${main} has it, then close this PR on GitHub.`,
      'hidden', 'enabled')
  }

  if (status === 'reengaged') {
    return base('sent-back-now', 'blocked', 'Not merged: sent back for rework',
      `${errorMessage || 'The merge gate rejected it.'} The ticket will be rebuilt and this PR updated.`, 'hidden', 'hidden')
  }

  // What the post-merge rebase found (#225): {state: clean | conflict | tests_failed | error, after, files}.
  const rb = pr.rebase || null

  if (pr.conflicts) {
    const since = rb?.state === 'conflict' && rb.files?.length ? `Since #${rb.after} merged it conflicts in ${rb.files.join(', ')}. ` : ''
    return base('conflict', 'blocked', `Conflicts with ${main}`,
      `${since}It can't merge as it is. The hourly scan first tries to resolve it automatically (when both sides only added lines); a real conflict sends a pipeline PR's ticket back to be rebuilt on the current ${main}, and flags a hand-made PR for you.`, 'hidden', 'hidden')
  }

  if (ci.state === 'failing') {
    return base('checks-failed', 'blocked', 'GitHub checks failed',
      `${ci.failing.join(', ')}. It is sent back for rework automatically, so there is nothing to approve.`, 'hidden', 'hidden')
  }

  // The owner's hard rule (marvin #374): a change to how the app looks is approved only with images to look at.
  if (pr.needsImages) {
    const files = pr.needsImages.files || []
    const shown = files.slice(0, 3).join(', ') + (files.length > 3 ? ` and ${files.length - 3} more` : '')
    return base('needs-images', 'blocked', 'Needs images',
      `It changes how the app looks${shown ? ` (${shown})` : ''} but its description shows no screenshots. ` +
        'Add images of the changed screens to the PR, and Approve appears here.', 'hidden', 'enabled')
  }

  if (pr.baseProblem?.parent) {
    // Stacked on another open PR: it waits for that one, and is moved onto main automatically when it merges.
    const b = pr.baseProblem
    const parent = `#${b.parent.number}${b.parent.title ? ` ${b.parent.title}` : ''}`
    return base('stacked', 'wait', `Stacked on ${parent}`,
      `It builds on ${parent}. Approve that one first: when it merges, this PR is moved onto ${b.expected} automatically, ` +
        `rebased and retested, and Approve becomes available here. Until then merging it would not put the work on ${b.expected}.`,
      'disabled', 'enabled')
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

  if (status === 'error' && /^GITHUB_OUTAGE\b/.test(errorMessage || '')) {
    return base('github-outage', 'wait', 'GitHub is having an outage',
      'The last merge attempt hit a GitHub server error (githubstatus.com). Nothing is wrong with this PR and it was not sent back. Approve again once GitHub recovers.', 'enabled', 'enabled')
  }

  if (status === 'error' && errorMessage && !MIRRORED_REFUSALS.test(errorMessage)) {
    return base('error', 'blocked', 'The last merge attempt failed', errorMessage, 'enabled', 'enabled')
  }

  if (rb?.state === 'tests_failed') {
    return base('tests-after-rebase', 'wait', 'Tests fail on the latest main',
      `After #${rb.after} merged, this PR's tests fail once it is rebased onto ${main}. Approve runs them again and sends it back if they still fail.`, 'enabled', 'enabled')
  }

  // Auto-merge's shadow verdict (ADR 0064, #341): what it WOULD do, shown while Gil keeps approving.
  const am = pr.autoMerge
  const amNote = !am ? null : am.verdict === 'auto'
    ? `Auto-merge (shadow): would merge${am.score != null ? ` (tests caught ${am.score}% of planted bugs)` : ''}`
    : `Auto-merge (shadow): would wait for you: ${(am.reasons || [])[0] || 'see the rules'}`
  const notes = [ci.state === 'passing' ? 'GitHub checks passed' : null, rb?.state === 'clean' ? `still merges cleanly onto ${main} after #${rb.after} merged` : null, amNote].filter(Boolean)
  return base('ready', 'ready', 'Ready to merge', null, 'enabled', 'enabled', { note: notes.length ? notes.join(' · ') : null })
}
