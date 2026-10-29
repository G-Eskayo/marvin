// Reads the real open PRs the way MR Review does (every board repo, mr_review.js listPipelinePrs), plus the two fields
// grouping needs that the list doesn't fetch yet (labels, isDraft), the project catalog (names after overrides.json)
// and the live helper tabs (marvin#753). Writes data.local.js next to this file: NOT committed, it holds private
// repos' PR titles and this is a public repo.
//
//   node docs/design/mr-review-by-project-758/snapshot.mjs
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync, statSync, writeFileSync, existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { listPipelinePrs } from '../../../dashboard/electron/main/mr_review.js'
import { prListArgs } from '../../../dashboard/electron/main/mr_repos.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const GH = join(homedir(), '.agents', 'bin', 'gh')
const json = (p) => JSON.parse(readFileSync(p, 'utf-8'))

const registry = json(join(homedir(), '.claude', 'boards', 'registry.json')).boards.map((b) => b.repo)
const catDir = join(homedir(), '.claude', 'catalog')
const catFile = readdirSync(catDir).filter((f) => /^projects\..+\.json$/.test(f)).map((f) => join(catDir, f)).sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)[0]
const overrides = existsSync(join(catDir, 'overrides.json')) ? json(join(catDir, 'overrides.json')) : {}
const projects = json(catFile).projects.map((p) => ({ id: p.id, name: overrides[p.id]?.name || p.name, repo: p.repo || null, status: overrides[p.id]?.status || p.status }))

const raw = []
const errors = []
for (const repo of registry) {
  const args = prListArgs(repo)
  args[args.length - 1] += ',labels,isDraft'
  try {
    for (const pr of JSON.parse(execFileSync(GH, args, { encoding: 'utf-8', maxBuffer: 64 << 20 }))) raw.push({ ...pr, repo })
  } catch (e) {
    errors.push({ repo, message: String(e.message).slice(0, 200) })
  }
}
const cards = await listPipelinePrs(async () => raw)
const extra = new Map(raw.map((p) => [`${p.repo}#${p.number}`, { labels: (p.labels || []).map((l) => l.name), isDraft: !!p.isDraft }]))
const prs = cards.map((c) => ({ ...c, ...extra.get(c.key), rawBody: null, evidence: null, images: undefined }))

let tabs = null
try {
  const list = JSON.parse(execFileSync('/opt/homebrew/bin/wezterm', ['cli', '--no-auto-start', 'list', '--format', 'json'], { encoding: 'utf-8' }))
  const marks = { '●': 'running', '✓': 'done', '✗': 'failed' }
  tabs = [...new Set(list.map((p) => p.tab_title))].map((t) => {
    const m = /^([●✓✗]) (.+?) · (.+)$/.exec(t || '')
    return m ? { state: marks[m[1]], group: m[2], title: m[3] } : null
  }).filter(Boolean)
} catch { tabs = null }

const data = { takenAt: new Date().toISOString(), projects, prs, errors, tabs }
writeFileSync(join(HERE, 'data.local.js'), `window.SNAPSHOT = ${JSON.stringify(data)}\n`)
console.log(`${prs.length} open PRs from ${registry.length} repos (${errors.length} failed), ${projects.length} projects, ${tabs ? tabs.length : 'no'} helper tabs`)
