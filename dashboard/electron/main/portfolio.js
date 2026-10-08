import { promises as fsp } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Backend for the Portfolio tab -- the single hub for how a portfolio Project Page is built
// (component library, design rules, guide, evaluation, images). See CONTEXT.md "Dashboard app --
// Portfolio tab". Decided 2026-10-02:
//   * DEV-ONLY by construction: every write is confined to <project>/templates/ (and the
//     MARVIN-side result/image dirs). It never touches deploy/ -- a push touching deploy/
//     auto-deploys to PRODUCTION, and promoting to production is Gil's manual act.
//   * Rules are shared with the evaluator (lib/portfolio_eval.py): the tab edits the same
//     design-rules.json the checks read, so changing a rule changes what is checked.
//
// Dependencies are injected (project/home/agents dirs, exec) so the whole module is testable.

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,60}$/

export function slugOf(url) {
  return String(url).replace(/\/+$/, '').split('/').pop()
}

async function readText(file, fallback = '') {
  try {
    return await fsp.readFile(file, 'utf8')
  } catch {
    return fallback
  }
}

async function readJson(file, fallback = null) {
  try {
    return JSON.parse(await fsp.readFile(file, 'utf8'))
  } catch {
    return fallback
  }
}

function assertName(name) {
  if (typeof name !== 'string' || !NAME_RE.test(name)) {
    throw new Error(`Invalid component name: ${JSON.stringify(name)} (lowercase letters, digits and hyphens, up to 61 chars)`)
  }
}

export function createPortfolio({
  projectDir = path.join(homedir(), 'Developer', 'portfolio-website-updater'), // out of iCloud ~/Documents since #192
  homeDir = homedir(),
  agentsDir = path.join(homedir(), '.agents'),
  exec,
  fetchFn = (...a) => fetch(...a),
  // Where the DEV site's files live (ADR 0003: a local copy outside iCloud). Existing project images are
  // read from here as inspiration for the generator -- never used as the key photo.
  htmlDir = path.join(homedir(), 'portfolio-dev', 'wordpress', 'html')
} = {}) {
  const templates = path.join(projectDir, 'templates')
  const componentsDir = path.join(templates, 'components')
  const rulesFile = path.join(templates, 'design-rules.json')
  const guideFile = path.join(templates, 'GUIDE.md')
  const manifestFile = path.join(projectDir, 'deploy', 'other-projects', 'manifest.json')
  const dataDir = path.join(homeDir, '.claude', 'portfolio')
  const evalFile = path.join(dataDir, 'eval-latest.json')
  const imagesDir = path.join(dataDir, 'images')
  const registryFile = path.join(agentsDir, 'portfolio', 'image-registry.json')
  const python = path.join(agentsDir, 'venv', 'bin', 'python')
  const evalScript = path.join(agentsDir, 'lib', 'portfolio_eval.py')
  const imageScript = path.join(agentsDir, 'lib', 'portfolio_imagegen.py')
  const addProjectScript = path.join(agentsDir, 'lib', 'portfolio_add_project.py')
  const parityScript = path.join(agentsDir, 'lib', 'portfolio_parity.py')
  const syncScript = path.join(agentsDir, 'lib', 'portfolio_sync_dev.py')
  const applyScript = path.join(agentsDir, 'lib', 'portfolio_apply.py')
  const inventoryScript = path.join(agentsDir, 'lib', 'portfolio_inventory.py')
  const templatesScript = path.join(agentsDir, 'lib', 'portfolio_templates.py')
  const contentScript = path.join(agentsDir, 'lib', 'portfolio_content.py')
  const inventoryDir = path.join(dataDir, 'inventory')
  const referenceDir = path.join(templates, 'reference')

  async function listComponents() {
    let entries
    try {
      entries = await fsp.readdir(componentsDir)
    } catch {
      return []
    }
    const names = entries.filter((f) => f.endsWith('.html')).map((f) => f.slice(0, -5)).sort()
    return Promise.all(
      names.map(async (name) => ({
        name,
        html: await readText(path.join(componentsDir, `${name}.html`)),
        notes: await readText(path.join(componentsDir, `${name}.md`))
      }))
    )
  }

  async function saveComponent(name, html, notes = '') {
    assertName(name)
    if (typeof html !== 'string') throw new Error('Component html must be a string')
    await fsp.mkdir(componentsDir, { recursive: true })
    await fsp.writeFile(path.join(componentsDir, `${name}.html`), html)
    if (typeof notes === 'string' && (notes || (await readText(path.join(componentsDir, `${name}.md`))))) {
      await fsp.writeFile(path.join(componentsDir, `${name}.md`), notes)
    }
    return { name }
  }

  async function createComponent(name, html, notes = '') {
    assertName(name)
    try {
      await fsp.access(path.join(componentsDir, `${name}.html`))
      throw new Error(`Component "${name}" already exists`)
    } catch (err) {
      if (String(err.message).includes('already exists')) throw err
    }
    return saveComponent(name, html, notes)
  }

  async function getRules() {
    const { stdout } = await exec(python, [evalScript, '--print-rules'], { maxBuffer: 1024 * 1024 })
    const overrides = await readJson(rulesFile, {})
    return { effective: JSON.parse(stdout), overrides: overrides && typeof overrides === 'object' && !Array.isArray(overrides) ? overrides : {} }
  }

  async function saveRules(overrides) {
    if (overrides === null || typeof overrides !== 'object' || Array.isArray(overrides)) {
      throw new Error('Design rules must be a JSON object')
    }
    await fsp.mkdir(templates, { recursive: true })
    await fsp.writeFile(rulesFile, JSON.stringify(overrides, null, 2) + '\n')
    return { saved: true }
  }

  const getGuide = () => readText(guideFile)

  async function saveGuide(text) {
    if (typeof text !== 'string') throw new Error('Guide must be a string')
    await fsp.mkdir(templates, { recursive: true })
    await fsp.writeFile(guideFile, text)
    return { saved: true }
  }

  const latestEval = () => readJson(evalFile, null)

  async function runEval() {
    try {
      await exec(python, [evalScript], { maxBuffer: 10 * 1024 * 1024, timeout: 10 * 60 * 1000 })
    } catch (err) {
      // The evaluator exits 1 when it FOUND problems -- that is the normal, useful outcome.
      if (err && err.code !== 1) {
        throw new Error(`Evaluation failed: ${String(err.stderr || err.message).slice(0, 400)}`)
      }
    }
    return latestEval()
  }

  async function listImages() {
    const manifest = await readJson(manifestFile, null)
    if (!Array.isArray(manifest)) return []
    const registry = await readJson(registryFile, {})
    const byThumb = new Map()
    for (const m of manifest) byThumb.set(m.thumbnail, [...(byThumb.get(m.thumbnail) || []), m.title])
    return Promise.all(
      manifest.map(async (m) => {
        const slug = slugOf(m.url)
        const file = path.join(imagesDir, `${slug}.png`)
        let exists = false
        try {
          await fsp.access(file)
          exists = true
        } catch {
          /* not generated yet */
        }
        return {
          slug,
          title: m.title,
          url: m.url,
          thumbnail: m.thumbnail,
          sharedWith: (byThumb.get(m.thumbnail) || []).filter((t) => t !== m.title),
          generated: { exists, path: exists ? file : null, ...(registry[slug] ? { salt: registry[slug].salt, style: registry[slug].style } : {}) }
        }
      })
    )
  }

  // The project's existing thumbnail (inside the dev site only) is passed as COLOUR inspiration -- never used as the image.
  async function knownProject(slug) {
    const manifest = await readJson(manifestFile, [])
    const entry = Array.isArray(manifest) && typeof slug === 'string' && NAME_RE.test(slug) ? manifest.find((m) => slugOf(m.url) === slug) : null
    if (!entry) throw new Error(`Unknown project: ${JSON.stringify(slug)}`)
    return entry
  }

  function inspireArgs(entry) {
    const existing = path.resolve(htmlDir, '.' + String(entry.thumbnail || ''))
    const inside = existing.startsWith(path.resolve(htmlDir) + path.sep)   // a crafted thumbnail path must not escape htmlDir
    return inside ? ['--inspire', existing] : []
  }

  async function generateImage(slug) {
    const entry = await knownProject(slug)
    await exec(python, [imageScript, slug, ...inspireArgs(entry)], { maxBuffer: 1024 * 1024, timeout: 5 * 60 * 1000 })
    return { slug, path: path.join(imagesDir, `${slug}.png`) }
  }

  // ── variants: every image tried is kept; the person chooses which one is in use ──
  const MOTIF_RE = /^[a-z][a-z-]{0,30}$/

  async function runImages(args) {
    const { stdout } = await exec(python, [imageScript, ...args], { maxBuffer: 1024 * 1024, timeout: 5 * 60 * 1000 })
    return JSON.parse(stdout)
  }

  const imageMotifs = () => runImages(['--motifs'])

  async function imageVariants(slug) {
    await knownProject(slug)
    return runImages([slug, '--list'])
  }

  async function newImageVariant(slug, motif) {
    const entry = await knownProject(slug)
    if (motif != null && !MOTIF_RE.test(motif)) throw new Error(`Invalid motif: ${JSON.stringify(motif)}`)
    return runImages([slug, '--new', ...(motif ? ['--motif', motif] : []), ...inspireArgs(entry)])
  }

  async function chooseImageVariant(slug, motif, salt) {
    const entry = await knownProject(slug)
    if (typeof motif !== 'string' || !MOTIF_RE.test(motif)) throw new Error(`Invalid motif: ${JSON.stringify(motif)}`)
    if (!Number.isInteger(salt) || salt < 0 || salt > 9999) throw new Error(`Invalid variant number: ${JSON.stringify(salt)}`)
    return runImages([slug, '--choose', '--motif', motif, '--salt', String(salt), ...inspireArgs(entry)])
  }

  // Put the images that are in use onto the DEV site (thumbnails, manifest, hub + All Projects pages). Slow (it
  // regenerates pages through the dev site), and it edits deploy/other-projects/manifest.json in the repo: a change
  // for the person to review and commit -- this never pushes anything.
  async function applyImages() {
    const { stdout } = await exec(python, [applyScript], { maxBuffer: 5 * 1024 * 1024, timeout: 10 * 60 * 1000 })
    return JSON.parse(stdout.trim().split('\n').pop())
  }

  // The add-project pipeline (lib/portfolio_add_project.py): a project spec in, a finished DEV-site change out. `plan`
  // validates and writes nothing. The script exits 2 for a spec problem and reports it as JSON on stdout.
  async function addProject(spec, { plan = false } = {}) {
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) throw new Error('A project spec is required')
    if (!/^[a-z0-9][a-z0-9-]{0,60}$/.test(String(spec.slug || ''))) throw new Error('The slug must be lowercase letters, digits and hyphens')
    if (JSON.stringify(spec).length > 200000) throw new Error('The project spec is too large')
    await fsp.mkdir(dataDir, { recursive: true })
    const file = path.join(dataDir, `add-project-${process.pid}-${Date.now()}.json`)
    await fsp.writeFile(file, JSON.stringify(spec))
    try {
      const { stdout } = await exec(python, [addProjectScript, '--spec', file, ...(plan ? ['--plan'] : [])], { maxBuffer: 5 * 1024 * 1024, timeout: 15 * 60 * 1000 })
      return JSON.parse(stdout.trim().split('\n').pop())
    } catch (err) {
      try { return JSON.parse(String(err.stdout || '').trim().split('\n').pop()) } catch { throw new Error(err.message) }
    } finally {
      await fsp.rm(file, { force: true })
    }
  }

  // The element library (templates/elements/<id>.json): elements captured from the live dev site, generalized, with their
  // look, where each look comes from, and every page that carries them.
  async function listElements() {
    let names = []
    try {
      names = (await fsp.readdir(path.join(templates, 'elements'))).filter((f) => f.endsWith('.json')).sort()
    } catch {
      return []
    }
    const out = []
    for (const f of names) {
      const e = await readJson(path.join(templates, 'elements', f), null)
      if (e && e.id) out.push(e)
    }
    return out
  }

  // Does the dashboard's own preview of the element still match the live site? (Renders it exactly as the tab does.)
  async function verifyElement(id) {
    if (typeof id !== 'string' || !TEMPLATE_ID.test(id)) throw new Error(`Invalid element id: ${JSON.stringify(id)}`)
    try {
      const { stdout } = await exec(python, [parityScript, id], { maxBuffer: 2 * 1024 * 1024, timeout: 3 * 60 * 1000 })
      return JSON.parse(stdout.trim().split('\n').pop())
    } catch (err) {
      try { return JSON.parse(String(err.stdout || '').trim().split('\n').pop()) } catch { throw new Error(err.message) }
    }
  }

  // The element pipeline's last result (lib/portfolio_sync_dev.py writes it) and a way to run it from the dashboard.
  const pipelineStatus = async () => readJson(path.join(dataDir, 'pipeline-status.json'), null)

  async function runPipeline() {
    try {
      const { stdout } = await exec(python, [syncScript], { maxBuffer: 5 * 1024 * 1024, timeout: 15 * 60 * 1000 })
      return JSON.parse(stdout.trim().split('\n').pop())
    } catch (err) {
      try { return JSON.parse(String(err.stdout || '').trim().split('\n').pop()) } catch { throw new Error(err.message) }
    }
  }

  async function deleteImageVariant(slug, motif, salt) {
    await knownProject(slug)
    if (typeof motif !== 'string' || !MOTIF_RE.test(motif)) throw new Error(`Invalid motif: ${JSON.stringify(motif)}`)
    if (!Number.isInteger(salt) || salt < 0 || salt > 9999) throw new Error(`Invalid variant number: ${JSON.stringify(salt)}`)
    try {
      return await runImages([slug, '--delete', '--motif', motif, '--salt', String(salt)])
    } catch (err) {
      // the generator reports a refusal (e.g. "that image is the one in use") as JSON on stdout with exit code 3
      let reason = null
      try { reason = JSON.parse(err.stdout || '{}').error } catch { /* not JSON */ }
      throw new Error(reason || err.message)
    }
  }

  async function variantPreview(slug, motif, salt) {
    await knownProject(slug)
    if (typeof motif !== 'string' || !MOTIF_RE.test(motif) || !Number.isInteger(salt) || salt < 0) throw new Error('Invalid variant')
    try {
      return 'data:image/png;base64,' + (await fsp.readFile(path.join(imagesDir, slug, `${motif}-${salt}.png`))).toString('base64')
    } catch {
      return null
    }
  }

  // A generated image as a data URL, for the gallery. Same slug validation as generateImage.
  async function imagePreview(slug) {
    const manifest = await readJson(manifestFile, [])
    const known = Array.isArray(manifest) && manifest.some((m) => slugOf(m.url) === slug)
    if (typeof slug !== 'string' || !NAME_RE.test(slug) || !known) throw new Error(`Unknown project: ${JSON.stringify(slug)}`)
    try {
      return 'data:image/png;base64,' + (await fsp.readFile(path.join(imagesDir, `${slug}.png`))).toString('base64')
    } catch {
      return null
    }
  }

  // The <head> a component preview needs to look like the real page: the dev site's own
  // stylesheet links (and nothing else) behind a <base>. Fetched in the main process because the
  // renderer cannot read the dev site cross-origin.
  async function previewHead(base = 'http://localhost:8080') {
    const root = base.replace(/\/?$/, '')
    const get = async (url) => {
      try {
        const res = await fetchFn(url, { signal: AbortSignal.timeout(5000) })
        return res.ok ? await res.text() : null
      } catch {
        return null
      }
    }
    // Avada writes a different generated stylesheet per page (the one with the card titles and photo treatment is only
    // linked from pages that use cards), so a preview takes the UNION of the stylesheets of a few representative pages.
    const [home, cards, project] = await Promise.all([get(root), get(`${root}/all-projects/`), get(`${root}/ai-projects/mancala/`)])
    if (home === null && cards === null && project === null) {
      return "<!-- dev site not reachable: previewing without the site's stylesheets -->"
    }
    const links = []
    for (const html of [cards, project, home]) {
      for (const m of (html || '').matchAll(/<link\b[^>]*>/gi)) {
        if (/rel=['"]stylesheet['"]/i.test(m[0]) && !links.includes(m[0])) links.push(m[0])
      }
    }
    // Some styling is inline <style> on the page itself (the category sidebar's pink active item, for one), and the <body>
    // class scopes much of Avada's layout, so both come from a real project page.
    const inline = [...(project || '').matchAll(/<style\b[^>]*>[\s\S]*?<\/style>/gi)].map((m) => m[0])
    const bodyClass = ((project || '').match(/<body\b[^>]*\bclass=["']([^"']*)["']/i) || [])[1] || ''
    const meta = bodyClass ? `\n<meta name="preview-body-class" content="${bodyClass.replace(/"/g, '&quot;')}">` : ''
    return `<base href="${root}/">\n${links.join('\n')}\n${inline.join('\n')}${meta}`
  }

  // ── site inventory: what is ACTUALLY on the website (crawled by lib/portfolio_inventory.py) ──
  const inventory = () => readJson(path.join(inventoryDir, 'inventory.json'), null)

  // A screenshot from the inventory as a data URL. Relative path only, confined to the inventory dir.
  async function inventoryImage(rel) {
    const abs = path.resolve(inventoryDir, String(rel))
    if (typeof rel !== 'string' || path.isAbsolute(rel) || !abs.startsWith(path.resolve(inventoryDir) + path.sep)) {
      throw new Error(`Invalid inventory path: ${JSON.stringify(rel)}`)
    }
    try {
      return 'data:image/png;base64,' + (await fsp.readFile(abs)).toString('base64')
    } catch {
      return null
    }
  }

  // The parts of the page that wrap every page (header, title bar, sidebar, footer cards, footer), captured by the crawler.
  async function chrome() {
    const items = await readJson(path.join(inventoryDir, 'chrome', 'index.json'), [])
    return Promise.all((Array.isArray(items) ? items : []).map(async (c) => ({
      id: c.id, name: c.name, source: c.source, width: c.width ?? null, screenshot: c.screenshot,
      markup: await readText(path.join(inventoryDir, 'chrome', `${path.basename(String(c.id))}.html`))
    })))
  }

  async function pageMarkup(slug) {
    if (typeof slug !== 'string' || !/^[a-z0-9][a-z0-9-]*$/.test(slug)) throw new Error(`Invalid page: ${JSON.stringify(slug)}`)
    const text = await readText(path.join(inventoryDir, 'raw', `${slug}.html`), null)
    return text
  }

  async function refreshInventory() {
    await exec(python, [inventoryScript], { maxBuffer: 10 * 1024 * 1024, timeout: 10 * 60 * 1000 })
    // keep the reference templates (one per existing page) in step with what was just crawled
    await exec(python, ['-c', `import sys; sys.path.insert(0, ${JSON.stringify(path.join(agentsDir, 'lib'))}); import portfolio_templates as t; from pathlib import Path; t.export_reference(Path(${JSON.stringify(inventoryDir)}), Path(${JSON.stringify(templates)}))`], { maxBuffer: 1024 * 1024 })
    return inventory()
  }

  // ── templates: rendering is the Python renderer's job (one implementation, fully tested) ──
  const TEMPLATE_ID = /^[a-z0-9][a-z0-9-]*$/

  async function runTemplates(args) {
    const { stdout } = await exec(python, [templatesScript, ...args], { maxBuffer: 5 * 1024 * 1024 })
    return JSON.parse(stdout)
  }

  const listTemplates = () => runTemplates(['list'])

  async function renderTemplate(id, data, options) {
    if (typeof id !== 'string' || !TEMPLATE_ID.test(id)) throw new Error(`Invalid template id: ${JSON.stringify(id)}`)
    return runTemplates(['render', id, '--data', JSON.stringify(data || {}), '--options', JSON.stringify(options || {})])
  }

  // The plain markup behind a template, for reading and editing in the Templates tab. The manifest names
  // the file; the resolved path must stay inside templates/ so a crafted manifest entry cannot escape.
  async function templateFile(id) {
    if (typeof id !== 'string' || !TEMPLATE_ID.test(id)) throw new Error(`Invalid template id: ${JSON.stringify(id)}`)
    const manifest = await readJson(path.join(templates, 'templates.json'), null)
    const entry = (manifest?.templates || []).find((t) => t.id === id)
    if (!entry?.file) throw new Error(`Unknown template: ${id}`)
    const file = path.resolve(templates, entry.file)
    if (!file.startsWith(templates + path.sep)) throw new Error(`Template file escapes templates/: ${entry.file}`)
    return file
  }

  async function templateSource(id) {
    return readText(await templateFile(id))
  }

  const specimen = (id) => {
    if (typeof id !== 'string' || !TEMPLATE_ID.test(id)) throw new Error(`Invalid template id: ${JSON.stringify(id)}`)
    return runTemplates(['specimen', id])
  }

  const planProject = (data) => runTemplates(['plan', '--data', JSON.stringify(data || {})])

  const listReference = async () => (await readJson(path.join(referenceDir, 'index.json'), [])) || []

  async function referenceMarkup(slug) {
    if (typeof slug !== 'string' || !/^[a-z0-9][a-z0-9-]*$/.test(slug)) throw new Error(`Invalid page: ${JSON.stringify(slug)}`)
    return readText(path.join(referenceDir, `${slug}.html`), null)
  }

  // ── content templates (ADR 0051): what a page should say, and each page's gaps against its template ──
  async function contentTemplates() {
    let names = []
    try {
      names = (await fsp.readdir(path.join(templates, 'content'))).filter((f) => f.endsWith('.json')).sort()
    } catch {
      return []
    }
    const out = []
    for (const f of names) {
      const t = await readJson(path.join(templates, 'content', f), null)
      if (t && t.id) out.push(t)
    }
    return out
  }

  async function contentReport() {
    const { stdout } = await exec(python, [contentScript, '--json'], { maxBuffer: 5 * 1024 * 1024, timeout: 2 * 60 * 1000 })
    return JSON.parse(stdout)
  }

  return { contentTemplates, contentReport, chrome, inventory, inventoryImage, pageMarkup, refreshInventory, listTemplates, templateSource, specimen, renderTemplate, planProject, listReference, referenceMarkup, imagePreview, previewHead, listComponents, saveComponent, createComponent, getRules, saveRules, getGuide, saveGuide, latestEval, runEval, listImages, generateImage, imageMotifs, imageVariants, newImageVariant, chooseImageVariant, applyImages, addProject, listElements, verifyElement, pipelineStatus, runPipeline, deleteImageVariant, variantPreview }
}
