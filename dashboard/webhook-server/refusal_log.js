import { execFile } from 'child_process'
import { promisify } from 'util'
import { appendFileSync, mkdirSync } from 'fs'
import path from 'path'
import os from 'os'
import { parseTicketRef } from '../electron/main/mr_review.js'
import { repoFromPrUrl } from '../electron/main/mr_repos.js'
import { recordStage } from './ticket_stages.js'

// Every refused merge, wherever it was refused, is recorded with its PR, project, ticket, stage and time (#215).
// PR #209 sat unmergeable for hours on 2026-10-07 and nothing said why: the dashboard kept its refusal in memory
// and the webhook's error line had no PR URL or time.
//
// A refusal is the review screen doing its job (wrong order, wrong base, sent back, CI still running), not a broken
// environment, so it is written as kind "refusal": lib/failure_breaker.py counts only kind "failure", and three
// order refusals in two hours must not pause the pipeline. Same file and line shape as failure_log.js.
// Fail-soft: recording must never break or mask the refusal being recorded.

export const REFUSAL_CODES = new Set(['OUT_OF_ORDER', 'WRONG_BASE', 'SENT_BACK', 'CI_PENDING', 'NO_MERGE_PROFILE', 'MERGE_REFUSED'])

const defaultFile = () => path.join(os.homedir(), '.claude', 'logs', 'pipeline-failures.jsonl')

function defaultAppend(file, line) {
  mkdirSync(path.dirname(file), { recursive: true })
  appendFileSync(file, line)
}

export function recordRefusal({ prUrl, ticket = null, code, message, stage }, {
  append = defaultAppend, recordStageFn = recordStage, now = () => new Date(), file = defaultFile(), writeStage = true
} = {}) {
  const project = repoFromPrUrl(prUrl)
  const reason = `${code}: ${message}`.slice(0, 300)
  try {
    append(file, JSON.stringify({ t: now().toISOString(), kind: 'refusal', ticket, project, pr_url: prUrl, sig: `merge:${code}`, stage, reason }) + '\n')
  } catch { /* fail-soft */ }
  if (writeStage && ticket !== null) {
    try {
      recordStageFn(ticket, 'merging', 'failed', `refused ${reason}`, { repo: project })
    } catch { /* fail-soft */ }
  }
}

async function ticketOfPr(prUrl, exec) {
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'body'])
    const ref = parseTicketRef(JSON.parse(stdout).body || '')
    return ref === null ? null : Number(ref)
  } catch {
    return null
  }
}

// The webhook's /approve error path. Real failures were already recorded inside mergePr (as kind "failure"); this
// adds the refusals. Those refused at the request stage happened before mergePr knew the ticket, so it is looked up
// here, and they get their stage-log entry here too (MERGE_REFUSED already has one).
export async function recordApproveError(prUrl, payload, { exec = promisify(execFile), ...deps } = {}) {
  if (!REFUSAL_CODES.has(payload.code)) return
  const ticket = await ticketOfPr(prUrl, exec)
  recordRefusal({ prUrl, ticket, code: payload.code, message: payload.message, stage: payload.stage },
    { ...deps, writeStage: payload.stage === 'request' })
}

export function approveErrorLine(prUrl, body, now = () => new Date()) {
  return `${now().toISOString()} approve failed: ${prUrl} ${body.error}`
}
