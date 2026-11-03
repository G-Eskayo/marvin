// The decisions parser for callers that aren't JavaScript (bin/gh, through lib/decisions_check.py; rule I2, marvin#742):
// a body on stdin, {present, problems, heading, asBuilt} on stdout (asBuilt: lib/owner_decisions.py, marvin#231). A thin wrapper, so there is one parser.
import { parseDecisions, askingHeading, answersAsBuilt } from './decisions.js'

let body = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (chunk) => { body += chunk })
process.stdin.on('end', () => {
  const { present, problems } = parseDecisions(body)
  process.stdout.write(JSON.stringify({ present, problems, heading: askingHeading(body), asBuilt: answersAsBuilt(body) }) + '\n')
})
