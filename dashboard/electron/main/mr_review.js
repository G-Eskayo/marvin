// Reads open PRs and identifies which were raised by ticket-driven work
// rather than a genuinely manual/human-opened PR (like this dashboard's
// own). Two ways a PR qualifies: the exact marker string
// _default_open_pr() (mr_raiser.py, G-Eskayo/marvin#4) always writes into
// the body, or BOTH a "Closes/Fixes/Resolves #N" reference AND a
// "## Test plan" section together -- the shape a ticket-dispatched
// session's own `gh pr create` naturally produces (this repo's own PR
// template), before ticket_pipeline.py is rewired to go through
// mr_raiser.py (G-Eskayo/marvin#95). Deliberately requires both, not
// either alone -- a bare "Closes #N" is not a safe signal by itself (a
// genuinely manual PR can reference an issue without being ticket-driven
// work), which is exactly why this checks for the pairing rather than
// loosening to a single keyword. Interim widening; the real, full
// schema-detection check (evidence sections, not just a shape match) is
// G-Eskayo/marvin#75 -- this only gets a ticket-linked PR to actually show
// up in the meantime, not the richer evidence parsing #75 will add.
// Parses the attached metrics-comparison table back out for display, when
// present. Approving fires a webhook per the documented contract (see
// dashboard/webhook-server/README.md) rather than running `gh pr merge`
// itself -- G-Eskayo/marvin#11 is explicit that the dashboard is a
// trigger, not the thing that does the merge.
const PIPELINE_MARKER = 'Autonomously implemented and verified by the MR pipeline'
const CLOSES_ISSUE_RE = /\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+/i
const TEST_PLAN_RE = /^##\s*test plan/im

export function isPipelinePr(body) {
  if (typeof body !== 'string') return false
  if (body.includes(PIPELINE_MARKER)) return true
  return CLOSES_ISSUE_RE.test(body) && TEST_PLAN_RE.test(body)
}

export function parseMetricsEvidence(body) {
  const subsystemMatch = body.match(/\*\*Subsystem\*\*:\s*(.+)/)
  const verdictMatch = body.match(/\*\*Verdict\*\*:\s*(.+)/)

  const lines = body.split('\n')
  const headerIndex = lines.findIndex((line) => /^\|\s*Metric\s*\|/.test(line.trim()))
  const rows = []
  if (headerIndex !== -1) {
    // headerIndex + 1 is the "|---|---|..." separator row -- skip it too.
    for (let i = headerIndex + 2; i < lines.length; i++) {
      const line = lines[i].trim()
      if (!line.startsWith('|')) break
      const cells = line
        .split('|')
        .slice(1, -1)
        .map((c) => c.trim())
      if (cells.length === 5) {
        const [name, baseline, current, delta, direction] = cells
        rows.push({ name, baseline, current, delta, direction })
      }
    }
  }

  return {
    subsystem: subsystemMatch ? subsystemMatch[1].trim() : null,
    verdict: verdictMatch ? verdictMatch[1].trim() : null,
    metrics: rows
  }
}

export async function listPipelinePrs(listOpenPrs) {
  const prs = await listOpenPrs()
  return prs
    .filter((pr) => isPipelinePr(pr.body))
    .map((pr) => ({
      number: pr.number,
      title: pr.title,
      url: pr.url,
      evidence: parseMetricsEvidence(pr.body)
    }))
}

export async function approveMr(prUrl, webhookUrl, post) {
  const response = await post(webhookUrl, { pr_url: prUrl })
  if (!response.ok) {
    throw new Error(`Webhook call failed: ${response.status}`)
  }
  return response
}
