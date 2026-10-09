import { useMemo } from 'react'
import { GROUPS, mergeHours, mergeBudget, mergeTop, lastHourTotals } from '../lib/github_view.js'

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
const FLOOR = 0.2 // below this the gate holds background work back (bin/gh BUDGET_FLOOR)

function Stat({ label, value, hint, tone }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      <p className={`text-xl font-semibold ${tone || 'text-white'}`}>{value}</p>
      {hint && <p className="text-[11px] text-neutral-600">{hint}</p>}
    </div>
  )
}

// GraphQL allowance left over time (both Macs' readings; it is one account-wide allowance).
function BudgetLine({ points }) {
  const W = 760, H = 120
  if (points.length < 2) return <p className="text-xs text-neutral-600">Not enough readings yet. The gate records one every couple of minutes while background jobs run.</p>
  const t0 = points[0].at, t1 = points[points.length - 1].at, span = Math.max(1, t1 - t0)
  const x = (t) => ((t - t0) / span) * W
  const y = (v) => H - v * H
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.at).toFixed(1)},${y(p.graphql).toFixed(1)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H + 16}`} className="w-full" role="img" aria-label="GitHub GraphQL allowance left over time">
      <line x1="0" x2={W} y1={y(FLOOR)} y2={y(FLOOR)} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth="1" />
      <text x="4" y={y(FLOOR) - 3} fontSize="9" fill="#f59e0b">20%: background work waits below this</text>
      <path d={d} fill="none" stroke="#3b82f6" strokeWidth="1.5" />
      {points.filter((p) => p.graphql === 0).map((p) => <circle key={p.at} cx={x(p.at)} cy={y(0)} r="2.5" fill="#ef4444"><title>allowance used up</title></circle>)}
      <text x="0" y={H + 13} fontSize="9" fill="#737373">{new Date(t0 * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}</text>
      <text x={W} y={H + 13} fontSize="9" fill="#737373" textAnchor="end">{new Date(t1 * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</text>
      <text x={W} y="9" fontSize="9" fill="#737373" textAnchor="end">100%</text>
    </svg>
  )
}

// GitHub calls per hour, stacked by who made them; red tick = GitHub refused calls that hour.
function HourBars({ hours }) {
  const max = Math.max(1, ...hours.map((h) => h.total))
  const W = 760, H = 140, bw = W / Math.max(1, hours.length)
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img" aria-label="GitHub calls per hour by caller group">
      {hours.map((h, i) => {
        let top = H
        return (
          <g key={h.hour}>
            <title>{`${h.hour.replace('T', ' ')}: ${h.total} calls (${GROUPS.filter((g) => h.groups[g]).map((g) => `${GROUP_STYLE[g][1]} ${h.groups[g]}`).join(', ')})${h.refused ? `, ${h.refused} refused by GitHub` : ''}${h.deferred ? `, ${h.deferred} held by the gate` : ''}`}</title>
            {GROUPS.map((g) => {
              const hgt = (h.groups[g] / max) * H
              top -= hgt
              return hgt > 0 ? <rect key={g} x={i * bw + 1} y={top} width={Math.max(1, bw - 2)} height={hgt} fill={GROUP_STYLE[g][0]} /> : null
            })}
            {h.refused > 0 && <rect x={i * bw + 1} y={H + 2} width={Math.max(1, bw - 2)} height="3" fill="#ef4444" />}
            {i % 6 === 0 && <text x={i * bw} y={H + 15} fontSize="9" fill="#737373">{h.hour.slice(11, 16)}</text>}
          </g>
        )
      })}
      <text x={W} y="10" fontSize="9" fill="#737373" textAnchor="end">peak {max}/h</text>
    </svg>
  )
}

export default function GithubView({ machines, which }) {
  const hours = useMemo(() => mergeHours(machines, which), [machines, which])
  const budget = useMemo(() => mergeBudget(machines), [machines])
  const top = useMemo(() => mergeTop(machines, which), [machines, which])
  const last = useMemo(() => lastHourTotals(machines, which), [machines, which])
  if (hours.length === 0) {
    return <p className="p-2 text-neutral-500">No GitHub calls logged for {which === 'all' ? 'either machine' : which} yet. The gate (~/.agents/bin/gh) logs them once installed (bin/install-gh-gate.sh).</p>
  }
  const now = budget[budget.length - 1]
  const left = now ? Math.round(now.graphql * 100) : null
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
        <h3 className="text-sm font-medium text-neutral-200">Allowance left over time</h3>
        <p className="mb-2 text-xs text-neutral-600">GitHub's GraphQL allowance (what ticket, PR and board reads use) resets every hour. A steep drop is something spending fast; red dots are hours it ran out.</p>
        <BudgetLine points={budget} />
      </section>

      <section className="mt-6">
        <h3 className="text-sm font-medium text-neutral-200">Calls per hour, by who made them</h3>
        <div className="mb-2 flex flex-wrap gap-3 text-xs text-neutral-400">
          {GROUPS.map((g) => <span key={g} className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: GROUP_STYLE[g][0] }} />{GROUP_STYLE[g][1]}</span>)}
          <span className="flex items-center gap-1"><span className="inline-block h-1 w-2.5 bg-red-500" />refused by GitHub</span>
        </div>
        <HourBars hours={hours} />
      </section>

      <section className="mt-6">
        <h3 className="text-sm font-medium text-neutral-200">Top callers, last 24 hours</h3>
        <p className="mb-2 text-xs text-neutral-600">The program that ran gh, and what it asked for most. The top row is the first thing to optimize.</p>
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
      </section>
    </div>
  )
}
