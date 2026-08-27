// Reads open PRs and identifies which were raised by the MR pipeline
// (mr_raiser.py, G-Eskayo/marvin#4) rather than a live/manual session, by
// matching the exact marker string _default_open_pr() always writes into
// the body. Parses the attached metrics-comparison table back out for
// display. Approving fires a webhook per the documented contract (see
// dashboard/webhook-server/README.md) rather than running `gh pr merge`
// itself -- G-Eskayo/marvin#11 is explicit that the dashboard is a
// trigger, not the thing that does the merge.
const PIPELINE_MARKER = 'Autonomously implemented and verified by the MR pipeline'

export function isPipelinePr(body) {
  return typeof body === 'string' && body.includes(PIPELINE_MARKER)
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
