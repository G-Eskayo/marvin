import { existsSync, readFileSync, readdirSync } from 'fs'
import path from 'path'

// The Docs tab's click handlers (#570), in one table so index.js registers exactly these and a test can drive them the
// way clicks do and count every network call (test/docs_clicks_network.test.js). Owner acceptance criterion
// (2026-10-21): zero network calls on any click. Every handler here reads local files, the saved copy (docs_saved.js),
// the outbox match map (deliverables.js) or memory. The one request a GitHub-only project makes, docs:revalidate, is
// sent once when the project is opened and is registered separately.
export function docsClickHandlers({ docsService, docsIndexer, outbox }) {
  return {
    'docs:repos': () => docsService.repos(),
    'docs:tree': (id) => docsService.tree(String(id)),
    'docs:content': (id, filePath) => docsService.content(String(id), String(filePath)),
    'docs:headings': (id, paths) => docsService.headings(String(id), paths),
    'docs:search': (query, opts) => docsIndexer.search(String(query || ''), opts),
    'outbox:list': (relPath) => outbox.list(String(relPath || '')),
    'outbox:summary': (relPath) => outbox.summary(String(relPath)),
    'outbox:preview': (relPath) => outbox.preview(String(relPath)),
    'outbox:content': (relPath) => outbox.content(relPath),
    'outbox:image': (fromRel, src) => outbox.image(fromRel, src),
    'outbox:thumb': (relPath) => outbox.thumb(String(relPath))
  }
}

// The docs-phrase tier's text per project: CONTEXT.md, README.md and docs/adr/*.md, lowercased (the files the design's
// measurement read). From the local clone when there is one, else the saved copy of its GitHub docs. Never the network.
export function docsTextFor(projects, { saved = null } = {}) {
  const out = {}
  for (const p of projects || []) {
    const dir = (p.localPaths || []).find((d) => existsSync(d))
    if (dir) {
      let adrs = []
      try {
        adrs = readdirSync(path.join(dir, 'docs', 'adr')).filter((f) => f.endsWith('.md')).map((f) => `docs/adr/${f}`)
      } catch {
        adrs = []
      }
      const parts = []
      for (const f of ['CONTEXT.md', 'README.md', ...adrs]) {
        try {
          parts.push(readFileSync(path.join(dir, f), 'utf8').toLowerCase())
        } catch {
          // missing file: the rest still counts
        }
      }
      if (parts.length) out[p.id] = parts.join('\n')
      continue
    }
    const copy = p.repo && saved ? saved.peek(p.repo) : null
    if (!copy?.files) continue
    const texts = Object.entries(copy.files).filter(([f]) => f === 'CONTEXT.md' || f === 'README.md' || /^docs\/adr\/[^/]+\.md$/.test(f)).map(([, t]) => String(t).toLowerCase())
    if (texts.length) out[p.id] = texts.join('\n')
  }
  return out
}

// The highest ticket/PR number each board repo has, from the board data github_state already holds (peek: memory only).
// The number tier treats a repo as having #n when n is at most this, like the measurement's PR ranges.
export function maxNumbers(peeked) {
  const out = {}
  for (const { repo, value } of peeked || []) {
    const nums = [...(value?.issues || []), ...(value?.prs || [])].map((x) => Number(x?.number)).filter((n) => Number.isInteger(n) && n > 0)
    if (nums.length) out[repo] = Math.max(...nums)
  }
  return out
}
