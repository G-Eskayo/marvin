import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createPortfolio, slugOf } from '../electron/main/portfolio.js'

// The Portfolio tab's backend: the single hub for how a portfolio Project Page is built --
// component library, design rules, guide, evaluation, images. Dev-only by construction: it can
// only write inside <project>/templates/ and never touches deploy/ (a push touching deploy/
// auto-deploys to PRODUCTION).

let dir, project, home, p, exec
const write = (rel, text) => { const f = path.join(project, rel); mkdirSync(path.dirname(f), { recursive: true }); writeFileSync(f, text) }

beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'portfolio-'))
  project = path.join(dir, 'project'); home = path.join(dir, 'home')
  mkdirSync(project, { recursive: true }); mkdirSync(home, { recursive: true })
  exec = vi.fn().mockResolvedValue({ stdout: '{}', stderr: '' })
  p = createPortfolio({ projectDir: project, homeDir: home, agentsDir: path.join(dir, 'agents'), exec })
})
afterEach(() => rmSync(dir, { recursive: true, force: true }))

describe('components', () => {
  it('lists nothing when the library does not exist yet', async () => {
    expect(await p.listComponents()).toEqual([])
  })

  it('lists components sorted by name with their html and optional notes', async () => {
    write('templates/components/project-card.html', '<div class="card"></div>')
    write('templates/components/github-button.html', '<a class="btn btn-default">View on GitHub</a>')
    write('templates/components/github-button.md', 'Use for the project\'s OWN repo only.')
    const list = await p.listComponents()
    expect(list.map((c) => c.name)).toEqual(['github-button', 'project-card'])
    expect(list[0]).toMatchObject({ html: '<a class="btn btn-default">View on GitHub</a>', notes: "Use for the project's OWN repo only." })
    expect(list[1].notes).toBe('')
  })

  it('saves a component, creating the library directory on first use', async () => {
    await p.saveComponent('github-button', '<a>x</a>', 'notes here')
    expect(readFileSync(path.join(project, 'templates/components/github-button.html'), 'utf8')).toBe('<a>x</a>')
    expect(readFileSync(path.join(project, 'templates/components/github-button.md'), 'utf8')).toBe('notes here')
  })

  it.each(['../evil', 'a/b', 'Has Space', '', '.hidden', 'x'.repeat(80), 'UPPER'])('rejects the unsafe component name %j', async (name) => {
    await expect(p.saveComponent(name, '<a/>')).rejects.toThrow(/invalid component name/i)
  })

  it('never writes outside templates/ even for a crafted name', async () => {
    await p.saveComponent('ok-name', '<a/>')
    expect(existsSync(path.join(project, 'deploy'))).toBe(false)
  })

  it('refuses to create a component that already exists, but saving updates it', async () => {
    await p.createComponent('card', '<div/>')
    await expect(p.createComponent('card', '<p/>')).rejects.toThrow(/already exists/i)
    await p.saveComponent('card', '<p/>')
    expect((await p.listComponents())[0].html).toBe('<p/>')
  })

  it('rejects non-string html', async () => {
    await expect(p.saveComponent('card', 42)).rejects.toThrow(/html must be a string/i)
  })
})

describe('design rules', () => {
  it('returns the effective rules (from the evaluator) alongside the saved overrides', async () => {
    exec.mockResolvedValue({ stdout: JSON.stringify({ tolerance_px: 2, github_button: { text: 'View on GitHub' } }), stderr: '' })
    write('templates/design-rules.json', JSON.stringify({ tolerance_px: 5 }))
    const r = await p.getRules()
    expect(r.overrides).toEqual({ tolerance_px: 5 })
    expect(r.effective.github_button.text).toBe('View on GitHub')
    expect(exec.mock.calls[0][1]).toContain('--print-rules')
  })

  it('treats a missing or corrupt rules file as no overrides', async () => {
    exec.mockResolvedValue({ stdout: '{}', stderr: '' })
    expect((await p.getRules()).overrides).toEqual({})
    write('templates/design-rules.json', '{broken')
    expect((await p.getRules()).overrides).toEqual({})
  })

  it('saves valid override objects as pretty JSON and rejects anything else', async () => {
    await p.saveRules({ footer: { expected_cards: 2 } })
    expect(JSON.parse(readFileSync(path.join(project, 'templates/design-rules.json'), 'utf8'))).toEqual({ footer: { expected_cards: 2 } })
    await expect(p.saveRules([1, 2])).rejects.toThrow(/object/i)
    await expect(p.saveRules('x')).rejects.toThrow(/object/i)
    await expect(p.saveRules(null)).rejects.toThrow(/object/i)
  })
})

describe('guide', () => {
  it('is empty until written, then round-trips', async () => {
    expect(await p.getGuide()).toBe('')
    await p.saveGuide('# Guide\n\nCards are equal height.')
    expect(await p.getGuide()).toBe('# Guide\n\nCards are equal height.')
  })
})

describe('evaluation', () => {
  const result = { generated_at: 't', findings: [{ page: '/a/', rule: 'x', detail: 'd' }], summary: { by_rule: { x: 1 } } }

  it('latestEval is null when nothing has run, or the file is corrupt', async () => {
    expect(await p.latestEval()).toBeNull()
    mkdirSync(path.join(home, '.claude/portfolio'), { recursive: true })
    writeFileSync(path.join(home, '.claude/portfolio/eval-latest.json'), '{nope')
    expect(await p.latestEval()).toBeNull()
  })

  it('reads the latest evaluation result', async () => {
    mkdirSync(path.join(home, '.claude/portfolio'), { recursive: true })
    writeFileSync(path.join(home, '.claude/portfolio/eval-latest.json'), JSON.stringify(result))
    expect((await p.latestEval()).summary.by_rule).toEqual({ x: 1 })
  })

  it('runEval treats exit code 1 (findings found) as a normal outcome, not a failure', async () => {
    mkdirSync(path.join(home, '.claude/portfolio'), { recursive: true })
    exec.mockImplementation(async () => {
      writeFileSync(path.join(home, '.claude/portfolio/eval-latest.json'), JSON.stringify(result))
      throw Object.assign(new Error('exit 1'), { code: 1 })
    })
    const r = await p.runEval()
    expect(r.findings).toHaveLength(1)
  })

  it('runEval surfaces a real failure (any other exit code)', async () => {
    exec.mockRejectedValue(Object.assign(new Error('playwright missing'), { code: 2, stderr: 'boom' }))
    await expect(p.runEval()).rejects.toThrow(/evaluation failed/i)
  })
})

describe('images', () => {
  const manifest = [
    { title: 'Algorithms', url: '/ai-projects/algorithms/', thumbnail: '/u/work001-01.jpg' },
    { title: 'Mancala', url: '/ai-projects/mancala/', thumbnail: '/u/work001-01.jpg' },
    { title: 'MITRE', url: '/ai-projects/mitre/', thumbnail: '/u/mitre.jpg' }
  ]
  beforeEach(() => write('deploy/other-projects/manifest.json', JSON.stringify(manifest)))

  it('derives a slug from a project url', () => {
    expect(slugOf('/ai-projects/mancala/')).toBe('mancala')
    expect(slugOf('/software-engineering/killer-sudoku')).toBe('killer-sudoku')
  })

  it('lists projects and flags a shared thumbnail, naming who shares it', async () => {
    const list = await p.listImages()
    const alg = list.find((i) => i.slug === 'algorithms')
    expect(alg.sharedWith).toEqual(['Mancala'])
    expect(list.find((i) => i.slug === 'mitre').sharedWith).toEqual([])
  })

  it('reports whether a generated image exists for each project', async () => {
    mkdirSync(path.join(home, '.claude/portfolio/images'), { recursive: true })
    writeFileSync(path.join(home, '.claude/portfolio/images/mitre.png'), 'png')
    const list = await p.listImages()
    expect(list.find((i) => i.slug === 'mitre').generated).toMatchObject({ exists: true })
    expect(list.find((i) => i.slug === 'mancala').generated.exists).toBe(false)
  })

  it('generates an image only for a slug that is in the manifest', async () => {
    await p.generateImage('mitre')
    expect(exec.mock.calls[0][1]).toEqual(expect.arrayContaining(['mitre']))
    await expect(p.generateImage('../../etc/passwd')).rejects.toThrow(/unknown project/i)
    await expect(p.generateImage('not-in-manifest')).rejects.toThrow(/unknown project/i)
  })

  it('returns an empty list when the manifest is missing, not a crash', async () => {
    rmSync(path.join(project, 'deploy'), { recursive: true, force: true })
    expect(await p.listImages()).toEqual([])
  })
})

describe('previews', () => {
  it('imagePreview returns a data URL for a generated image and null when none exists', async () => {
    write('deploy/other-projects/manifest.json', JSON.stringify([{ title: 'MITRE', url: '/ai-projects/mitre/', thumbnail: '/u/m.jpg' }]))
    expect(await p.imagePreview('mitre')).toBeNull()
    mkdirSync(path.join(home, '.claude/portfolio/images'), { recursive: true })
    writeFileSync(path.join(home, '.claude/portfolio/images/mitre.png'), Buffer.from([137, 80, 78, 71]))
    expect(await p.imagePreview('mitre')).toBe('data:image/png;base64,' + Buffer.from([137, 80, 78, 71]).toString('base64'))
  })

  it('imagePreview refuses anything that is not a known project slug', async () => {
    write('deploy/other-projects/manifest.json', '[]')
    await expect(p.imagePreview('../../etc/passwd')).rejects.toThrow(/unknown project/i)
  })

  it('previewHead fetches the dev site and returns its stylesheet links plus a base href, so a component previews with the real site styling', async () => {
    const html = `<html><head><link rel='stylesheet' id='a' href='http://localhost:8080/wp-content/a.css?ver=1' media='all' />
      <link rel="stylesheet" href="/wp-content/b.css"><link rel="icon" href="/x.ico"><style>.x{}</style></head></html>`
    const fetchFn = vi.fn().mockResolvedValue({ ok: true, text: async () => html })
    const q = createPortfolio({ projectDir: project, homeDir: home, agentsDir: path.join(dir, 'agents'), exec, fetchFn })
    const head = await q.previewHead('http://localhost:8080')
    expect(head).toContain('<base href="http://localhost:8080/">')
    expect(head).toContain("href='http://localhost:8080/wp-content/a.css?ver=1'")   // WordPress emits single quotes; tags are kept verbatim
    expect(head).toContain('href="/wp-content/b.css"')
    expect(head).not.toContain('x.ico')           // only stylesheets
    expect(head).not.toContain('<style>')         // no inline script/style carried over
  })

  it('previewHead degrades to an empty head with a reason when the dev site is down', async () => {
    const fetchFn = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'))
    const q = createPortfolio({ projectDir: project, homeDir: home, agentsDir: path.join(dir, 'agents'), exec, fetchFn })
    const head = await q.previewHead('http://localhost:8080')
    expect(head).toContain('dev site not reachable')
  })
})

describe('generateImage passes the project\'s existing image as inspiration', () => {
  it('hands the generator the existing thumbnail (resolved inside the dev html dir) via --inspire', async () => {
    write('deploy/other-projects/manifest.json', JSON.stringify([{ title: 'MITRE', url: '/ai-projects/mitre/', thumbnail: '/wp-content/uploads/2025/10/mitre.jpg' }]))
    const htmlDir = path.join(dir, 'html')
    const q = createPortfolio({ projectDir: project, homeDir: home, agentsDir: path.join(dir, 'agents'), exec, htmlDir })
    await q.generateImage('mitre')
    const args = exec.mock.calls[0][1]
    expect(args).toContain('--inspire')
    expect(args[args.indexOf('--inspire') + 1]).toBe(path.join(htmlDir, 'wp-content/uploads/2025/10/mitre.jpg'))
  })

  it('never lets a crafted thumbnail path escape the html dir', async () => {
    write('deploy/other-projects/manifest.json', JSON.stringify([{ title: 'X', url: '/a/evil/', thumbnail: '/../../../etc/passwd' }]))
    const htmlDir = path.join(dir, 'html')
    const q = createPortfolio({ projectDir: project, homeDir: home, agentsDir: path.join(dir, 'agents'), exec, htmlDir })
    await q.generateImage('evil')
    expect(exec.mock.calls[0][1]).not.toContain('--inspire')
  })
})

// ── site inventory + templates (Gil 2026-10-02: components must be representative of what is ON the
// website; templates for every existing page; plug-and-play so MARVIN supplies data, not markup) ──

describe('inventory', () => {
  const inv = { generated_at: 't', pages: [{ slug: 'ai-projects--mancala', url: '/ai-projects/mancala/', title: 'Mancala', type: 'project', screenshot: 'pages/ai-projects--mancala.png', raw: 'raw/ai-projects--mancala.html' }],
    buttons: [{ id: 'abc', kind: 'button', count: 3, screenshot: 'buttons/abc.png' }], summary: { pages: 1 } }
  beforeEach(() => {
    const d = path.join(home, '.claude/portfolio/inventory')
    mkdirSync(path.join(d, 'pages'), { recursive: true }); mkdirSync(path.join(d, 'buttons'), { recursive: true }); mkdirSync(path.join(d, 'raw'), { recursive: true })
    writeFileSync(path.join(d, 'inventory.json'), JSON.stringify(inv))
    writeFileSync(path.join(d, 'pages/ai-projects--mancala.png'), Buffer.from([1, 2, 3]))
    writeFileSync(path.join(d, 'buttons/abc.png'), Buffer.from([4, 5]))
    writeFileSync(path.join(d, 'raw/ai-projects--mancala.html'), '[fusion_text]Mancala[/fusion_text]')
  })

  it('reads the inventory, or null when it has never been collected / is corrupt', async () => {
    expect((await p.inventory()).summary.pages).toBe(1)
    writeFileSync(path.join(home, '.claude/portfolio/inventory/inventory.json'), '{bad')
    expect(await p.inventory()).toBeNull()
  })

  it('serves an inventory screenshot as a data URL, confined to the inventory directory', async () => {
    expect(await p.inventoryImage('buttons/abc.png')).toBe('data:image/png;base64,' + Buffer.from([4, 5]).toString('base64'))
    await expect(p.inventoryImage('../../../etc/passwd')).rejects.toThrow(/invalid inventory path/i)
    await expect(p.inventoryImage('/etc/passwd')).rejects.toThrow(/invalid inventory path/i)
    expect(await p.inventoryImage('buttons/missing.png')).toBeNull()
  })

  it('returns a page\'s raw markup, by slug only (never a path)', async () => {
    expect(await p.pageMarkup('ai-projects--mancala')).toBe('[fusion_text]Mancala[/fusion_text]')
    await expect(p.pageMarkup('../x')).rejects.toThrow(/invalid page/i)
    expect(await p.pageMarkup('nope')).toBeNull()
  })

  it('refreshInventory runs the crawler, then re-exports the reference templates, and returns the new inventory', async () => {
    const r = await p.refreshInventory()
    const scripts = exec.mock.calls.map((c) => c[1][0])
    expect(scripts[0]).toMatch(/portfolio_inventory\.py$/)
    expect(r.summary.pages).toBe(1)
  })
})

describe('templates', () => {
  it('lists templates via the renderer (single source of truth for fields and slots)', async () => {
    exec.mockResolvedValue({ stdout: JSON.stringify([{ id: 'project-page', kind: 'page' }]), stderr: '' })
    expect((await p.listTemplates())[0].id).toBe('project-page')
    expect(exec.mock.calls[0][1]).toEqual(expect.arrayContaining(['list']))
  })

  it('renders through the Python renderer, passing data and options as JSON', async () => {
    exec.mockResolvedValue({ stdout: JSON.stringify({ ok: true, html: '<a/>' }), stderr: '' })
    const r = await p.renderTemplate('button-github', { REPO_URL: 'https://github.com/G-Eskayo/x' }, {})
    expect(r.ok).toBe(true)
    const args = exec.mock.calls[0][1]
    expect(args).toEqual(expect.arrayContaining(['render', 'button-github']))
    expect(JSON.parse(args[args.indexOf('--data') + 1])).toEqual({ REPO_URL: 'https://github.com/G-Eskayo/x' })
  })

  it('refuses a template id that is not a plain id', async () => {
    await expect(p.renderTemplate('../../x', {}, {})).rejects.toThrow(/invalid template id/i)
  })

  it('plans a whole new project from one data set (page + card + manifest entry)', async () => {
    exec.mockResolvedValue({ stdout: JSON.stringify({ ok: true, page_html: '<p/>', card_html: '<c/>', manifest_entry: { url: '/ai-projects/x/' } }), stderr: '' })
    const plan = await p.planProject({ title: 'X', slug: 'x' })
    expect(plan.manifest_entry.url).toBe('/ai-projects/x/')
    expect(exec.mock.calls[0][1]).toEqual(expect.arrayContaining(['plan']))
  })

  it('lists the reference templates (one per existing page) from templates/reference/index.json', async () => {
    write('templates/reference/index.json', JSON.stringify([{ slug: 'about-me', url: '/about-me/', title: 'About me', type: 'page', file: 'reference/about-me.html', empty: false }]))
    write('templates/reference/about-me.html', '[fusion_text]About[/fusion_text]')
    const list = await p.listReference()
    expect(list[0].slug).toBe('about-me')
    expect(await p.referenceMarkup('about-me')).toBe('[fusion_text]About[/fusion_text]')
    await expect(p.referenceMarkup('../../x')).rejects.toThrow(/invalid page/i)
  })
})

describe('template source (plain markup behind each template)', () => {
  const manifest = (file) => JSON.stringify({ templates: [{ id: 'content-page', file }] })

  it('reads and saves the file the manifest names', async () => {
    write('templates/templates.json', manifest('content-page.html'))
    write('templates/content-page.html', '<p>old</p>')
    expect(await p.templateSource('content-page')).toBe('<p>old</p>')
    await p.saveTemplateSource('content-page', '<p>new</p>')
    expect(readFileSync(path.join(project, 'templates', 'content-page.html'), 'utf8')).toBe('<p>new</p>')
  })

  it('rejects unknown ids, bad ids and empty markup', async () => {
    write('templates/templates.json', manifest('content-page.html'))
    await expect(p.templateSource('nope')).rejects.toThrow(/Unknown template/)
    await expect(p.templateSource('../x')).rejects.toThrow(/Invalid template id/)
    await expect(p.saveTemplateSource('content-page', '   ')).rejects.toThrow(/non-empty/)
  })

  it('never writes outside templates/ even if the manifest points there', async () => {
    write('templates/templates.json', manifest('../deploy/evil.html'))
    await expect(p.saveTemplateSource('content-page', '<p>x</p>')).rejects.toThrow(/escapes templates/)
    expect(existsSync(path.join(project, 'deploy', 'evil.html'))).toBe(false)
  })
})
