import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  groupFindingsByRule, parseRulesText, previewDocument, formatRunTime,
  buttonVerdict, groupTemplates, countByType, inventoryIsStale, slugify, CATEGORIES
} from '../lib/portfolio.js'

// The Portfolio hub (CONTEXT.md "Dashboard app -- Portfolio tab"): the single place that defines how
// a portfolio Project Page is built -- guide + design rules, the component library, the evaluation
// results, and the images. Gil edits and refines it; MARVIN reads from it when building pages.
// DEV-ONLY: edits are confined to the portfolio repo's templates/; nothing here touches production.

const DEV_SITE = 'http://localhost:8080'
const SUBTABS = [
  ['templates', 'Templates'],
  ['inventory', 'Site inventory'],
  ['add', 'Add project'],
  ['guide', 'Guide & rules'],
  ['evaluation', 'Evaluation'],
  ['images', 'Images']
]

const button =
  'rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:border-neutral-500 disabled:opacity-50'
const primary =
  'rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50'
const field =
  'w-full rounded-md border border-neutral-700 bg-neutral-950 p-3 font-mono text-xs text-neutral-200 outline-none focus:border-blue-500'

function Status({ state }) {
  if (!state) return null
  const color = state.error ? 'text-red-400' : 'text-emerald-400'
  return <span className={`text-xs ${color}`}>{state.error || state.message}</span>
}

function errText(err) {
  return String(err?.message || err).replace(/^Error invoking remote method '[^']+':\s*(Error:\s*)?/, '')
}


// ── Shared form pieces ──────────────────────────────────────────────────────

function CopyButton({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false)
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text || '')
          setDone(true)
          setTimeout(() => setDone(false), 1500)
        } catch {
          /* clipboard unavailable */
        }
      }}
      className={button}
    >
      {done ? 'Copied' : label}
    </button>
  )
}

function FieldInputs({ fields, data, onChange }) {
  return (
    <div className="flex flex-col gap-3">
      {fields.map((f) => (
        <label key={f.name} className="flex flex-col gap-1">
          <span className="text-xs text-neutral-400">
            {f.label || f.name}
            {f.required && <span className="text-red-400"> *</span>}
          </span>
          {fieldInputType(f) === 'textarea' ? (
            <textarea value={data[f.name] ?? ''} onChange={(e) => onChange({ ...data, [f.name]: e.target.value })} rows={5} spellCheck={false} className={field} />
          ) : (
            <input type="text" value={data[f.name] ?? ''} onChange={(e) => onChange({ ...data, [f.name]: e.target.value })} className="rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-xs text-neutral-200 outline-none focus:border-blue-500" />
          )}
        </label>
      ))}
    </div>
  )
}

// One slot (e.g. "Action buttons"): the alternatives a template accepts, each with its own fields.
function SlotPicker({ slot, spec, templates, value, onChange }) {
  const [adding, setAdding] = useState('')
  const byId = Object.fromEntries(templates.map((t) => [t.id, t]))
  const list = value || []
  return (
    <div className="rounded-lg border border-neutral-800 p-3">
      <div className="mb-2 flex items-center gap-2">
        <h4 className="text-xs font-medium uppercase tracking-wide text-neutral-400">{spec.label || slot}</h4>
        <span className="text-[10px] text-neutral-600">optional — leave empty for none</span>
      </div>
      {list.map((choice, i) => (
        <div key={i} className="mb-3 rounded-md border border-neutral-800 bg-neutral-950 p-3">
          <div className="mb-2 flex items-center">
            <span className="text-xs font-medium text-white">{byId[choice.template]?.name || choice.template}</span>
            <button onClick={() => onChange(list.filter((_, j) => j !== i))} className="ml-auto text-xs text-neutral-500 hover:text-red-400">remove</button>
          </div>
          <FieldInputs fields={byId[choice.template]?.fields || []} data={choice.data} onChange={(d) => onChange(list.map((c, j) => (j === i ? { ...c, data: d } : c)))} />
        </div>
      ))}
      <div className="flex items-center gap-2">
        <select value={adding} onChange={(e) => setAdding(e.target.value)} className="rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-200">
          <option value="">Add an alternative…</option>
          {spec.options.map((id) => (
            <option key={id} value={id}>{byId[id]?.name || id}</option>
          ))}
        </select>
        <button
          disabled={!adding}
          onClick={() => {
            onChange([...list, { template: adding, data: initialData(byId[adding]) }])
            setAdding('')
          }}
          className={button}
        >
          Add
        </button>
      </div>
    </div>
  )
}

function Problems({ result }) {
  if (!result) return null
  const items = [...(result.missing || []).map((m) => `Missing: ${m}`), ...(result.errors || [])]
  if (!items.length && !(result.warnings || []).length) return <span className="text-xs text-emerald-400">Ready — valid and complete</span>
  return (
    <ul className="text-xs">
      {items.map((m, i) => <li key={i} className="text-red-400">{m}</li>)}
      {(result.warnings || []).map((m, i) => <li key={`w${i}`} className="text-amber-400">{m}</li>)}
    </ul>
  )
}

// A live element in an iframe that grows to fit it: real markup, real site CSS, real hover states -- not a picture.
// allow-same-origin WITHOUT allow-scripts: the parent may measure the content, but nothing in it can run.
function AutoFrame({ html, head, title, wide = false, width = null, maxHeight = 640, context = 'page' }) {
  const [height, setHeight] = useState(120)
  const measure = (e) => {
    try {
      // Measure the content wrapper, not the document: the theme gives html/body a viewport-based height, which
      // would only ever grow the frame.
      const d = e.target.contentDocument
      const wrap = d.getElementById('wrapper')
      const h = wrap ? wrap.getBoundingClientRect().height + 32 : d.body.scrollHeight
      setHeight(Math.min(maxHeight, Math.max(40, Math.ceil(h))))
      // Everything behaves (hover, focus, pressed) except going anywhere: a link in a reference preview must not
      // navigate the frame or submit anything. Listener lives in the parent, so no script runs inside the frame.
      if (!d.__inert) {
        d.__inert = true
        d.addEventListener('click', (ev) => { if (ev.target.closest && ev.target.closest('a, button, input[type="submit"]')) ev.preventDefault() }, true)
        d.addEventListener('submit', (ev) => ev.preventDefault(), true)
      }
    } catch { /* keep the default height */ }
  }
  return (
    <iframe title={title} sandbox="allow-same-origin" srcDoc={previewDocument(html, head, { wide, width, context })} onLoad={measure} style={{ height }} className="w-full rounded-md border border-neutral-800 bg-white" />
  )
}

// ── Templates: the prescriptive reference, shown as what each one IS ───────

function Rule({ label, children }) {
  return <p className="text-xs text-neutral-300"><span className="text-neutral-500">{label}: </span>{children}</p>
}

// What the library knows about an element captured from the live dev site: its look, where each look comes from,
// where it is used, and whether the dashboard's own preview still matches the site.
function ElementDetails({ element }) {
  const [check, setCheck] = useState(null)
  const [busy, setBusy] = useState(false)
  async function verify() {
    setBusy(true)
    setCheck(null)
    try {
      setCheck(await window.api.portfolio.verifyElement(element.id))
    } catch (e) {
      setCheck({ ok: false, differences: [errText(e)] })
    } finally {
      setBusy(false)
    }
  }
  const pages = Object.entries(element.usage?.pages || {})
  const sources = Object.entries(element.provenance || {})
  return (
    <div className="mt-3 flex flex-col gap-3 rounded-md border border-neutral-800 bg-neutral-950 p-3 text-xs text-neutral-300">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded bg-emerald-950 px-1.5 py-0.5 text-[10px] text-emerald-300">captured from the live dev site</span>
        <span>{element.usage?.placements} placements on {pages.length} pages · {element.distinct_looks} distinct look{element.distinct_looks === 1 ? '' : 's'}</span>
        <span className={element.deviations?.length ? 'text-amber-400' : 'text-emerald-400'}>
          {element.deviations?.length ? `${element.deviations.length} placement(s) are not the element` : 'every placement is the element'}
        </span>
        <button onClick={verify} disabled={busy} className={`${button} ml-auto`}>{busy ? 'Checking…' : 'Verify this preview against the live site'}</button>
      </div>
      {check && (
        <p className={check.ok ? 'text-emerald-400' : 'text-red-400'}>
          {check.ok ? 'The preview above matches the live site (look and geometry).' : `Differences from the live site: ${check.differences.join('; ')}`}
        </p>
      )}
      {(element.deviations || []).map((d) => (
        <p key={d.page} className="text-amber-400">{d.page}: {d.why.join('; ')}</p>
      ))}
      {element.geometry && (
        <p><span className="text-neutral-500">Geometry: </span>photo frame {element.geometry.photoHeight}px · text box {element.geometry.boxHeight}px · box overlays the photo by {element.geometry.overlap}px</p>
      )}
      <details>
        <summary className="cursor-pointer text-neutral-400">Where its look comes from ({sources.length} parts)</summary>
        <div className="mt-2 flex flex-col gap-2">
          {sources.map(([part, props]) => (
            <div key={part}>
              <p className="text-neutral-500">{part}</p>
              {Object.entries(props).map(([prop, v]) => (
                <p key={prop} className="font-mono text-[11px]">{prop}: {v.value} <span className="text-neutral-600">← {v.selector} in {v.source}</span></p>
              ))}
            </div>
          ))}
        </div>
      </details>
      <details>
        <summary className="cursor-pointer text-neutral-400">Pages that use it ({pages.length})</summary>
        <p className="mt-2 font-mono text-[11px] text-neutral-400">{pages.map(([u, n]) => `${u} ×${n}`).join(' · ')}</p>
      </details>
    </div>
  )
}

function Specimen({ template, head, element }) {
  const [res, setRes] = useState(null)
  const [markup, setMarkup] = useState(null)
  const [showMarkup, setShowMarkup] = useState(false)
  useEffect(() => {
    let live = true
    window.api.portfolio.specimen(template.id).then((r) => live && setRes(r)).catch((e) => live && setRes({ ok: false, errors: [errText(e)] }))
    return () => { live = false }
  }, [template.id])
  async function toggleMarkup() {
    if (markup === null) {
      try { setMarkup(await window.api.portfolio.templateSource(template.id)) } catch (e) { setMarkup(`Could not read: ${errText(e)}`) }
    }
    setShowMarkup((v) => !v)
  }
  const isPage = template.kind === 'page'
  return (
    <article className="rounded-lg border border-neutral-800 p-4">
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <h3 className="text-base font-medium text-white">{template.name}</h3>
        <span className="font-mono text-[11px] text-neutral-600">{template.id}</span>
      </div>
      <p className="mb-3 text-xs text-neutral-400">{template.description}</p>
      {/* Stacked, so the preview frame is as wide as the page: the theme's desktop styles are media queries on the
          frame's width, and a narrow side-by-side frame would preview the phone layout instead. */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <Rule label="Page type">{template.pageType || '—'}</Rule>
          {template.role && <Rule label="Role">{template.role}</Rule>}
          {template.usedOn && <Rule label="Used on">{template.usedOn.join(', ')} pages only</Rule>}
          {template.placement && <Rule label="Placement">{template.placement}</Rule>}
          {(template.zones || []).length > 0 && (
            <ol className="mt-1 flex flex-col gap-1">
              {template.zones.map((z, i) => (
                <li key={z.name} className="rounded border border-dashed border-neutral-700 px-2 py-1 text-xs text-neutral-300"><span className="text-neutral-500">{i + 1}. </span>{z.name}<span className="text-neutral-500"> — {z.note}</span></li>
              ))}
            </ol>
          )}
          {(template.fields || []).length > 0 && <Rule label="Fill in">{template.fields.map((f) => f.label || f.name).join(' · ')}</Rule>}
        </div>
        <div className="min-w-0">
          {res && !res.ok && <p className="text-xs text-red-400">Specimen did not render: {[...(res.errors || []), ...(res.missing || [])].join('; ')}</p>}
          {res?.html && <AutoFrame title={`${template.name} specimen`} html={res.html} head={head} wide={isPage} width={isPage ? null : template.kind === 'button' ? 340 : template.id === 'project-card' ? 760 : 400} context={template.id === 'project-card' ? 'grid' : 'page'} maxHeight={isPage ? 700 : 520} />}
          {!res && <p className="text-xs text-neutral-600">Rendering…</p>}
        </div>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button onClick={toggleMarkup} className="text-xs text-blue-400 hover:text-blue-300">{showMarkup ? 'hide markup' : 'show markup'}</button>
        {showMarkup && <CopyButton text={markup} label="Copy markup" />}
      </div>
      {showMarkup && <pre className="mt-2 max-h-80 overflow-auto rounded border border-neutral-800 bg-neutral-950 p-3 text-[11px] text-neutral-300">{markup}</pre>}
      {element && <ElementDetails element={element} />}
    </article>
  )
}

// A part of the page that wraps every page (not authored per page): shown as it is on the site, with where it comes from.
function ChromePart({ part, head }) {
  const [open, setOpen] = useState(false)
  return (
    <article className="rounded-lg border border-neutral-800 p-4">
      <div className="mb-2 flex items-baseline gap-3">
        <h3 className="text-base font-medium text-white">{part.name}</h3>
        <span className="font-mono text-[11px] text-neutral-600">{part.id}</span>
      </div>
      <p className="mb-3 text-xs text-neutral-400">{part.source}</p>
      <div style={part.width ? { maxWidth: part.width + 24 } : undefined}>
        <AutoFrame title={part.name} html={part.markup} head={head} wide width={part.width} context="chrome" maxHeight={['hub-sidebar', 'other-projects'].includes(part.id) ? 900 : 520} />
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button onClick={() => setOpen((v) => !v)} className="text-xs text-blue-400 hover:text-blue-300">{open ? 'hide markup' : 'show markup'}</button>
        {open && <CopyButton text={part.markup} label="Copy markup" />}
      </div>
      {open && <pre className="mt-2 max-h-80 overflow-auto rounded border border-neutral-800 bg-neutral-950 p-3 text-[11px] text-neutral-300">{part.markup}</pre>}
    </article>
  )
}

// A one-line audit under the button templates: how much of the site already uses them. (Same section, not a second one.)
function ButtonAudit() {
  const [inv, setInv] = useState(null)
  useEffect(() => { window.api.portfolio.inventory().then(setInv).catch(() => setInv(false)) }, [])
  if (!inv) return null
  const off = inv.buttons.filter((v) => !buttonVerdict(v).ok)
  const ok = inv.buttons.filter((v) => buttonVerdict(v).ok)
  const instances = ok.reduce((n, v) => n + v.count, 0)
  return (
    <p className="text-xs text-neutral-500">
      On the site today: {instances} use{instances === 1 ? '' : 's'} of the canonical buttons.{' '}
      {off.length === 0
        ? 'No other button looks.'
        : `Still to bring back to these: ${off.map((v) => `“${v.texts[0] || v.classes || 'unnamed'}” ×${v.count}`).join(', ')}.`}
    </p>
  )
}

function Templates() {
  const [chrome, setChrome] = useState([])
  const [elements, setElements] = useState({})
  const [templates, setTemplates] = useState(null)
  const [head, setHead] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    window.api.portfolio.templates().then(setTemplates).catch((e) => setError(errText(e)))
    window.api.portfolio.previewHead().then(setHead).catch(() => {})
    window.api.portfolio.chrome().then(setChrome).catch(() => {})
    window.api.portfolio.elements().then((list) => setElements(Object.fromEntries(list.map((e) => [e.id, e])))).catch(() => {})
  }, [])

  if (error) return <p className="text-sm text-red-400">Could not load templates: {error}</p>
  if (!templates) return <p className="text-sm text-neutral-500">Loading templates…</p>

  const titles = { page: 'Page types', component: 'Components', button: 'Buttons — the only three' }
  return (
    <div className="flex flex-col gap-8">
      <p className="max-w-3xl text-xs text-neutral-500">
        The reference for how every page is built. Each template is shown as it renders on the site, with the rules for using it. To build or change a page, start from the matching template here so structure stays uniform.
      </p>
      <section className="flex flex-col gap-4">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-400">Around every page — generated, not authored per page</h2>
        {chrome.length === 0 ? (
          <p className="text-xs text-neutral-500">Not captured yet: start the dev site and use Refresh in Site inventory.</p>
        ) : chrome.map((c) => <ChromePart key={c.id} part={c} head={head} />)}
      </section>
      {groupTemplates(templates).map((g) => (
        <section key={g.kind} className="flex flex-col gap-4">
          <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-400">{titles[g.kind] || g.kind}</h2>
          {g.items.map((t) => <Specimen key={t.id} template={t} head={head} element={elements[t.id]} />)}
          {g.kind === 'button' && <ButtonAudit />}
        </section>
      ))}
    </div>
  )
}

// ── Site inventory: what is ACTUALLY on the website ─────────────────────────

function Shot({ rel, className = '' }) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    let live = true
    if (rel) window.api.portfolio.inventoryImage(rel).then((d) => live && setSrc(d)).catch(() => {})
    return () => { live = false }
  }, [rel])
  return src ? <img src={src} alt="" className={className} /> : <div className={`flex items-center justify-center bg-neutral-900 text-[10px] text-neutral-600 ${className}`}>{rel ? 'loading…' : 'no screenshot'}</div>
}

function PageTemplates({ pages }) {
  const [type, setType] = useState('all')
  const [open, setOpen] = useState(null)
  const [markup, setMarkup] = useState(null)
  const counts = countByType(pages)
  const shown = pages.filter((p) => type === 'all' || p.type === type)

  async function choose(p) {
    setOpen(p)
    setMarkup(null)
    try { setMarkup(await window.api.portfolio.pageMarkup(p.slug)) } catch { setMarkup('') }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {['all', ...Object.keys(counts)].map((t) => (
          <button key={t} onClick={() => setType(t)} className={`rounded-md border px-3 py-1 text-xs ${type === t ? 'border-blue-500 bg-blue-950 text-white' : 'border-neutral-800 text-neutral-400 hover:border-neutral-600'}`}>
            {t}{t !== 'all' ? ` (${counts[t]})` : ` (${pages.length})`}
          </button>
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-5">
        {shown.map((p) => (
          <button key={p.slug} onClick={() => choose(p)} className={`overflow-hidden rounded-lg border text-left ${open?.slug === p.slug ? 'border-blue-500' : 'border-neutral-800 hover:border-neutral-600'}`}>
            <div className="h-40 overflow-hidden bg-neutral-900"><Shot rel={p.screenshot} className="w-full" /></div>
            <div className="p-2">
              <p className="truncate text-xs font-medium text-white">{p.title}</p>
              <p className="truncate font-mono text-[10px] text-neutral-500">{p.url}</p>
              <span className="mt-1 inline-block rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">{p.type}</span>
            </div>
          </button>
        ))}
      </div>
      {open && (
        <div className="rounded-lg border border-neutral-800 p-4">
          <div className="mb-2 flex items-center gap-3">
            <h3 className="text-sm font-medium text-white">{open.title} <span className="font-mono text-xs text-neutral-500">{open.url}</span></h3>
            <CopyButton text={markup || ''} label="Copy markup" />
            <span className="text-[11px] text-neutral-500">saved as a reference template: templates/reference/{open.slug}.html</span>
          </div>
          {markup === null ? <p className="text-xs text-neutral-500">Loading…</p> : markup.trim() ? (
            <pre className="max-h-96 overflow-auto rounded border border-neutral-800 bg-neutral-950 p-3 text-[11px] text-neutral-300">{markup}</pre>
          ) : <p className="text-xs text-neutral-500">This page has no content of its own (it is only a navigation parent).</p>}
        </div>
      )}
    </div>
  )
}

function Inventory() {
  const [inv, setInv] = useState(undefined)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  // Always live: show what was last crawled at once, and re-crawl in the background when it is stale.
  useEffect(() => {
    let live = true
    window.api.portfolio.inventory().then((i) => {
      if (!live) return
      setInv(i)
      if (inventoryIsStale(i?.generated_at)) refresh()
    }).catch((e) => live && setError(errText(e)))
    return () => { live = false }
  }, [])

  async function refresh() {
    setBusy(true); setError(null)
    try { setInv(await window.api.portfolio.refreshInventory()) } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  const s = inv?.summary
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-medium text-white">What is on the website today (descriptive — the rules live in Templates)</h2>
        <button onClick={refresh} disabled={busy} className={primary}>{busy ? 'Updating from the dev site (about a minute)…' : 'Refresh now'}</button>
        <span className="text-xs text-neutral-500">crawled: {formatRunTime(inv?.generated_at)}</span>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
      {inv === undefined && <p className="text-sm text-neutral-500">Loading…</p>}
      {inv === null && <p className="text-sm text-neutral-400">Nothing crawled yet. Start the dev site, then refresh.</p>}
      {s && (
        <>
          <p className="text-xs text-neutral-500">
            {s.pages} pages ({Object.entries(s.pages_by_type).map(([t, n]) => `${n} ${t}`).join(', ')})
          </p>
          <PageTemplates pages={inv.pages} />
        </>
      )}
    </div>
  )
}

// ── Add project: a project spec in, a finished DEV-site change out ──────────

const SPEC_START = {
  title: '', slug: '', category: CATEGORIES[0], subtitle: '', description: '', body_html: '', stack_csv: '',
  github_url: '', download_url: '', download_label: '', theme: ''
}

function AddProject() {
  const [spec, setSpec] = useState(SPEC_START)
  const [slugTouched, setSlugTouched] = useState(false)
  const [motifs, setMotifs] = useState([])
  const [busy, setBusy] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const set = (k, v) => setSpec((cur) => ({ ...cur, [k]: v, ...(k === 'title' && !slugTouched ? { slug: slugify(v) } : {}) }))

  useEffect(() => { window.api.portfolio.imageMotifs().then(setMotifs).catch(() => {}) }, [])

  async function run(plan) {
    setBusy(plan ? 'plan' : 'create')
    setError(null)
    setResult(null)
    try {
      const clean = Object.fromEntries(Object.entries(spec).filter(([, v]) => String(v).trim() !== ''))
      setResult(await window.api.portfolio.addProject(clean, { plan }))
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(null)
    }
  }

  const input = 'rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-xs text-neutral-200 outline-none focus:border-blue-500'
  const row = (label, node, hint) => (
    <label className="flex flex-col gap-1"><span className="text-xs text-neutral-400">{label}</span>{node}{hint && <span className="text-[10px] text-neutral-600">{hint}</span>}</label>
  )

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div className="flex flex-col gap-3">
        <div>
          <h2 className="text-lg font-medium text-white">Add a project to the dev site</h2>
          <p className="text-xs text-neutral-500">
            Fill in what only a person writes. The pipeline does the rest by the site rules: generates a unique image, creates the page under its category,
            adds the card and manifest entry, rebuilds the hub, All Projects and sidebars, and checks the result. Dev site only; nothing is pushed.
          </p>
        </div>
        {row('Title', <input value={spec.title} onChange={(e) => set('title', e.target.value)} className={input} />)}
        {row('Slug (the URL ending)', <input value={spec.slug} onChange={(e) => { setSlugTouched(true); set('slug', e.target.value) }} className={input} />)}
        {row('Category', <select value={spec.category} onChange={(e) => set('category', e.target.value)} className={input}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>)}
        {row('Subtitle (the pink line)', <input value={spec.subtitle} onChange={(e) => set('subtitle', e.target.value)} className={input} />)}
        {row('Card description (one or two sentences)', <input value={spec.description} onChange={(e) => set('description', e.target.value)} className={input} />)}
        {row('Body (HTML paragraphs)', <textarea value={spec.body_html} onChange={(e) => set('body_html', e.target.value)} rows={6} spellCheck={false} className={field} />)}
        {row('Stack (comma-separated)', <input value={spec.stack_csv} onChange={(e) => set('stack_csv', e.target.value)} className={input} />)}
        {row('GitHub repository URL', <input value={spec.github_url} onChange={(e) => set('github_url', e.target.value)} placeholder="https://github.com/G-Eskayo/…" className={input} />, 'Leave empty if the project has no public repository: no button is added.')}
        {row('Download file URL', <input value={spec.download_url} onChange={(e) => set('download_url', e.target.value)} className={input} />, 'Optional. Shown after the GitHub button.')}
        {row('Image theme', <select value={spec.theme} onChange={(e) => set('theme', e.target.value)} className={input}><option value="">Plain pattern (choose another later in Images)</option>{motifs.filter((m) => m !== 'pattern').map((m) => <option key={m} value={m}>{m}</option>)}</select>)}
        <div className="flex items-center gap-2">
          <button onClick={() => run(true)} disabled={!!busy} className={button}>{busy === 'plan' ? 'Checking…' : 'Check (writes nothing)'}</button>
          <button onClick={() => run(false)} disabled={!!busy} className={primary}>{busy === 'create' ? 'Creating on the dev site (about two minutes)…' : 'Create on the dev site'}</button>
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-3">
        {error && <p className="text-xs text-red-400">{error}</p>}
        {result && !result.ok && (
          <ul className="text-xs">{(result.errors || ['Something went wrong']).map((m, i) => <li key={i} className="text-red-400">{m}</li>)}</ul>
        )}
        {result?.ok && result.dry_run && (
          <div className="rounded-lg border border-neutral-800 p-3 text-xs text-neutral-300">
            <p className="mb-1 text-emerald-400">Valid. Nothing was written.</p>
            <p>Page: <span className="font-mono">{result.url}</span></p>
            <p>Steps: {result.steps.join(' → ')}</p>
            <pre className="mt-2 overflow-auto rounded border border-neutral-800 bg-neutral-950 p-2 text-[11px]">{JSON.stringify(result.manifest_entry, null, 2)}</pre>
          </div>
        )}
        {result?.ok && !result.dry_run && (
          <div className="rounded-lg border border-emerald-900 p-3 text-xs text-neutral-300">
            <p className="mb-1 text-emerald-400">Created on the dev site.</p>
            <p>Page: <a href={`http://localhost:8080${result.url}`} target="_blank" rel="noreferrer" className="font-mono text-blue-400">{result.url}</a></p>
            {result.image?.warning && <p className="text-amber-400">Image: {result.image.warning} — choose another in the Images tab.</p>}
            <p>{(result.pages_regenerated || []).length} page rebuild step(s) ran.</p>
            {(result.findings_for_new_page || []).length > 0 ? (
              <ul className="mt-1">{result.findings_for_new_page.map((f, i) => <li key={i} className="text-amber-400">{f.rule}: {f.detail}</li>)}</ul>
            ) : <p className="text-emerald-400">The evaluation found nothing wrong with the new page.</p>}
            <p className="mt-2 text-neutral-500">Review: {result.review}</p>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Guide & rules ───────────────────────────────────────────────────────────

function GuideAndRules() {
  const [guide, setGuide] = useState('')
  const [preview, setPreview] = useState(false)
  const [rulesText, setRulesText] = useState('')
  const [effective, setEffective] = useState(null)
  const [gStatus, setGStatus] = useState(null)
  const [rStatus, setRStatus] = useState(null)

  const load = useCallback(async () => {
    setGuide(await window.api.portfolio.guide())
    const r = await window.api.portfolio.rules()
    setRulesText(JSON.stringify(r.overrides, null, 2))
    setEffective(r.effective)
  }, [])

  useEffect(() => {
    load().catch((e) => setGStatus({ error: errText(e) }))
  }, [load])

  async function saveGuide() {
    try {
      await window.api.portfolio.saveGuide(guide)
      setGStatus({ message: 'Guide saved' })
    } catch (e) {
      setGStatus({ error: errText(e) })
    }
  }

  async function saveRules() {
    const parsed = parseRulesText(rulesText)
    if (!parsed.ok) return setRStatus({ error: parsed.error })
    try {
      await window.api.portfolio.saveRules(parsed.value)
      setRStatus({ message: 'Rules saved — the next evaluation uses them' })
      await load()
    } catch (e) {
      setRStatus({ error: errText(e) })
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-medium text-white">Guide</h2>
          <button onClick={() => setPreview((p) => !p)} className={button}>
            {preview ? 'Edit' : 'Preview'}
          </button>
          <button onClick={saveGuide} className={primary}>
            Save
          </button>
          <Status state={gStatus} />
        </div>
        {preview ? (
          <div className="prose prose-invert max-w-none text-sm text-neutral-200">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{guide || '*The guide is empty.*'}</ReactMarkdown>
          </div>
        ) : (
          <textarea value={guide} onChange={(e) => setGuide(e.target.value)} rows={22} spellCheck={false} className={field} placeholder="How a Project Page is built: structure, components to use, what never to do…" />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-medium text-white">Design rules</h2>
          <button onClick={saveRules} className={primary}>
            Save overrides
          </button>
          <Status state={rStatus} />
        </div>
        <p className="text-xs text-neutral-500">
          These are the same rules the Evaluation checks. Only overrides are saved; anything you leave out keeps its default.
        </p>
        <textarea value={rulesText} onChange={(e) => setRulesText(e.target.value)} rows={8} spellCheck={false} className={field} />
        <h3 className="text-xs font-medium uppercase tracking-wide text-neutral-500">Effective rules (defaults + your overrides)</h3>
        <pre className="max-h-72 overflow-auto rounded-md border border-neutral-800 bg-neutral-950 p-3 text-xs text-neutral-300">
          {effective ? JSON.stringify(effective, null, 2) : 'Loading…'}
        </pre>
      </section>
    </div>
  )
}

// ── Evaluation ──────────────────────────────────────────────────────────────

function Evaluation() {
  const [result, setResult] = useState(undefined)
  const [running, setRunning] = useState(false)
  const [filter, setFilter] = useState('')
  const [status, setStatus] = useState(null)

  useEffect(() => {
    window.api.portfolio.latestEval().then(setResult).catch((e) => setStatus({ error: errText(e) }))
  }, [])

  async function run() {
    setRunning(true)
    setStatus(null)
    try {
      setResult(await window.api.portfolio.runEval())
    } catch (e) {
      setStatus({ error: errText(e) })
    } finally {
      setRunning(false)
    }
  }

  const groups = groupFindingsByRule(result?.findings, filter)
  const s = result?.summary

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-medium text-white">Evaluation</h2>
        <button onClick={run} disabled={running} className={primary}>
          {running ? 'Running (about a minute)…' : 'Run evaluation'}
        </button>
        <span className="text-xs text-neutral-500">last run: {formatRunTime(result?.generated_at)}</span>
        <Status state={status} />
      </div>
      <p className="text-xs text-neutral-500">
        Headless-browser checks against the dev site at {DEV_SITE}: no model, no tokens. Each element is measured against a rule, because the Other Projects pair changes on every view.
      </p>
      {result === undefined && <p className="text-sm text-neutral-500">Loading…</p>}
      {result === null && <p className="text-sm text-neutral-400">No evaluation has been run yet. Start the dev site, then run one.</p>}
      {s && (
        <>
          <div className="flex flex-wrap gap-2">
            <span className="rounded-md border border-neutral-800 px-3 py-1.5 text-xs text-neutral-300">
              {s.pages_checked} checked · {s.pages_with_findings} with findings · {s.clean_pages.length} clean
            </span>
            {Object.entries(s.by_rule).map(([rule, n]) => (
              <span key={rule} className="rounded-md border border-amber-900 bg-amber-950 px-3 py-1.5 text-xs text-amber-300">
                {n} × {rule}
              </span>
            ))}
            {result.findings.length === 0 && <span className="rounded-md border border-emerald-900 bg-emerald-950 px-3 py-1.5 text-xs text-emerald-300">All checks pass</span>}
          </div>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by page, rule or text…" className="w-full max-w-md rounded-md border border-neutral-700 bg-neutral-950 px-3 py-1.5 text-xs text-neutral-200 outline-none focus:border-blue-500" />
          {groups.map((g) => (
            <section key={g.rule} className="rounded-lg border border-neutral-800">
              <h3 className="border-b border-neutral-800 px-4 py-2 text-sm font-medium text-white">
                {g.rule} <span className="text-neutral-500">({g.items.length})</span>
              </h3>
              <ul className="divide-y divide-neutral-900">
                {g.items.slice(0, 40).map((f, i) => (
                  <li key={i} className="px-4 py-2 text-xs text-neutral-300">
                    <span className="mr-2 font-mono text-neutral-500">{f.page}</span>
                    {f.detail}
                  </li>
                ))}
                {g.items.length > 40 && <li className="px-4 py-2 text-xs text-neutral-500">…and {g.items.length - 40} more</li>}
              </ul>
            </section>
          ))}
        </>
      )}
    </div>
  )
}

// ── Images ──────────────────────────────────────────────────────────────────

// Full-size view of an image: Esc (or a click outside the picture) closes it.
function Lightbox({ src, caption, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div role="dialog" aria-label="Full-size image" onClick={onClose} className="fixed inset-0 z-50 flex cursor-zoom-out flex-col items-center justify-center gap-3 bg-black/85 p-6">
      <img src={src} alt={caption || ''} onClick={(e) => e.stopPropagation()} className="max-h-[85vh] max-w-full cursor-default rounded shadow-2xl" />
      <p className="text-xs text-neutral-300">{caption ? `${caption} · ` : ''}press Esc to close</p>
    </div>
  )
}

// One generated variant: its picture and a button to put it in use. Every image ever generated stays here, so a
// liked one is never lost to a re-roll.
function VariantTile({ slug, v, onChoose, onDelete, onZoom, busy }) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    let live = true
    window.api.portfolio.variantPreview(slug, v.motif, v.salt).then((d) => live && setSrc(d)).catch(() => {})
    return () => { live = false }
  }, [slug, v.motif, v.salt])
  return (
    <div className={`flex flex-col gap-1 rounded border p-1 ${v.chosen ? 'border-emerald-600' : 'border-neutral-800'}`}>
      {src ? <img src={src} alt="" onClick={() => onZoom(src, `${v.motif} #${v.salt}`)} className="h-16 w-full cursor-zoom-in rounded object-cover" /> : <div className="h-16 rounded bg-neutral-900" />}
      <div className="flex items-center gap-1">
        <span className="truncate text-[10px] text-neutral-400">{v.motif} #{v.salt}</span>
        {v.chosen
          ? <span className="ml-auto rounded bg-emerald-950 px-1.5 py-0.5 text-[10px] text-emerald-300">in use</span>
          : <>
              <button disabled={busy} onClick={() => onChoose(v)} className="ml-auto text-[10px] text-blue-400 hover:text-blue-300 disabled:opacity-50">use this</button>
              <button disabled={busy} onClick={() => onDelete(v)} title="Delete this image" className="text-[10px] text-neutral-500 hover:text-red-400 disabled:opacity-50">delete</button>
            </>}
      </div>
    </div>
  )
}

function ImageCard({ item, motifs, onGenerate }) {
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState(null)
  const [open, setOpen] = useState(false)
  const [variants, setVariants] = useState(null)
  const [theme, setTheme] = useState('default')
  const [zoom, setZoom] = useState(null)

  const loadVariants = useCallback(() => window.api.portfolio.imageVariants(item.slug).then(setVariants).catch((e) => setErr(errText(e))), [item.slug])

  useEffect(() => {
    let live = true
    if (item.generated.exists) window.api.portfolio.imagePreview(item.slug).then((d) => live && setPreview(d)).catch(() => {})
    return () => {
      live = false
    }
  }, [item.slug, item.generated.exists])

  useEffect(() => { if (open) loadVariants() }, [open, loadVariants])

  async function run(fn) {
    setBusy(true)
    setErr(null)
    setNote(null)
    try {
      await fn()
    } catch (e) {
      setErr(errText(e))
    } finally {
      setBusy(false)
    }
  }

  const generate = () => run(async () => {
    await window.api.portfolio.generateImage(item.slug)
    await onGenerate()
    setPreview(await window.api.portfolio.imagePreview(item.slug))
    if (open) await loadVariants()
  })

  const another = () => run(async () => {
    await window.api.portfolio.newImageVariant(item.slug, theme === 'default' ? null : theme)
    await loadVariants()
  })

  const choose = (v) => run(async () => {
    const r = await window.api.portfolio.chooseImageVariant(item.slug, v.motif, v.salt)
    if (r.warning) setNote(r.warning)
    await onGenerate()
    setPreview(await window.api.portfolio.imagePreview(item.slug))
    await loadVariants()
  })

  const remove = (v) => run(async () => {
    await window.api.portfolio.deleteImageVariant(item.slug, v.motif, v.salt)
    await loadVariants()
  })

  const closeZoom = useCallback(() => setZoom(null), [])

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-neutral-800 p-3">
      {zoom && <Lightbox src={zoom.src} caption={zoom.caption} onClose={closeZoom} />}
      <div className="flex items-center gap-2">
        <h3 className="truncate text-sm font-medium text-white">{item.title}</h3>
        {item.sharedWith.length > 0 && (
          <span title={`Also used by: ${item.sharedWith.join(', ')}`} className="shrink-0 rounded bg-amber-950 px-1.5 py-0.5 text-[10px] text-amber-300">
            shared ×{item.sharedWith.length + 1}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wide text-neutral-500">On the site now</p>
          <img src={`${DEV_SITE}${item.thumbnail}`} alt="" onClick={() => setZoom({ src: `${DEV_SITE}${item.thumbnail}`, caption: `${item.title} · on the site now` })} className="h-20 w-full cursor-zoom-in rounded border border-neutral-800 object-cover" />
        </div>
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wide text-neutral-500">Chosen{item.generated.style ? ` · ${item.generated.style}` : ''}</p>
          {preview ? <img src={preview} alt="" onClick={() => setZoom({ src: preview, caption: `${item.title} · chosen` })} className="h-20 w-full cursor-zoom-in rounded border border-neutral-800 object-cover" /> : <div className="flex h-20 items-center justify-center rounded border border-dashed border-neutral-800 text-[10px] text-neutral-600">not generated</div>}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {!item.generated.exists && <button onClick={generate} disabled={busy} className={button}>{busy ? 'Generating…' : 'Generate'}</button>}
        <button onClick={() => setOpen((v) => !v)} className={button}>{open ? 'Hide choices' : 'Choose image…'}</button>
        {err && <span className="text-xs text-red-400">{err}</span>}
        {note && <span className="text-xs text-amber-400">{note}</span>}
      </div>
      {open && (
        <div className="flex flex-col gap-2 rounded-md border border-neutral-800 bg-neutral-950 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <select value={theme} onChange={(e) => setTheme(e.target.value)} className="rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200">
              <option value="default">Theme: suggested{variants?.default_motif ? ` (${variants.default_motif})` : ''}</option>
              {(motifs || []).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <button onClick={another} disabled={busy} className={button}>{busy ? 'Generating…' : 'Generate another'}</button>
          </div>
          {variants === null ? <p className="text-xs text-neutral-500">Loading…</p> : variants.variants.length === 0 ? (
            <p className="text-xs text-neutral-500">Nothing generated yet.</p>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {variants.variants.map((v) => <VariantTile key={`${v.motif}-${v.salt}`} slug={item.slug} v={v} onChoose={choose} onDelete={remove} onZoom={(src, caption) => setZoom({ src, caption: `${item.title} · ${caption}` })} busy={busy} />)}
            </div>
          )}
          <p className="text-[10px] text-neutral-600">Every image you generate is kept. Pick any as the one in use; the choice stays until you pick another.</p>
        </div>
      )}
    </div>
  )
}

function Images() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)
  const [motifs, setMotifs] = useState([])
  const [applying, setApplying] = useState(false)
  const [applied, setApplied] = useState(null)
  const load = useCallback(() => window.api.portfolio.images().then(setItems).catch((e) => setError(errText(e))), [])
  useEffect(() => {
    load()
    window.api.portfolio.imageMotifs().then(setMotifs).catch(() => {})
  }, [load])

  if (error) return <p className="text-sm text-red-400">{error}</p>
  if (!items) return <p className="text-sm text-neutral-500">Loading images…</p>
  const shared = items.filter((i) => i.sharedWith.length > 0).length

  async function applyAll() {
    setApplying(true)
    setApplied(null)
    try {
      const r = await window.api.portfolio.applyImages()
      setApplied({ message: `Applied ${r.images} images to the dev site; ${r.manifest_changed} manifest thumbnail${r.manifest_changed === 1 ? '' : 's'} changed (review deploy/other-projects/manifest.json in the repo — nothing was pushed).` })
      await load()
    } catch (e) {
      setApplied({ error: errText(e) })
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-medium text-white">Images</h2>
        <span className="text-xs text-neutral-500">
          {items.length} projects · {shared} sharing a thumbnail · generated art is unique per project and keyed to its slug
        </span>
        <button onClick={applyAll} disabled={applying} className={`${primary} ml-auto`}>{applying ? 'Applying to the dev site (about a minute)…' : 'Apply chosen images to the dev site'}</button>
      </div>
      <Status state={applied} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((it) => (
          <ImageCard key={it.slug} item={it} motifs={motifs} onGenerate={load} />
        ))}
      </div>
    </div>
  )
}

// ── Hub ─────────────────────────────────────────────────────────────────────

export default function PortfolioHub() {
  const [tab, setTab] = useState('templates')
  return (
    <div className="flex h-full flex-col">
      <nav className="flex items-center gap-1 border-b border-neutral-800 px-6 pt-3">
        {SUBTABS.map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`rounded-t-md px-4 py-2 text-sm ${tab === id ? 'border-b-2 border-blue-500 text-white' : 'text-neutral-400 hover:text-neutral-200'}`}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto pb-2 text-[11px] text-neutral-600">dev site only · nothing here touches production</span>
      </nav>
      <div className="flex-1 overflow-auto p-6">
        {tab === 'templates' ? <Templates /> : tab === 'inventory' ? <Inventory /> : tab === 'add' ? <AddProject /> : tab === 'guide' ? <GuideAndRules /> : tab === 'evaluation' ? <Evaluation /> : <Images />}
      </div>
    </div>
  )
}
