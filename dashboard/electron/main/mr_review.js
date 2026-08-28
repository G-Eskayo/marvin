// Reads open PRs and identifies which follow the MR pipeline's evidence
// schema (G-Eskayo/marvin#72, ADR 0024) -- one fixed, structured PR body
// format that every MR-pipeline PR uses whether it was raised
// autonomously (mr_raiser.py, G-Eskayo/marvin#4) or by a live/manual
// session. Detection is schema-based (are the section headers present),
// not the old exact-marker-string match, so manually-raised PRs that
// follow the schema are treated the same as pipeline-raised ones. Parses
// the metrics-comparison, test-results, and dev-environment-evidence
// sections back out for display, plus the linked ticket reference.
// Approving fires a webhook per the documented contract (see
// dashboard/webhook-server/README.md) rather than running `gh pr merge`
// itself -- G-Eskayo/marvin#11 is explicit that the dashboard is a
// trigger, not the thing that does the merge.
export const EVIDENCE_HEADERS = {
  metrics: '## Metrics Comparison',
  testResults: '## Test Results',
  devEvidence: '## Dev Environment Evidence'
}

export function hasEvidenceSchema(body) {
  return (
    typeof body === 'string' &&
    body.includes(EVIDENCE_HEADERS.metrics) &&
    body.includes(EVIDENCE_HEADERS.testResults) &&
    body.includes(EVIDENCE_HEADERS.devEvidence)
  )
}

// Returns the section's own body text (everything after its "## " header
// up to the next "## " header or end of string), or '' if the header
// isn't present.
function extractSection(body, header) {
  const start = body.indexOf(header)
  if (start === -1) return ''
  const afterHeader = start + header.length
  const nextHeaderMatch = body.slice(afterHeader).match(/\n##\s/)
  const end = nextHeaderMatch ? afterHeader + nextHeaderMatch.index : body.length
  return body.slice(afterHeader, end).trim()
}

function parseMetricsSection(section) {
  const subsystemMatch = section.match(/\*\*Subsystem\*\*:\s*(.+)/)
  const verdictMatch = section.match(/\*\*Verdict\*\*:\s*(.+)/)

  const lines = section.split('\n')
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

function parseTestResultsSection(section) {
  if (!section) return null
  const suiteMatch = section.match(/\*\*Suite\*\*:\s*(.+)/)
  const passedMatch = section.match(/\*\*Passed\*\*:\s*(\d+)/)
  const failedMatch = section.match(/\*\*Failed\*\*:\s*(\d+)/)
  const totalMatch = section.match(/\*\*Total\*\*:\s*(\d+)/)
  if (!suiteMatch && !passedMatch && !failedMatch && !totalMatch) return null

  return {
    suite: suiteMatch ? suiteMatch[1].trim() : null,
    passed: passedMatch ? Number(passedMatch[1]) : null,
    failed: failedMatch ? Number(failedMatch[1]) : null,
    total: totalMatch ? Number(totalMatch[1]) : null
  }
}

function parseDevEvidenceSection(section) {
  if (!section) return null
  if (/^N\/A/i.test(section)) {
    return { na: true, reason: section.replace(/^N\/A\s*[—-]?\s*/i, '').trim() || null }
  }

  const imageMatch = section.match(/!\[[^\]]*\]\(([^)]+)\)/)
  const description = section.replace(/!\[[^\]]*\]\([^)]+\)/, '').trim()
  return {
    na: false,
    screenshot: imageMatch ? imageMatch[1].trim() : null,
    description: description || null
  }
}

export function parseTicketRef(body) {
  const match = body.match(/\b(?:Closes|Fixes|Resolves)\s+(?:[\w.-]+\/[\w.-]+)?#(\d+)/i)
  return match ? match[1] : null
}

export function parseEvidence(body) {
  const metrics = parseMetricsSection(extractSection(body, EVIDENCE_HEADERS.metrics))
  return {
    ...metrics,
    testResults: parseTestResultsSection(extractSection(body, EVIDENCE_HEADERS.testResults)),
    devEvidence: parseDevEvidenceSection(extractSection(body, EVIDENCE_HEADERS.devEvidence)),
    ticketRef: parseTicketRef(body)
  }
}

export async function listPipelinePrs(listOpenPrs) {
  const prs = await listOpenPrs()
  return prs
    .filter((pr) => hasEvidenceSchema(pr.body))
    .map((pr) => ({
      number: pr.number,
      title: pr.title,
      url: pr.url,
      evidence: parseEvidence(pr.body)
    }))
}

export async function approveMr(prUrl, webhookUrl, post) {
  const response = await post(webhookUrl, { pr_url: prUrl })
  if (!response.ok) {
    throw new Error(`Webhook call failed: ${response.status}`)
  }
  return response
}
