// Determines whether a dispatch task string is about a specific ticket, using the repo and number as the key.
// This is shared by activity.js (which uses it to match dispatch tasks to tickets) and mr_review.js
// (which uses it to determine isLiveNow for PR cards), avoiding circular imports.

const MARVIN_REPO = 'G-Eskayo/marvin'

// The dispatch label is `ticket #N: ...` for marvin and `ticket <owner/repo>#N: ...` for any other project, so a
// bare "#13" appears in both. Match the right form, and not "#130" when asked about #13.
export function taskIsTicket(task, repo, number) {
  if (!task) return false
  const n = String(number)
  const form = repo === MARVIN_REPO ? `ticket #${n}` : `${repo}#${n}`
  const at = task.indexOf(form)
  if (at < 0) return false
  return !/\d/.test(task.charAt(at + form.length))
}
