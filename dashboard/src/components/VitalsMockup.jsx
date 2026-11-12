import '@fontsource/saira-condensed/600.css'
import '@fontsource/share-tech-mono/400.css'
import './vitals.css'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { needsYou, verdict, tightestBudget, columnSlice, KIND_ORDER } from '../lib/vitals_view.js'
import { LoopsView } from './LoopsPanel.jsx'
import { VitalsAccountsCard } from './VitalsAccountsCard.jsx'

// Vitals tab MOCK-UP for Gil's approval (marvin#873). Behind the "Vitals mock-up" switch on the Health tab; no tab is
// removed. Real data only: Health's live checks (the producer's copy when this Mac's is old), the loop registry, the
// Workshop's decisions, the plan's own meter, and the Accounts sweep. The live map (brain-map, Body and Work layout) is
// the background; pointing at a row lights its part there and dims the rest. Both placements are here for the review:
// the column over the map on the left, or below it. Spec: marvin-instance docs/plans/vitals-v5-2026-10-30.md.

const MAP_SRC = 'marvin-map://map/index.html?layout=work&embed=1'
const COLUMN_LIMIT = 12
const KIND_TITLE = { failure: 'Failures', missed: 'Missed purposes', decision: 'Decisions', paused: 'Paused' }
const KIND_WORD = { failure: 'Failure', missed: 'Missed purpose', decision: 'Decision', paused: 'Paused' }
const STEP_WORD = { notice: 'noticed', act: 'acted', verify: 'verified', told: 'told you' }
const STEP_MARK = { ok: '✓', failed: '✗', unknown: '·' }

export function ageText(s) {
  if (s == null) return 'age unknown'
  if (s < 90) return 'just now'
  const m = Math.round(s / 60)
  if (m < 90) return `${m} min ago`
  const h = Math.round(m / 60)
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`
}

function resetText(ms) {
  try { return new Date(ms).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit' }) } catch { return '' }
}

function markClass(row) {
  if (row.severity === 'unknown') return 'unknown'
  if (row.kind === 'failure') return `failure${row.severity === 'yellow' ? ' amber' : ''}`
  if (row.kind === 'missed') return `missed${row.severity === 'red' ? ' red' : ''}`
  return row.kind
}

function stateWord(row) {
  if (row.severity === 'unknown') return "Couldn't measure"
  return KIND_WORD[row.kind] + (row.severity === 'red' && row.kind !== 'failure' ? ' · blocking' : '')
}

export function FixLine({ row, onFix, busy }) {
  const f = row.fix || {}
  if (f.level === 'auto') return <span className="v-fix v-green">Auto: {f.done ? 'MARVIN fixed it' : 'MARVIN is fixing it'}{f.text ? ` · ${f.text}` : ''}</span>
  if (f.action && f.label) {
    const level = f.level === 'decision' ? 'Decision' : 'One tap'
    return (
      <span className="v-fix">
        <span className="v-dim">{level}:</span>
        <button type="button" className="v-btn" disabled={busy} onClick={(e) => { e.stopPropagation(); onFix?.(row) }}>{busy ? 'Working…' : f.label}</button>
      </span>
    )
  }
  if (f.text) return <span className="v-fix-text"><span className="v-dim">By hand: </span><span className="[overflow-wrap:anywhere]">{f.text}</span></span>
  return <span className="v-fix v-dim">No fix recorded yet (#836)</span>
}

function Steps({ steps }) {
  if (!steps) return null
  return (
    <span className="v-steps" aria-label="Loop steps">
      {['notice', 'act', 'verify', 'told'].map((k) => (
        <span key={k} className={steps[k] === 'failed' ? 'v-red' : steps[k] === 'ok' ? 'v-green' : 'v-dim'}>{STEP_MARK[steps[k]]} {STEP_WORD[k]}</span>
      ))}
    </span>
  )
}

export function Row({ row, selected, offMap, onPoint, onOpen, onFix, busy }) {
  return (
    <div role="button" tabIndex={0} aria-pressed={selected ? 'true' : 'false'} data-row={row.key} data-kind={row.kind} className="v-row"
      onMouseEnter={() => onPoint?.(row)} onMouseLeave={() => onPoint?.(null)} onFocus={() => onPoint?.(row)} onBlur={() => onPoint?.(null)}
      onClick={() => onOpen?.(row)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen?.(row) } }}>
      <span className={`v-mark ${markClass(row)}`} aria-hidden="true" />
      <span className="min-w-0">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="v-title">{row.title}</span>
          <span className={row.severity === 'red' ? 'v-red' : row.severity === 'unknown' ? '' : 'v-amber'}>{stateWord(row)}</span>
        </span>
        <span className="v-reason block">{row.reason}</span>
        <span className="v-dim block text-[12px]">
          {row.machine || 'Mac unknown'} · {ageText(row.ageS)}{row.stale ? ' · old' : ''}{row.parts?.length ? ` · ${row.parts.length} check${row.parts.length === 1 ? '' : 's'} under it` : ''}
          {offMap ? ' · not on the map yet' : ''}
        </span>
        {row.steps && <Steps steps={row.steps} />}
        <span className="block"><FixLine row={row} onFix={onFix} busy={busy} /></span>
      </span>
    </div>
  )
}

export function Verdict({ v, placement, onPlacement, onRefresh }) {
  const tone = v.stale ? 'v-amber' : v.healthy ? 'v-green' : 'v-red'
  const mark = v.stale ? 'unknown' : v.healthy ? 'ok' : 'failure'
  const b = v.budget
  const allUnknown = v.independence.every((k) => k.value == null)
  return (
    <div data-verdict={v.healthy ? 'healthy' : v.stale ? 'stale' : 'needs'} className="v-panel v-verdict">
      <span className="flex items-center gap-2">
        <span className={`v-mark ${mark}`} aria-hidden="true" />
        <span className={`v-display v-headline ${tone}`}>{v.headline}</span>
      </span>
      {v.detail && <span className="v-dim">{v.detail}</span>}
      <span className="flex items-center gap-2" data-flow={b ? b.line : 'none'}>
        <span className="v-display v-amber">Flow</span>
        {b ? (
          <>
            <span className="v-meter" aria-hidden="true"><i style={{ width: `${Math.min(100, b.pct)}%`, background: b.line === 'ok' ? undefined : 'var(--orange)' }} /><b style={{ left: '90%' }} /><b style={{ left: '99%' }} /></span>
            <span>{b.label} {Math.round(b.pct)}%{b.line !== 'ok' ? ` · ${b.line === 'hard' ? 'hard line' : 'soft line'}` : ''} · resets {resetText(b.resetsAt)}{b.pace ? ` · on pace for ${Math.min(b.pace, 999)}%` : ''}</span>
          </>
        ) : <span className="v-dim">not enough data yet</span>}
      </span>
      <span className="flex items-center gap-2" title={v.independence.map((k) => `${k.kind}: ${k.text}`).join('\n')}>
        <span className="v-display v-amber">Independence</span>
        <span className={allUnknown ? 'v-dim' : ''}>{allUnknown ? 'not enough data yet (#875)' : v.independence.filter((k) => k.value != null).map((k) => `${k.kind} ${k.text}`).join(' · ')}</span>
      </span>
      <span className={`ml-auto ${v.stale ? 'v-amber' : 'v-dim'}`} data-reading="">
        {v.from ? `${v.from}, ` : ''}as of {ageText(v.ageS)}{v.stale ? ' (old)' : ''}
      </span>
      <span className="flex items-center gap-2">
        <span className="v-switch" role="group" aria-label="Column placement">
          {['overlay', 'below'].map((p) => <button key={p} type="button" aria-pressed={placement === p ? 'true' : 'false'} onClick={() => onPlacement?.(p)}>{p === 'overlay' ? 'Over the map' : 'Below the map'}</button>)}
        </span>
        <button type="button" className="v-btn v-quiet" onClick={onRefresh}>Refresh</button>
      </span>
    </div>
  )
}

export function Column({ view, selectedKey, offMap, onPoint, onOpen, onFix, busyKey, limit = COLUMN_LIMIT, onShowAll, showWatching, onToggleWatching }) {
  const { shown, more } = columnSlice(view.rows, limit)
  const groups = KIND_ORDER.map((k) => [k, shown.filter((r) => r.kind === k)]).filter(([, list]) => list.length)
  return (
    <section data-column="" className="v-panel v-column" aria-label="What needs you">
      <h2 className="v-display px-[14px] pb-1 pt-2 text-[15px] text-white">What needs you <span className="v-dim">· worst first</span></h2>
      <div className="v-column-scroll">
        <div className="v-rows-wrap">
          {groups.map(([k, list]) => (
            <div key={k} data-group={k}>
              <div className="v-group v-display">{KIND_TITLE[k]} <span className="v-dim">({view.counts[k]})</span></div>
              <div className="v-rows">
                {list.map((r) => <Row key={r.key} row={r} selected={selectedKey === r.key} offMap={offMap(r)} onPoint={onPoint} onOpen={onOpen} onFix={onFix} busy={busyKey === r.key} />)}
              </div>
            </div>
          ))}
          {more > 0 && <button type="button" data-show-all="" className="v-btn m-3" onClick={onShowAll}>Show all {view.rows.length} ({more} more)</button>}
          {view.watching.length > 0 && (
            <div data-group="watching">
              <button type="button" className="v-group v-display w-full text-left" aria-expanded={showWatching ? 'true' : 'false'} onClick={onToggleWatching}>
                {showWatching ? '▾' : '▸'} Also watching <span className="v-dim">({view.watching.length}, degraded, not broken)</span>
              </button>
              {showWatching && <div className="v-rows">{view.watching.map((r) => <Row key={r.key} row={r} selected={selectedKey === r.key} offMap={offMap(r)} onPoint={onPoint} onOpen={onOpen} onFix={onFix} />)}</div>}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

export function Evidence({ row, offMap, onClose }) {
  if (!row) return null
  return (
    <section data-evidence={row.key} className="v-panel v-evidence" aria-label="Evidence">
      <div className="mb-2 flex items-start gap-2">
        <span className={`v-mark ${markClass(row)}`} aria-hidden="true" />
        <h3 className="v-display flex-1 text-[17px] text-white">{row.title}</h3>
        <button type="button" className="v-btn v-quiet" onClick={onClose} aria-label="Close the evidence">Close</button>
      </div>
      <dl>
        <dt>Why</dt><dd>{row.detail || row.reason}</dd>
        <dt>Reported by</dt><dd>{row.machine || 'unknown Mac'}, {ageText(row.ageS)}{row.stale ? ' (older than this check allows)' : ''}{row.checkedAt ? ` · ${row.checkedAt.slice(0, 16).replace('T', ' ')} UTC` : ''}</dd>
        <dt>Confidence</dt><dd>{row.confidence}</dd>
        {row.value != null && <><dt>Value</dt><dd>{typeof row.value === 'object' ? JSON.stringify(row.value).slice(0, 300) : String(row.value)}</dd></>}
        <dt>Trend</dt><dd className="v-dim">Not recorded yet: each sweep replaces the last (history comes with #836).</dd>
        <dt>Fix</dt><dd><FixLine row={row} />{row.fix?.derived && row.fix?.text ? <span className="v-dim block text-[12px]">Read from the check's own words until #836 gives every check a fix field.</span> : null}</dd>
        {row.steps && <><dt>Loop</dt><dd><Steps steps={row.steps} />{row.ticket ? <span className="v-dim"> · #{row.ticket}</span> : null}</dd></>}
        <dt>On the map</dt><dd>{offMap ? <span className="v-amber">Not on the map yet ({row.part || 'no part for this check'})</span> : row.part}</dd>
      </dl>
      {row.parts?.length > 0 && (
        <>
          <h4 className="v-display mt-2 text-[13px] v-amber">Checks under this loop</h4>
          {row.parts.map((p) => (
            <p key={p.key} className="mt-1 text-[12px]"><span className="text-white">{p.title}</span> <span className="v-dim">· {p.machine} · {ageText(p.ageS)}</span><br />{p.reason}</p>
          ))}
        </>
      )}
    </section>
  )
}

// The live map, framed. Spotlight messages go in once it has loaded; its answers say which parts it has.
function useMapFrame() {
  const frame = useRef(null)
  const [ready, setReady] = useState(false)
  const [found, setFound] = useState({}) // part id -> true | false
  useEffect(() => {
    const onMsg = (ev) => {
      const d = ev.data
      if (!frame.current || ev.source !== frame.current.contentWindow || !d || d.type !== 'marvin-map:spotlight-ack' || typeof d.id !== 'string') return
      setFound((f) => (f[d.id] === d.found ? f : { ...f, [d.id]: !!d.found }))
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])
  const spotlight = useCallback((id) => {
    try { frame.current?.contentWindow?.postMessage({ type: 'marvin-map:spotlight', id: id || null }, '*') } catch { /* frame gone */ }
  }, [])
  return { frame, ready, onLoad: () => setReady(true), found, spotlight }
}

export function VitalsView({ data, now = Date.now(), placement = 'overlay', onPlacement, onRefresh, onFix, busyKey, onRenew, map }) {
  const [selectedKey, setSelectedKey] = useState(null)
  const [pointed, setPointed] = useState(null)
  const [limit, setLimit] = useState(COLUMN_LIMIT)
  const [showWatching, setShowWatching] = useState(false)
  const view = useMemo(() => needsYou({ health: data.health, loops: data.loops, decisions: data.decisions, now }), [data, now])
  const v = verdict({ rows: view.rows, watching: view.watching, health: data.health, budget: tightestBudget(data.plan, now), now })
  const all = [...view.rows, ...view.watching]
  const selected = all.find((r) => r.key === selectedKey) || null
  const offMap = (r) => !r.part || map?.found?.[r.part] === false
  const target = (pointed || selected)?.part || null
  const ready = !!map?.ready
  useEffect(() => { if (ready) map.spotlight(target) }, [ready, target]) // eslint-disable-line react-hooks/exhaustive-deps
  // Ask the map once which parts it has, so a row can say "not on the map yet" before anyone points at it.
  useEffect(() => {
    if (!ready) return
    const parts = [...new Set(all.map((r) => r.part).filter(Boolean))]
    parts.forEach((p) => map.spotlight(p))
    map.spotlight(target)
  }, [ready, view]) // eslint-disable-line react-hooks/exhaustive-deps

  const nothing = view.rows.length === 0
  const column = !nothing && (
    <Column view={view} selectedKey={selectedKey} offMap={offMap} onPoint={setPointed} onOpen={(r) => setSelectedKey((k) => (k === r.key ? null : r.key))}
      onFix={onFix} busyKey={busyKey} limit={limit} onShowAll={() => setLimit(Infinity)} showWatching={showWatching} onToggleWatching={() => setShowWatching((s) => !s)} />
  )
  const evidence = selected && <Evidence row={selected} offMap={offMap(selected)} onClose={() => setSelectedKey(null)} />
  const verdictEl = <Verdict v={v} placement={placement} onPlacement={onPlacement} onRefresh={onRefresh} />
  const stage = (
    <div className="v-stage">
      {map ? <iframe ref={map.frame} title="MARVIN live map" src={MAP_SRC} className="v-map" onLoad={map.onLoad} /> : <div className="v-map" />}
      {!ready && <div className="v-map-wait">Loading the live map…</div>}
      <div className="v-raster" />
    </div>
  )
  return (
    <div className="vitals-root" data-placement={placement} data-rows={view.rows.length}>
      {placement === 'overlay' ? (
        <div className="v-overlay">
          {stage}
          <div className="v-hud">
            {verdictEl}
            {/* the evidence sits at the right edge, so the part it lights in the middle of the map stays in view */}
            <div className="v-hud-main">{column}<div className="v-spacer" />{evidence}</div>
          </div>
        </div>
      ) : (
        <div className="v-below">
          <div className="p-[14px] pb-0">{verdictEl}</div>
          <div className="p-[14px]">{stage}</div>
          {(column || evidence) && <div className="grid gap-[14px] px-[14px]" style={{ gridTemplateColumns: evidence ? 'minmax(0,1fr) minmax(0, 420px)' : '1fr' }}>{column}{evidence}</div>}
        </div>
      )}
      <div className="v-cards">
        <VitalsAccountsCard rows={data.accounts?.accounts || []} thisMachine={data.accounts?.thisMachine || null}
          checkedAge={data.accounts?.generatedAt ? ageText(Math.max(0, Math.round((now - Date.parse(data.accounts.generatedAt)) / 1000))) : null} onRenew={onRenew} now={now} />
        <div className="v-panel"><LoopsView view={data.loops || { loops: [] }} now={now} filter="open" /></div>
      </div>
    </div>
  )
}

function storage() {
  try { return globalThis.localStorage } catch { return null }
}
export const PLACEMENT_KEY = 'vitals.mockup.placement'

export default function VitalsMockup({ workshop = null, onOpenItem = null, api = typeof window !== 'undefined' ? window.api : null }) {
  const [data, setData] = useState({ health: null, loops: null, plan: null, accounts: null, decisions: [] })
  const [placement, setPlacementState] = useState(() => (storage()?.getItem(PLACEMENT_KEY) === 'below' ? 'below' : 'overlay'))
  const [busyKey, setBusyKey] = useState(null)
  const [now, setNow] = useState(Date.now())
  const map = useMapFrame()
  const decisions = workshop?.now?.sections?.yours || []
  const load = useCallback(async () => {
    const safe = (p) => Promise.resolve(p).catch(() => null)
    const [health, loops, plan, accounts] = await Promise.all([safe(api?.health?.status()), safe(api?.loops?.status()), safe(api?.vitals?.planMeter()), safe(api?.accounts?.list({ fresh: false }))])
    setData((d) => ({ ...d, health, loops, plan, accounts }))
    setNow(Date.now())
    // Then this Mac's accounts checked now (a few seconds), merged into the saved view, as Health's card does.
    const fresh = await safe(api?.accounts?.list({ fresh: true }))
    if (fresh) setData((d) => ({ ...d, accounts: fresh }))
  }, [api])
  useEffect(() => { load() }, [load])
  const setPlacement = (p) => { setPlacementState(p); try { storage()?.setItem(PLACEMENT_KEY, p) } catch { /* private window */ } }
  const onFix = async (row) => {
    const a = row.fix?.action
    if (!a) return
    if (a.type === 'item') return onOpenItem?.(a.repo, a.number, a.kind)
    if (a.type === 'loop' && api?.loops?.fix) {
      setBusyKey(row.key)
      try {
        const r = await api.loops.fix(a.id)
        if (r?.ok && r.how === 'open' && r.repo && r.number) onOpenItem?.(r.repo, r.number, 'ticket')
      } finally {
        setBusyKey(null)
        load()
      }
    }
  }
  const onRenew = api?.accounts?.renew ? (row) => api.accounts.renew(row.id, row.machine).catch(() => null) : null
  return <VitalsView data={{ ...data, decisions }} now={now} placement={placement} onPlacement={setPlacement} onRefresh={load} onFix={onFix} busyKey={busyKey} onRenew={onRenew} map={map} />
}
