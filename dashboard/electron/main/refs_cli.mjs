// extractRefs for callers that aren't JavaScript (lib/resume_check.py, marvin#1221), so there is one parser.
// stdin: {texts: [string], repos: {shortName: 'owner/repo'}, defaultRepo: 'owner/repo'}
// stdout: {refs: [[{repo, number}]]}, one list per text, bare refs given defaultRepo, de-duplicated in order.
// Not JSON in: exit 2. The same pattern as webhook-server/decisions_cli.js for lib/decisions_check.py.
import { extractRefs } from './relations.js'

let raw = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (chunk) => { raw += chunk })
process.stdin.on('end', () => {
  let input
  try {
    input = JSON.parse(raw)
  } catch (e) {
    process.stderr.write(`refs_cli: input is not JSON (${e.message})\n`)
    process.exit(2)
  }
  const repos = input.repos && typeof input.repos === 'object' ? input.repos : {}
  const refs = (Array.isArray(input.texts) ? input.texts : []).map((text) => {
    const seen = new Set()
    const out = []
    for (const t of extractRefs(String(text ?? ''), { repos, words: true }).tickets) {
      const repo = t.repo || input.defaultRepo || null
      const key = `${String(repo).toLowerCase()}#${t.number}`
      if (!repo || seen.has(key)) continue
      seen.add(key)
      out.push({ repo, number: t.number })
    }
    return out
  })
  process.stdout.write(JSON.stringify({ refs }) + '\n')
})
