import { useMemo, useState } from 'react'
import { GROUPS, RANGES, mergeHours, mergeTop, lastHourTotals, timeline, allowanceTone, slotDetail, readRange, writeRange } from '../lib/github_view.js'

// Every gh call on each Mac goes through the GitHub gate (~/.agents/bin/gh), which logs who called and what GitHub said.
// Both Macs share ONE hourly allowance (5,000 GraphQL points), so this is where to see what spends it and fix the top spender.
const GROUP_STYLE = {
  dashboard: ['#3b82f6', 'Dashboard'],
  pipeline: ['#10b981', 'Pipeline'],
  tests: ['#f59e0b', 'Tests'],
  health: ['#a78bfa', 'Health checks'],
  people: ['#e5e5e5', 'You (terminal, Claude)'],
  other: ['#737373', 'Other']
}

function Stat({ label, value, hint, tone }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      <p className={`text-xl font-semibold ${tone || 'text-white'}`}>{value}</p>
      {hint && <p className="text-[11px] text-neutral-600">{hint}</p>}
    </div>
  )
}

const TONE_FILL = { green: '#10b981', amber: '#f59e0b', red: '#ef4444', out: '#ef4444' }
const W = 760

function storage() {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

function labelStep(n) {
  return Math.max(1, Math.ceil(n / 8))
}

// One invisible column per slot over both charts, so hover and click mean the same hour in each.
function Columns({ n, height, onHover, onPick }) {
  const bw = W / Math.max(1, n)
  return Array.from({ length: n }, (_, i) => (
    <rect key={i} x={i * bw} y="0" width={bw} height={height} fill="transparent" style={{ cursor: 'pointer' }}
      onMouseEnter={() => onHover(i)} onMouseLeave={() => onHover(null)} onClick={() => onPick(i)} />
  ))
}

function Highlight({ i, n, height }) {
  if (i == null) return null
  const bw = W / Math.max(1, n)
  return <rect x={i * bw} y="0" width={bw} height={height} fill="#ffffff" opacity="0.08" pointerEvents="none" />
}

// Top: the lowest the shared allowance got in each slot. No reading = a gap, never a guessed 0% or 100%.
export function LowPointBars({ slots, active, onHover, onPick }) {
  const H = 90, n = slots.length, bw = W / Math.max(1, n)
  const y = (v) => H - v * H
  return (
    <svg viewBox={`0 0 ${W} ${H + 4}`} className="w-full" role="img" aria-label="Lowest GitHub GraphQL allowance left in each hour">
      <Highlight i={active} n={n} height={H} />
      {slots.map((s, i) => {
        const tone = allowanceTone(s.budgetMin)
        if (tone === 'none') return <rect key={s.key} data-gap="1" x={i * bw + bw / 2 - 0.5} y={H - 2} width="1" height="2" fill="#404040" pointerEvents="none" />
        if (tone === 'out') return <circle key={s.key} data-out="1" cx={i * bw + bw / 2} cy={H - 3} r={Math.min(3, Math.max(1.5, bw / 3))} fill="#ef4444" pointerEvents="none" />
        return <rect key={s.key} data-tone={tone} x={i * bw + 1} y={y(s.budgetMin)} width={Math.max(1, bw - 2)} height={H - y(s.budgetMin)} fill={TONE_FILL[tone]} pointerEvents="none" />
      })}
      <line x1="0" x2={W} y1={H} y2={H} stroke="#262626" pointerEvents="none" />
      <line data-floor="1" x1="0" x2={W} y1={y(0.2)} y2={y(0.2)} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth="1" pointerEvents="none" />
      <Columns n={n} height={H} onHover={onHover} onPick={onPick} />
    </svg>
  )
}

// Bottom: calls per slot, stacked by who made them, on the same columns as the bars above.
export const busiest = (slots) => Math.max(0, ...slots.map((s) => s.total))

export function CallBars({ slots, active, onHover, onPick }) {
  const H = 120, n = slots.length, bw = W / Math.max(1, n)
  const max = Math.max(1, ...slots.map((s) => s.total))
  const step = labelStep(n)
  return (
    <svg viewBox={`0 0 ${W} ${H + 16}`} className="w-full" role="img" aria-label="GitHub calls in each hour, by who made them">
      <Highlight i={active} n={n} height={H} />
      {slots.map((s, i) => {
        let top = H
        return (
          <g key={s.key} pointerEvents="none">
            {GROUPS.map((g) => {
              const hgt = (s.groups[g] / max) * H
              top -= hgt
              return hgt > 0 ? <rect key={g} x={i * bw + 1} y={top} width={Math.max(1, bw - 2)} height={hgt} fill={GROUP_STYLE[g][0]} /> : null
            })}
            {s.refused > 0 && <rect x={i * bw + 1} y={H + 1} width={Math.max(1, bw - 2)} height="2" fill="#ef4444" />}
            {i % step === 0 && <text x={i * bw} y={H + 13} fontSize="9" fill="#737373">{s.label}</text>}
          </g>
        )
      })}
      <Columns n={n} height={H} onHover={onHover} onPick={onPick} />
    </svg>
  )
}

function Detail({ slot, pinned }) {
  if (!slot) return null
  const d = slotDetail(slot)
  return (
    <div className="mt-2 rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs">
      <p className="text-neutral-200">{pinned ? '▸ ' : ''}{d.headline}{d.refused ? <span className="text-red-400"> · {d.refused} refused by GitHub</span> : null}{d.deferred ? <span className="text-amber-300"> · {d.deferred} held by the gate</span> : null}</p>
      {d.split.length > 0 && <p className="mt-0.5 text-neutral-400">{d.split.join(' · ')}</p>}
      {d.callers.length > 0 && <p className="mt-0.5 font-mono text-neutral-500">{d.callers.join(' · ')}</p>}
    </div>
  )
}

export default function GithubView({ machines, which }) {
  const [range, setRange] = useState(() => readRange(storage()))
  const [hover, setHover] = useState(null)
  const [picked, setPicked] = useState(null)
  const hours = useMemo(() => mergeHours(machines, which), [machines, which])
  const tl = useMemo(() => timeline(machines, which, range), [machines, which, range])
  const top = useMemo(() => mergeTop(machines, which), [machines, which])
  const last = useMemo(() => lastHourTotals(machines, which), [machines, which])
  if (hours.length === 0) {
    return <p className="p-2 text-neutral-500">No GitHub calls logged for {which === 'all' ? 'either machine' : which} yet. The gate (~/.agents/bin/gh) logs them once installed (bin/install-gh-gate.sh).</p>
  }
  const now = (machines || []).map((m) => m.github?.latest_budget).filter((b) => b && b.graphql != null).sort((a, b) => b.at - a.at)[0]
  const left = now ? Math.round(now.graphql * 100) : null
  const pickRange = (r) => { setRange(r); writeRange(storage(), r); setPicked(null); setHover(null) }
  const pick = (i) => setPicked((p) => (p === i ? null : i))
  const active = hover ?? picked
  const shown = tl.slots[active ?? tl.slots.length - 1]
  const per = tl.slotHours === 1 ? 'hour' : `${tl.slotHours} hours`
  const day = hours.slice(-24).reduce((a, h) => ({ total: a.total + h.total, refused: a.refused + h.refused, deferred: a.deferred + h.deferred }), { total: 0, refused: 0, deferred: 0 })
  return (
    <div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="GraphQL allowance left" value={left == null ? '—' : `${left}%`} tone={left == null ? undefined : left < 20 ? 'text-red-400' : left < 50 ? 'text-amber-300' : 'text-emerald-400'}
          hint={now ? `of 5,000 an hour, shared by both Macs · read ${new Date(now.at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'no reading yet'} />
        <Stat label="Calls this hour" value={last.total.toLocaleString()} hint={`${day.total.toLocaleString()} in the last 24 h`} />
        <Stat label="Refused by GitHub" value={last.refused} tone={last.refused ? 'text-red-400' : undefined} hint={`${day.refused} in the last 24 h`} />
        <Stat label="Held back by the gate" value={last.deferred} tone={last.deferred ? 'text-amber-300' : undefined} hint={`${day.deferred} in the last 24 h · cooldowns and the 20% floor`} />
      </div>

      <section className="mt-6">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-medium text-neutral-200">Allowance: lowest left each {per}</h3>
          <div className="ml-auto flex gap-1" role="group" aria-label="Time range">
            {Object.keys(RANGES).map((r) => (
              <button key={r} aria-pressed={range === r} onClick={() => pickRange(r)}
                className={`rounded px-2 py-0.5 text-xs ${range === r ? 'bg-neutral-700 text-white' : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'}`}>{r}</button>
            ))}
          </div>
        </div>
        <p className="mb-2 text-xs text-neutral-600">Bar height is the share left (full height = 100%). GitHub refills the GraphQL allowance every hour, shared by both Macs. Each bar is how low it got: green is fine, amber is getting close, red is under the 20% floor, a red dot means it ran out. A gap means no reading.</p>
        <LowPointBars slots={tl.slots} active={active} onHover={setHover} onPick={pick} />
        <p className="mt-1 flex items-center gap-1.5 text-[11px] text-amber-400/80"><span className="inline-block w-4 border-t border-dashed border-amber-500" />20% floor: background work waits below this line</p>
      </section>

      <section className="mt-3">
        <div className="flex items-baseline gap-3">
          <h3 className="text-sm font-medium text-neutral-200">Calls per {per}, by who made them</h3>
          <span className="ml-auto text-[11px] text-neutral-600">tallest bar: {busiest(tl.slots).toLocaleString()} calls</span>
        </div>
        <div className="mb-2 flex flex-wrap gap-3 text-xs text-neutral-400">
          {GROUPS.map((g) => <span key={g} className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: GROUP_STYLE[g][0] }} />{GROUP_STYLE[g][1]}</span>)}
          <span className="flex items-center gap-1"><span className="inline-block h-1 w-2.5 bg-red-500" />refused by GitHub</span>
        </div>
        <CallBars slots={tl.slots} active={active} onHover={setHover} onPick={pick} />
        <Detail slot={shown} pinned={picked != null && hover == null} />
        <p className="mt-1 text-[11px] text-neutral-600">Point at a bar to see that {per === 'hour' ? 'hour' : 'stretch'}; click to keep it.</p>
      </section>

      <section className="mt-6">
        <h3 className="text-sm font-medium text-neutral-200">Top callers, last 24 hours</h3>
        <p className="mb-2 text-xs text-neutral-600">The program that ran gh, and what it asked for most. The top row is the first thing to optimize.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-neutral-500">
              <tr><th className="py-1 pr-3">Caller</th><th className="pr-3">Machine</th><th className="pr-3">Kind</th><th className="pr-3 text-right">Calls</th><th className="pr-3 text-right">Refused</th><th className="pr-3 text-right">Held</th><th>Mostly</th></tr>
            </thead>
            <tbody className="text-neutral-300">
              {top.map((t) => (
                <tr key={`${t.machine}|${t.caller}`} className="border-t border-neutral-800">
                  <td className="py-1 pr-3 font-mono">{t.caller}</td>
                  <td className="pr-3 text-neutral-400">{t.machine}</td>
                  <td className="pr-3"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: GROUP_STYLE[t.group]?.[0] }} /> {GROUP_STYLE[t.group]?.[1] || t.group}</td>
                  <td className="pr-3 text-right">{t.calls.toLocaleString()}</td>
                  <td className={`pr-3 text-right ${t.refused ? 'text-red-400' : 'text-neutral-600'}`}>{t.refused}</td>
                  <td className={`pr-3 text-right ${t.deferred ? 'text-amber-300' : 'text-neutral-600'}`}>{t.deferred}</td>
                  <td className="text-neutral-400">{(t.commands || []).map((c) => `${c.cmd} ${c.calls}`).join(' · ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
