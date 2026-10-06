// What a comment from the owner does to a ticket. Shared by the dashboard (to say what will happen before you send)
// and by the main process (to do it), so the two can never disagree.
//
// The agent already reads a ticket's comments before it plans (sandbox_orchestration), so the comment itself is the
// answer. What this adds is the missing second half: a ticket that was WAITING (needs-info, or parked after repeated
// failures) is put back in the queue, otherwise nothing would ever look at the answer.

export const HUMAN_INPUT_MARKER = '<!-- marvin:human-input -->'

const claims = (labels) => labels.filter((l) => l.startsWith('claimed:'))

export function planInput(labels, state = 'OPEN') {
  const none = { requeue: false, add: [], remove: [] }
  const has = (l) => labels.includes(l)
  if (state && state !== 'OPEN') return { ...none, effect: 'This ticket is closed: your comment is posted, nothing is queued.' }
  if (has('needs-reengagement')) {
    return { ...none, effect: 'This ticket is already queued to be rebuilt; the agent will read your comment when it does.' }
  }
  if (has('ready-for-human') || has('wontfix')) {
    return { ...none, effect: 'This one stays with you (it is marked for a person, not the agent): your comment is posted, nothing is queued.' }
  }
  if (has('needs-info')) {
    return { requeue: true, add: ['ready-for-agent'], remove: ['needs-info', ...claims(labels)], effect: 'It was waiting on you: sending this puts it back to ready, and the agent will read your answer.' }
  }
  if (claims(labels).length > 0 && !has('ready-for-agent')) {
    return { requeue: true, add: ['ready-for-agent'], remove: claims(labels), effect: 'The pipeline had parked it after repeated failures: sending this puts it back to ready, with your comment as the new context.' }
  }
  return { ...none, effect: 'Your comment is posted; the agent reads the comments when it picks this ticket up.' }
}
