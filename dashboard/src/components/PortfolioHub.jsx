import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { groupFindingsByRule, parseRulesText, previewDocument, nextComponentName, formatRunTime } from '../lib/portfolio.js'

// The Portfolio hub (CONTEXT.md "Dashboard app -- Portfolio tab"): the single place that defines how
// a portfolio Project Page is built -- guide + design rules, the component library, the evaluation
// results, and the images. Gil edits and refines it; MARVIN reads from it when building pages.
// DEV-ONLY: edits are confined to the portfolio repo's templates/; nothing here touches production.

const DEV_SITE = 'http://localhost:8080'
const SUBTABS = [
  ['components', 'Components'],
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

// ── Components ──────────────────────────────────────────────────────────────

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
  const [tab, setTab] = useState('components')
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
        {tab === 'components' ? <Components /> : tab === 'guide' ? <GuideAndRules /> : tab === 'evaluation' ? <Evaluation /> : <Images />}
      </div>
    </div>
  )
}
