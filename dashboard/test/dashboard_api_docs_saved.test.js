// The phone's Docs backend (mobile-backend/dashboard_api.js) obeys the desktop rule (#565): a GitHub-only project is
// served from the saved copy, a click never calls GitHub, and opening a project's tree is one conditional request.
import { describe, it, expect } from 'vitest'
import { createServer, request } from 'http'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createDashboardApiRouter } from '../mobile-backend/dashboard_api.js'
import { gitBlobSha } from '../electron/main/docs_saved.js'

const get = (base, p) => new Promise((resolve, reject) => {
  request(`${base}${p}`, (res) => {
    let body = ''
    res.on('data', (c) => (body += c))
    res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(body) }))
  }).on('error', reject).end()
})
const flush = () => new Promise((r) => setTimeout(r, 30))

describe('phone Docs backend: saved copy, zero calls per click', () => {
  it('tree and content never call gh; each tree request (an open) is one conditional request, then a 304', async () => {
    const root = mkdtempSync(path.join(tmpdir(), 'phone-docs-'))
    const files = { 'README.md': '# pd\n', 'docs/adr/0001-a.md': '# 1. A\n' }
    const calls = { probe: 0, exec: 0 }
    try {
      const catalogDir = path.join(root, 'catalog')
      mkdirSync(catalogDir, { recursive: true })
      writeFileSync(path.join(catalogDir, 'projects.dev.json'), JSON.stringify({ generated_at: '2026-10-21T00:00:00Z', projects: [{ id: 'pd', name: 'pd', kind: 'repo', repo: 'G-Eskayo/pd', status: 'active', localPaths: [], docs: { context: false, readme: true, adrCount: 1 }, summary_md: '# pd\n' }] }))
      const router = createDashboardApiRouter({
        stagesDir: path.join(root, 's'), dispatchStatePath: path.join(root, 'd.json'), healthStatusPath: path.join(root, 'h.json'),
        registryPath: path.join(root, 'r.json'), catalogDir, masterDocPath: path.join(root, 'm.md'), deviceId: 'dev',
        savedDocsDir: path.join(root, 'saved'),
        probe: async (_repo, etag) => (calls.probe++, etag === 'e1' ? { status: 304, etag } : { status: 200, etag: 'e1', body: { tree: Object.entries(files).map(([p, t]) => ({ path: p, type: 'blob', sha: gitBlobSha(t) })) } }),
        exec: async (_c, args) => {
          calls.exec++
          const p = args.find((a) => a.startsWith('repos/')).split('/contents/')[1]
          return { stdout: Buffer.from(files[p]).toString('base64') }
        }
      })
      const server = createServer(async (req, res) => (await router(req, res)) || res.writeHead(404).end())
      await new Promise((r) => server.listen(0, '127.0.0.1', r))
      const base = `http://127.0.0.1:${server.address().port}`
      try {
        // First open: answered at once from what the catalog knows; the check fills the copy behind it.
        expect((await get(base, '/docs/tree?id=pd')).body.ok).toBe(true)
        await flush()
        expect(calls.probe).toBe(1)
        const filled = calls.exec
        // Clicks: tree and content, ten rounds, no gh call.
        for (let i = 0; i < 10; i++) expect((await get(base, '/docs/content?id=pd&path=docs/adr/0001-a.md')).body.data).toBe('# 1. A\n')
        expect(calls.exec).toBe(filled)
        // Re-open: one more conditional request, a 304, no download.
        const t = await get(base, '/docs/tree?id=pd')
        expect(t.body.data.tree.map((e) => e.path || e.section)).toContain('docs/adr/')
        await flush()
        expect(calls.probe).toBe(2)
        expect(calls.exec).toBe(filled)
        expect((await get(base, '/docs/revalidate?id=pd')).body.data.status).toBe('unchanged')
        expect((await get(base, '/docs/revalidate')).status).toBe(400)
      } finally {
        server.close()
      }
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})
