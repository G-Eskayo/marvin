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
  projectDir = path.join(homedir(), 'Documents', 'Projects', 'portfolio-website-updater'),
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
  const inventoryScript = path.join(agentsDir, 'lib', 'portfolio_inventory.py')
  const templatesScript = path.join(agentsDir, 'lib', 'portfolio_templates.py')
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

  async function generateImage(slug) {
    const manifest = await readJson(manifestFile, [])
    const known = Array.isArray(manifest) && manifest.some((m) => slugOf(m.url) === slug)
    if (typeof slug !== 'string' || !NAME_RE.test(slug) || !known) {
      throw new Error(`Unknown project: ${JSON.stringify(slug)}`)
    }
    const entry = manifest.find((m) => slugOf(m.url) === slug)
    const existing = path.resolve(htmlDir, '.' + String(entry.thumbnail || ''))
    const inside = existing.startsWith(path.resolve(htmlDir) + path.sep)   // a crafted thumbnail path must not escape htmlDir
    const args = [imageScript, slug, ...(inside ? ['--inspire', existing] : [])]
    await exec(python, args, { maxBuffer: 1024 * 1024, timeout: 5 * 60 * 1000 })
    return { slug, path: path.join(imagesDir, `${slug}.png`) }
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
    try {
      const res = await fetchFn(base, { signal: AbortSignal.timeout(5000) })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const html = await res.text()
      const links = [...html.matchAll(/<link\b[^>]*>/gi)]
        .map((m) => m[0])
        .filter((tag) => /rel=['"]stylesheet['"]/i.test(tag))
      return `<base href="${base.replace(/\/?$/, '/')}">\n${links.join('\n')}`
    } catch (err) {
      return `<!-- dev site not reachable (${String(err.message || err)}): previewing without the site's stylesheets -->`
    }
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

  async function saveTemplateSource(id, content) {
    if (typeof content !== 'string' || !content.trim()) throw new Error('Template markup must be a non-empty string')
    const file = await templateFile(id)
    await fsp.writeFile(file, content)
    return { id }
  }

  const planProject = (data) => runTemplates(['plan', '--data', JSON.stringify(data || {})])

  const listReference = async () => (await readJson(path.join(referenceDir, 'index.json'), [])) || []

  async function referenceMarkup(slug) {
    if (typeof slug !== 'string' || !/^[a-z0-9][a-z0-9-]*$/.test(slug)) throw new Error(`Invalid page: ${JSON.stringify(slug)}`)
    return readText(path.join(referenceDir, `${slug}.html`), null)
  }

  return { inventory, inventoryImage, pageMarkup, refreshInventory, listTemplates, templateSource, saveTemplateSource, renderTemplate, planProject, listReference, referenceMarkup, imagePreview, previewHead, listComponents, saveComponent, createComponent, getRules, saveRules, getGuide, saveGuide, latestEval, runEval, listImages, generateImage }
}
