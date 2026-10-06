import { promisify } from 'util'
import { execFile } from 'child_process'
import { planInput, HUMAN_INPUT_MARKER } from '../../src/lib/ticket_input.js'

const execFileAsync = promisify(execFile)
const OWNER = 'G-Eskayo'

// Leave the owner's comment on a ticket and, if the ticket was waiting on it, put the ticket back in the queue.
// The comment goes first: if the label change fails the answer is still on the ticket, and the result says so.
export async function postTicketInput({ repo, number, body }, exec = execFileAsync) {
  if (typeof repo !== 'string' || !repo.startsWith(`${OWNER}/`) || repo.split('/').length !== 2) throw new Error(`Not a ${OWNER} repo: ${repo}`)
  if (!Number.isInteger(Number(number)) || Number(number) <= 0) throw new Error(`Not a ticket number: ${number}`)
  const text = String(body ?? '').trim()
  if (!text) throw new Error('The comment is empty')
  const n = String(Number(number))

  const view = JSON.parse((await exec('gh', ['issue', 'view', n, '--repo', repo, '--json', 'labels,state'])).stdout)
  const plan = planInput((view.labels || []).map((l) => l.name), view.state)

  await exec('gh', ['issue', 'comment', n, '--repo', repo, '--body', `**Reply from the owner:**\n\n${text}\n\n${HUMAN_INPUT_MARKER}`])
  if (!plan.requeue) return { posted: true, requeued: false, effect: plan.effect }

  try {
    const args = ['issue', 'edit', n, '--repo', repo]
    for (const l of plan.add) args.push('--add-label', l)
    for (const l of plan.remove) args.push('--remove-label', l)
    await exec('gh', args)
  } catch {
    return { posted: true, requeued: false, effect: plan.effect, warning: 'Your comment is posted, but the ticket could not be moved back to ready (the label change failed). Try again, or move it by hand.' }
  }
  return { posted: true, requeued: true, effect: plan.effect }
}
