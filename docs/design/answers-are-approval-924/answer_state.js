// MR Review: answers are the approval (marvin#924). Mock-up logic only, no DOM: which one button a PR's Decisions card
// offers, decided from the answers. The page (index.html) and the tests (dashboard/test/answers_are_approval_proto.test.js)
// both call answerState(), so what you click in the mock-up is exactly what is tested.
//
// A classic script, not a module, so the mock-up opens straight from Finder (file://). It sets globalThis.AnswerState.
//
// Input (all plain data):
//   decisions: [{ id, question, kind: 'single'|'pick-one'|'multi'|'pick-any'|'text', required,
//                 options: [{ label, built }] }]        built = the "(built here)" marker on that option
//   picks:     { [id]: string[] }   what is selected now. Missing = untouched, so the built option shows pre-selected.
//                                   An empty array = deliberately cleared. For a text question: { [id]: 'typed answer' }.
//   notes:     { [id]: string }     the note box under each question
//   plan:      true for a mock-up or plan PR (nothing to merge)
//   status:    'idle' | 'sending' | 'merge-failed'   (pressing twice, and a merge that fails after the answers saved)
//   failure:   why the merge failed, shown when status is 'merge-failed'
//
// Output: { label, action: 'merge'|'send-back'|'send'|'disabled'|'two-step', reason, missing, picks, unsent, busy }
//   picks:  the answer for every question as the screen shows it (untouched ones = what's built)
//   unsent: ids whose selection is only the built default, shown as "not yet sent"
;(function (root) {
  'use strict'

  const KIND = { single: 'single', 'pick-one': 'single', multi: 'multi', 'pick-any': 'multi', text: 'text' }
  const kindOf = (q) => KIND[q.kind] || 'single'
  const filled = (s) => typeof s === 'string' && s.trim().length > 0
  const builtOf = (q) => (q.options || []).filter((o) => o.built).map((o) => o.label)
  const sameSet = (a, b) => a.length === b.length && [...a].sort().join('\u0000') === [...b].sort().join('\u0000')
  const quote = (s) => `“${s}”`
  const list = (xs) => xs.map(quote).join(', ')

  function answered(q, pick) {
    const k = kindOf(q)
    if (k === 'text') return filled(pick)
    const n = (pick || []).length
    return k === 'single' ? n === 1 : n >= 1
  }

  // What the screen shows for each question: an untouched choice question starts on what's built.
  function effectivePicks(decisions, picks) {
    const out = {}
    const unsent = []
    for (const q of decisions) {
      const own = picks ? picks[q.id] : undefined
      if (kindOf(q) === 'text') { out[q.id] = typeof own === 'string' ? own : ''; continue }
      if (Array.isArray(own)) {
        const labels = new Set((q.options || []).map((o) => o.label))
        out[q.id] = [...new Set(own)].filter((l) => labels.has(l)) // a label not on the list is not an answer
      } else {
        out[q.id] = builtOf(q)
        if (out[q.id].length) unsent.push(q.id)
      }
    }
    return { out, unsent }
  }

  function answerState({ decisions = [], picks = {}, notes = {}, plan = false, status = 'idle', failure = null } = {}) {
    const qs = Array.isArray(decisions) ? decisions : []
    const done = (action, label, reason, extra = {}) => ({ action, label, reason, missing: [], picks: {}, unsent: [], busy: false, ...extra })

    if (!qs.length) return done('two-step', 'Approve & merge', 'This PR asks no decisions.')

    // A pick-one question can't have two built answers: the format is broken, so nothing merges in one press.
    const broken = qs.find((q) => kindOf(q) === 'single' && builtOf(q).length > 1)
    const anyBuilt = qs.some((q) => builtOf(q).length > 0)
    // Old format: a code PR that marks nothing as built. Today's two steps.
    if (!plan && (!anyBuilt || broken)) {
      return done('two-step', 'Submit decisions',
        broken
          ? `${quote(broken.question)} marks more than one answer as built, so answers and merging stay two steps.`
          : 'This PR doesn’t say what was built, so answers and merging stay two steps: submit, then Approve & merge.')
    }

    // A plan has nothing built, so nothing is pre-selected: only what was picked counts.
    const asked = plan ? qs.map((q) => ({ ...q, options: (q.options || []).map((o) => ({ ...o, built: false })) })) : qs
    const eff = effectivePicks(asked, picks)
    const shown = eff.out
    const base = { picks: shown, unsent: eff.unsent }

    const missing = qs.filter((q) => q.required && !answered(q, shown[q.id]))
    if (missing.length) {
      const n = missing.length
      return done('disabled', `Answer ${n} more`,
        n === 1 ? `${quote(missing[0].question)} needs an answer.` : `Still to answer: ${list(missing.map((q) => q.question))}.`,
        { ...base, missing: missing.map((q) => q.id) })
    }

    let result
    if (plan) {
      result = done('send', 'Send answers', 'A mock-up or plan: your answers go to MARVIN, and nothing merges.', base)
    } else {
      const noted = qs.find((q) => filled(notes ? notes[q.id] : ''))
      const written = qs.find((q) => kindOf(q) === 'text' && filled(shown[q.id]))
      // A choice that differs from what's built. An empty optional answer is no answer, so it changes nothing.
      const differs = qs.find((q) => kindOf(q) !== 'text' && (shown[q.id] || []).length > 0 && !sameSet(shown[q.id], builtOf(q)))
      if (differs) {
        const built = builtOf(differs)
        result = done('send-back', 'Send back with answers',
          built.length
            ? `You picked ${list(shown[differs.id])} for ${quote(differs.question)}; what’s built is ${list(built)}. MARVIN rebuilds it.`
            : `Nothing is built for ${quote(differs.question)} yet, so MARVIN builds your answer first.`, base)
      } else if (noted) {
        result = done('send-back', 'Send back with answers', `You wrote a note on ${quote(noted.question)}, so MARVIN reads it and rebuilds first.`, base)
      } else if (written) {
        result = done('send-back', 'Send back with answers', `You wrote an answer to ${quote(written.question)}, so MARVIN acts on it first.`, base)
      } else {
        result = done('merge', 'Merge with these answers', 'Every answer matches what’s built.', base)
      }
    }

    // Pressing twice: while it is sending, the button is busy and a second press does nothing.
    if (status === 'sending') {
      return { ...result, busy: true, label: result.action === 'merge' ? 'Merging…' : 'Sending…' }
    }
    // The answers saved but the merge failed: the answers stay, the failure shows, and the button retries the merge only.
    if (status === 'merge-failed' && result.action === 'merge') {
      return { ...result, label: 'Try the merge again', unsent: [], reason: `Your answers are saved. The merge failed: ${failure || 'no reason given'}.` }
    }
    return result
  }

  // One press, once: the page calls this before acting. A press while busy, disabled or done is ignored.
  function canPress(state) {
    return !!state && !state.busy && state.action !== 'disabled'
  }

  root.AnswerState = { answerState, canPress, answered, kindOf }
})(typeof globalThis !== 'undefined' ? globalThis : window)
