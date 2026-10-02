import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  groupFindingsByRule, parseRulesText, previewDocument, nextComponentName, formatRunTime,
  initialData, buildOptions, fieldInputType, groupTemplates, slugify, projectDefaults, CATEGORIES, countByType
} from '../lib/portfolio.js'

// The Portfolio hub (CONTEXT.md "Dashboard app -- Portfolio tab"): the single place that defines how
// a portfolio Project Page is built -- guide + design rules, the component library, the evaluation
// results, and the images. Gil edits and refines it; MARVIN reads from it when building pages.
// DEV-ONLY: edits are confined to the portfolio repo's templates/; nothing here touches production.

const DEV_SITE = 'http://localhost:8080'
const SUBTABS = [
  ['templates', 'Templates'],
  ['inventory', 'Site inventory'],
  ['components', 'Edit templates'],
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

// ── Templates: plug-and-play forms ──────────────────────────────────────────

function TemplateRunner({ template, templates, head }) {
  const [data, setData] = useState(() => initialData(template))
  const [choices, setChoices] = useState({})
  const [result, setResult] = useState(null)

  useEffect(() => {
    setData(initialData(template))
    setChoices({})
  }, [template.id])

  useEffect(() => {
    const t = setTimeout(() => {
      window.api.portfolio.renderTemplate(template.id, data, buildOptions(choices)).then(setResult).catch((e) => setResult({ ok: false, errors: [errText(e)] }))
    }, 250)
    return () => clearTimeout(t)
  }, [template.id, data, choices])

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div className="flex flex-col gap-4">
        <div>
          <h2 className="text-lg font-medium text-white">{template.name}</h2>
          <p className="text-xs text-neutral-500">{template.description}</p>
        </div>
        <FieldInputs fields={template.fields} data={data} onChange={setData} />
        {Object.entries(template.slots || {}).map(([slot, spec]) => (
          <SlotPicker key={slot} slot={slot} spec={spec} templates={templates} value={choices[slot]} onChange={(v) => setChoices({ ...choices, [slot]: v })} />
        ))}
      </div>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex items-center gap-3">
          <h3 className="text-xs font-medium uppercase tracking-wide text-neutral-500">Result</h3>
          <CopyButton text={result?.html} label="Copy HTML" />
        </div>
        <Problems result={result} />
        <iframe title="template preview" sandbox="" srcDoc={previewDocument(result?.html || '', head)} className="h-64 w-full rounded-md border border-neutral-800 bg-white" />
        <textarea readOnly value={result?.html ?? ''} rows={10} spellCheck={false} className={field} />
      </div>
    </div>
  )
}

function NewProject({ templates, head }) {
  const [d, setD] = useState(projectDefaults)
  const [slugTouched, setSlugTouched] = useState(false)
  const [plan, setPlan] = useState(null)
  const set = (k, v) => setD((cur) => ({ ...cur, [k]: v, ...(k === 'title' && !slugTouched ? { slug: slugify(v) } : {}) }))

  useEffect(() => {
    const t = setTimeout(() => {
      window.api.portfolio.planProject(d).then(setPlan).catch((e) => setPlan({ ok: false, errors: [errText(e)] }))
    }, 300)
    return () => clearTimeout(t)
  }, [d])

  const input = 'rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-xs text-neutral-200 outline-none focus:border-blue-500'
  const row = (label, node) => (
    <label className="flex flex-col gap-1"><span className="text-xs text-neutral-400">{label}</span>{node}</label>
  )
  const actionsSpec = templates.find((t) => t.id === 'project-page')?.slots?.actions

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div className="flex flex-col gap-3">
        <div>
          <h2 className="text-lg font-medium text-white">New project</h2>
          <p className="text-xs text-neutral-500">One form produces the project page, its card and its manifest entry — nothing is hand-written, so it matches every other page.</p>
        </div>
        {row('Title', <input value={d.title} onChange={(e) => set('title', e.target.value)} className={input} />)}
        {row('Slug (the URL ending)', <input value={d.slug} onChange={(e) => { setSlugTouched(true); set('slug', e.target.value) }} className={input} />)}
        {row('Category', <select value={d.category} onChange={(e) => set('category', e.target.value)} className={input}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>)}
        {row('Subtitle (the pink line)', <input value={d.subtitle} onChange={(e) => set('subtitle', e.target.value)} className={input} />)}
        {row('Card description (one line)', <input value={d.description} onChange={(e) => set('description', e.target.value)} className={input} />)}
        {row('Body (HTML paragraphs)', <textarea value={d.body_html} onChange={(e) => set('body_html', e.target.value)} rows={5} className={field} />)}
        {row('Hero image URL', <input value={d.hero_image_url} onChange={(e) => set('hero_image_url', e.target.value)} className={input} />)}
        {row('Thumbnail URL', <input value={d.thumbnail} onChange={(e) => set('thumbnail', e.target.value)} className={input} />)}
        {row('Stack (comma-separated)', <input value={d.stack_csv} onChange={(e) => set('stack_csv', e.target.value)} className={input} />)}
        {actionsSpec && <SlotPicker slot="actions" spec={actionsSpec} templates={templates} value={d.actions} onChange={(v) => set('actions', v)} />}
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <Problems result={plan ? { errors: plan.ok ? [] : plan.errors, warnings: plan.warnings } : null} />
        {plan?.ok && (
          <>
            <div>
              <div className="mb-1 flex items-center gap-3"><h3 className="text-xs font-medium uppercase tracking-wide text-neutral-500">Card (as it appears on hub pages)</h3><CopyButton text={plan.card_html} /></div>
              <iframe title="card preview" sandbox="" srcDoc={previewDocument(plan.card_html, head)} className="h-56 w-full rounded-md border border-neutral-800 bg-white" />
            </div>
            <div>
              <div className="mb-1 flex items-center gap-3"><h3 className="text-xs font-medium uppercase tracking-wide text-neutral-500">Project page content</h3><CopyButton text={plan.page_html} /></div>
              <textarea readOnly value={plan.page_html} rows={7} className={field} />
            </div>
            <div>
              <div className="mb-1 flex items-center gap-3"><h3 className="text-xs font-medium uppercase tracking-wide text-neutral-500">Manifest entry</h3><CopyButton text={JSON.stringify(plan.manifest_entry, null, 2)} /></div>
              <textarea readOnly value={JSON.stringify(plan.manifest_entry, null, 2)} rows={8} className={field} />
              <p className="mt-1 text-[11px] text-neutral-500">Add this to deploy/other-projects/manifest.json as a reviewed repo change — it lives in deploy/, which this tab never writes.</p>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Templates() {
  const [templates, setTemplates] = useState(null)
  const [selected, setSelected] = useState(null)
  const [head, setHead] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    window.api.portfolio.templates().then((t) => { setTemplates(t); setSelected((cur) => cur ?? 'project-page') }).catch((e) => setError(errText(e)))
    window.api.portfolio.previewHead().then(setHead).catch(() => {})
  }, [])

  if (error) return <p className="text-sm text-red-400">Could not load templates: {error}</p>
  if (!templates) return <p className="text-sm text-neutral-500">Loading templates…</p>
  const current = templates.find((t) => t.id === selected)

  return (
    <div className="grid grid-cols-[230px_1fr] gap-6">
      <aside className="flex flex-col gap-1">
        <button onClick={() => setSelected('__new')} className={`mb-2 rounded-md px-3 py-2 text-left text-sm font-medium ${selected === '__new' ? 'bg-blue-600 text-white' : 'border border-blue-700 text-blue-300 hover:bg-blue-950'}`}>
          + New project
        </button>
        {groupTemplates(templates).map((g) => (
          <div key={g.kind} className="mb-2">
            <h4 className="px-1 pb-1 text-[10px] font-medium uppercase tracking-wide text-neutral-500">{g.kind === 'page' ? 'Pages' : g.kind === 'component' ? 'Components' : 'Buttons'}</h4>
            {g.items.map((t) => (
              <button key={t.id} onClick={() => setSelected(t.id)} className={`block w-full rounded-md border px-3 py-2 text-left text-sm ${selected === t.id ? 'border-blue-500 bg-blue-950 text-white' : 'border-transparent text-neutral-300 hover:border-neutral-700'}`}>
                {t.name}
              </button>
            ))}
          </div>
        ))}
      </aside>
      <section className="min-w-0">
        {selected === '__new' ? <NewProject templates={templates} head={head} /> : current ? <TemplateRunner key={current.id} template={current} templates={templates} head={head} /> : null}
      </section>
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

function ButtonVariants({ variants }) {
  const [open, setOpen] = useState(null)
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {variants.map((v) => (
        <div key={v.id} className="rounded-lg border border-neutral-800 p-3">
          <div className="mb-2 flex items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-[10px] ${v.kind === 'github-link' ? 'bg-purple-950 text-purple-300' : 'bg-blue-950 text-blue-300'}`}>{v.kind === 'github-link' ? 'GitHub link' : 'Button'}</span>
            <span className="text-xs text-neutral-300">×{v.count} on {v.pages.length} page{v.pages.length === 1 ? '' : 's'}</span>
          </div>
          <div className="rounded bg-white p-3"><Shot rel={v.screenshot} className="max-h-16 max-w-full" /></div>
          <p className="mt-2 truncate text-xs text-neutral-400">{v.texts.join(' · ') || '(no text)'}</p>
          <p className="truncate font-mono text-[10px] text-neutral-600">{v.classes || '(no class)'} · {v.styles.fontSize} {v.styles.textTransform}</p>
          <button onClick={() => setOpen(open === v.id ? null : v.id)} className="mt-2 text-xs text-blue-400 hover:text-blue-300">{open === v.id ? 'hide details' : 'details'}</button>
          {open === v.id && (
            <div className="mt-2 flex flex-col gap-2">
              <pre className="max-h-32 overflow-auto rounded border border-neutral-800 bg-neutral-950 p-2 text-[10px] text-neutral-300">{v.example.html}</pre>
              <p className="text-[10px] text-neutral-500">Used on: {v.pages.slice(0, 12).join(', ')}{v.pages.length > 12 ? ` …+${v.pages.length - 12}` : ''}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  )
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
  const [view, setView] = useState('buttons')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { window.api.portfolio.inventory().then(setInv).catch((e) => setError(errText(e))) }, [])

  async function refresh() {
    setBusy(true); setError(null)
    try { setInv(await window.api.portfolio.refreshInventory()) } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  const s = inv?.summary
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-medium text-white">What is actually on the website</h2>
        <button onClick={refresh} disabled={busy} className={primary}>{busy ? 'Crawling the dev site (about a minute)…' : 'Refresh from dev site'}</button>
        <span className="text-xs text-neutral-500">crawled: {formatRunTime(inv?.generated_at)}</span>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
      {inv === undefined && <p className="text-sm text-neutral-500">Loading…</p>}
      {inv === null && <p className="text-sm text-neutral-400">Nothing crawled yet. Start the dev site, then refresh.</p>}
      {s && (
        <>
          <p className="text-xs text-neutral-500">
            {s.pages} pages ({Object.entries(s.pages_by_type).map(([t, n]) => `${n} ${t}`).join(', ')}) · {s.button_variants} button look{s.button_variants === 1 ? '' : 's'} + {s.github_link_variants} GitHub-link looks across {s.button_instances} instances
          </p>
          <div className="flex gap-2">
            {[['buttons', `Buttons & links (${inv.buttons.length})`], ['pages', `Page templates (${inv.pages.length})`]].map(([id, label]) => (
              <button key={id} onClick={() => setView(id)} className={`rounded-md border px-3 py-1.5 text-xs ${view === id ? 'border-blue-500 bg-blue-950 text-white' : 'border-neutral-800 text-neutral-400 hover:border-neutral-600'}`}>{label}</button>
            ))}
          </div>
          {view === 'buttons' ? <ButtonVariants variants={inv.buttons} /> : <PageTemplates pages={inv.pages} />}
        </>
      )}
    </div>
  )
}

// ── Edit templates (the raw component files) ────────────────────────────────

function Components() {
  const [list, setList] = useState(null)
  const [selected, setSelected] = useState(null)
  const [html, setHtml] = useState('')
  const [notes, setNotes] = useState('')
  const [head, setHead] = useState('')
  const [newName, setNewName] = useState('')
  const [status, setStatus] = useState(null)

  const load = useCallback(async (keep) => {
    const items = await window.api.portfolio.components()
    setList(items)
    const pick = items.find((c) => c.name === keep) || items[0]
    if (pick) {
      setSelected(pick.name)
      setHtml(pick.html)
      setNotes(pick.notes)
    }
  }, [])

  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    load().catch((e) => setLoadError(errText(e)))
    window.api.portfolio.previewHead().then(setHead).catch(() => {})
  }, [load])

  function choose(c) {
    setSelected(c.name)
    setHtml(c.html)
    setNotes(c.notes)
    setStatus(null)
  }

  async function save() {
    try {
      await window.api.portfolio.saveComponent(selected, html, notes)
      setStatus({ message: `Saved ${selected}` })
      await load(selected)
    } catch (e) {
      setStatus({ error: errText(e) })
    }
  }

  async function create() {
    const name = nextComponentName(newName)
    if (!name) return setStatus({ error: 'Type a name first' })
    try {
      await window.api.portfolio.createComponent(name, '<!-- new component -->\n', '')
      setNewName('')
      await load(name)
      setStatus({ message: `Created ${name}` })
    } catch (e) {
      setStatus({ error: errText(e) })
    }
  }

  // A failed load must say so -- "Loading…" forever would hide the reason.
  if (loadError) return <p className="text-sm text-red-400">Could not load components: {loadError}</p>
  if (!list) return <p className="text-sm text-neutral-500">Loading components…</p>

  return (
    <div className="grid grid-cols-[220px_1fr] gap-6">
      <aside className="flex flex-col gap-2">
        {list.length === 0 && <p className="text-xs text-neutral-500">No components yet. Create the first one below.</p>}
        {list.map((c) => (
          <button
            key={c.name}
            onClick={() => choose(c)}
            className={`rounded-md border px-3 py-2 text-left text-sm ${
              selected === c.name ? 'border-blue-500 bg-blue-950 text-white' : 'border-neutral-800 text-neutral-300 hover:border-neutral-600'
            }`}
          >
            {c.name}
          </button>
        ))}
        <div className="mt-3 flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="new-component"
            className="min-w-0 flex-1 rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-xs text-neutral-200 outline-none focus:border-blue-500"
          />
          <button onClick={create} className={button}>
            Add
          </button>
        </div>
      </aside>

      {selected ? (
        <section className="flex min-w-0 flex-col gap-4">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-medium text-white">{selected}</h2>
            <button onClick={save} className={primary}>
              Save
            </button>
            <Status state={status} />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral-500">Live preview (the dev site's own styles)</h3>
            <iframe title="component preview" sandbox="" srcDoc={previewDocument(html, head)} className="h-40 w-full rounded-md border border-neutral-800 bg-white" />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral-500">HTML</h3>
            <textarea value={html} onChange={(e) => setHtml(e.target.value)} rows={9} spellCheck={false} className={field} />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral-500">Notes — when to use it, what to fill in</h3>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} className={field} />
          </div>
        </section>
      ) : (
        <p className="text-sm text-neutral-500">Select or create a component.</p>
      )}
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

function ImageCard({ item, onGenerate }) {
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let live = true
    if (item.generated.exists) window.api.portfolio.imagePreview(item.slug).then((d) => live && setPreview(d)).catch(() => {})
    return () => {
      live = false
    }
  }, [item.slug, item.generated.exists])

  async function generate() {
    setBusy(true)
    setErr(null)
    try {
      await window.api.portfolio.generateImage(item.slug)
      await onGenerate()
      setPreview(await window.api.portfolio.imagePreview(item.slug))
    } catch (e) {
      setErr(errText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-neutral-800 p-3">
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
          <p className="mb-1 text-[10px] uppercase tracking-wide text-neutral-500">Current</p>
          <img src={`${DEV_SITE}${item.thumbnail}`} alt="" className="h-20 w-full rounded border border-neutral-800 object-cover" />
        </div>
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wide text-neutral-500">Generated{item.generated.style ? ` · ${item.generated.style}` : ''}</p>
          {preview ? <img src={preview} alt="" className="h-20 w-full rounded border border-neutral-800 object-cover" /> : <div className="flex h-20 items-center justify-center rounded border border-dashed border-neutral-800 text-[10px] text-neutral-600">not generated</div>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button onClick={generate} disabled={busy} className={button}>
          {busy ? 'Generating…' : item.generated.exists ? 'Regenerate' : 'Generate'}
        </button>
        {err && <span className="text-xs text-red-400">{err}</span>}
      </div>
    </div>
  )
}

function Images() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)
  const load = useCallback(() => window.api.portfolio.images().then(setItems).catch((e) => setError(errText(e))), [])
  useEffect(() => {
    load()
  }, [load])

  if (error) return <p className="text-sm text-red-400">{error}</p>
  if (!items) return <p className="text-sm text-neutral-500">Loading images…</p>
  const shared = items.filter((i) => i.sharedWith.length > 0).length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-medium text-white">Images</h2>
        <span className="text-xs text-neutral-500">
          {items.length} projects · {shared} sharing a thumbnail · generated art is unique per project and keyed to its slug
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((it) => (
          <ImageCard key={it.slug} item={it} onGenerate={load} />
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
        {tab === 'templates' ? <Templates /> : tab === 'inventory' ? <Inventory /> : tab === 'components' ? <Components /> : tab === 'guide' ? <GuideAndRules /> : tab === 'evaluation' ? <Evaluation /> : <Images />}
      </div>
    </div>
  )
}
