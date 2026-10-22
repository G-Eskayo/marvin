import { useMemo, useState } from 'react'
import { mergeTokenRows, dailySeries, sumRows, projectTable, ticketTable, autonomousShare, launchSpendTable, weeklySeries } from '../lib/usage_view.js'

const KIND_STYLE = { headless: ['#3b82f6', 'Pipeline (headless)'], interactive: ['#10b981', 'Interactive'], subagent: ['#a78bfa', 'Subagents'] }
const fmt = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}k` : String(n))

// ShareLine: shows autonomous spending with reference lines at 30/40/50%
export function ShareLine({ share }) {
  const W = 760, H = 40
  const pct = Math.min(100, share * 100)
  const x = (pct / 100) * W
  const textX = Math.min(x + 5, W - 30)
  const refs = [30, 40, 50]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Autonomous spending: ${pct.toFixed(0)}%`}>
      {refs.map((r) => {
        const rx = (r / 100) * W
        return <line key={r} x1={rx} y1={10} x2={rx} y2={H - 10} stroke="#737373" strokeDasharray="2,2" strokeWidth="1" />
      })}
      <rect x="0" y={H / 2 - 3} width={x} height="6" fill="#a78bfa" />
      <text x={textX} y={H / 2 + 4} fontSize="12" fill="#9ca3af">{pct.toFixed(0)}%</text>
    </svg>
  )
}

function Stat({ label, value, hint }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="text-xl font-semibold text-white">{value}</p>
      {hint && <p className="text-[11px] text-neutral-600">{hint}</p>}
    </div>
  )
}

// Tokens per day or week, stacked by kind of run. A bar's height is that period's total on the chosen measure.
export function DailyBars({ series, metric, bucketKey = 'day' }) {
  const max = Math.max(1, ...series.map((d) => d.total))
  const W = 760, H = 150, bw = W / series.length
  const keyField = bucketKey === 'week' ? 'week' : 'day'
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img" aria-label={`${metric === 'all' ? 'All tokens' : 'Output tokens'} per ${bucketKey}, stacked by kind of run`}>
      {series.map((d, i) => {
        let y = H
        return (
          <g key={d[keyField]}>
            <title>{`${d[keyField]}: ${d.total.toLocaleString()} (pipeline ${d.headless.toLocaleString()}, interactive ${d.interactive.toLocaleString()}, subagents ${d.subagent.toLocaleString()})`}</title>
            {['headless', 'interactive', 'subagent'].map((k) => {
              const h = (d[k] / max) * H
              y -= h
              return h > 0 ? <rect key={k} x={i * bw + 1} y={y} width={bw - 2} height={h} fill={KIND_STYLE[k][0]} /> : null
            })}
            {i % 5 === 0 && <text x={i * bw} y={H + 13} fontSize="9" fill="#737373">{bucketKey === 'week' ? d.week.slice(5) : d.day.slice(5)}</text>}
          </g>
        )
      })}
      <text x={W} y={10} fontSize="9" fill="#737373" textAnchor="end">peak {fmt(max)}</text>
    </svg>
  )
}

function Table({ title, hint, children }) {
  return (
    <section className="mt-6">
      <h3 className="text-sm font-medium text-neutral-200">{title}</h3>
      {hint && <p className="mb-2 text-xs text-neutral-600">{hint}</p>}
      {children}
    </section>
  )
}

// How much the Claude sessions used, when, by what kind of run, and where it went (project, ticket) for the chosen machine(s).
export default function UsageView({ machines, which }) {
  const [metric, setMetric] = useState('output')
  const [period, setPeriod] = useState('day')  // 'day' or 'week'
  const rows = useMemo(() => mergeTokenRows(machines, which), [machines, which])
  const projects = useMemo(() => projectTable(machines, which), [machines, which])
  const tickets = useMemo(() => ticketTable(machines, which), [machines, which])
  const topSpenders = useMemo(() => launchSpendTable(machines, which), [machines, which])
  const end = new Date().toISOString().slice(0, 10)
  const autonomousShareVal = useMemo(() => autonomousShare(rows, end), [rows, end])
  if (rows.length === 0) return <p className="p-2 text-neutral-500">No token usage scan for {which === 'all' ? 'any machine' : which} yet. It is created within the hour.</p>

  const dailySeries_data = dailySeries(rows, { days: 30, end, metric })
  const weeklySeries_data = weeklySeries(rows, end)
  const series = period === 'week' ? weeklySeries_data : dailySeries_data
  const d7 = sumRows(rows, { days: 7, end })
  const d30 = sumRows(rows, { days: 30, end })
  const headlessShare = d30.output ? d30.byKind.headless / d30.output : 0
  const maxProject = Math.max(1, ...projects.map((p) => p.output))

  return (
    <div className="max-w-5xl">
      <p className="mb-3 text-xs text-neutral-500">
        Tokens used by the Claude sessions on {which === 'all' ? 'both machines' : which}, read from the session transcripts (each response counted once). <strong className="text-neutral-400">Output tokens</strong> are what
        usage limits mostly track, so they are the default measure; cached input is cheap but large, and shown under "all tokens".
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Output, last 7 days" value={fmt(d7.output)} hint={`${d7.messages.toLocaleString()} responses`} />
        <Stat label="Output, last 30 days" value={fmt(d30.output)} hint={`${d30.messages.toLocaleString()} responses`} />
        <Stat label="Pipeline share" value={`${Math.round(headlessShare * 100)}%`} hint="of 30-day output, headless ticket runs" />
        <Stat label="Cache reads, 30 days" value={fmt(d30.cache_read)} hint="re-reading context: cheap, huge" />
      </div>

      <div className="mt-5 flex items-center justify-between">
        <h3 className="text-sm font-medium text-neutral-200">Per {period === 'day' ? 'day' : 'week'}, last 30 days</h3>
        <div className="flex gap-1">
          {[['day', 'By day'], ['week', 'By week']].map(([id, label]) => (
            <button key={id} onClick={() => setPeriod(id)} className={`rounded px-2 py-1 text-xs ${period === id ? 'bg-neutral-700 text-white' : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'}`}>{label}</button>
          ))}
          <div className="mx-2 w-px bg-neutral-800" />
          {[['output', 'Output tokens'], ['all', 'All tokens']].map(([id, label]) => (
            <button key={id} onClick={() => setMetric(id)} className={`rounded px-2 py-1 text-xs ${metric === id ? 'bg-neutral-700 text-white' : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'}`}>{label}</button>
          ))}
        </div>
      </div>
      <div className="mt-2 rounded border border-neutral-800 bg-neutral-900 p-3">
        <DailyBars series={series} metric={metric} bucketKey={period} />
        <div className="mt-1 flex gap-4 text-[11px] text-neutral-500">
          {Object.entries(KIND_STYLE).map(([k, [color, label]]) => (
            <span key={k} className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: color }} />{label}</span>
          ))}
        </div>
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-medium text-neutral-200">Autonomous job spending</h3>
        <p className="mb-3 text-xs text-neutral-600">Background jobs (digest, research-colony, self-review) as a share of total spending. Reference lines at 30%, 40%, 50%.</p>
        <div className="rounded border border-neutral-800 bg-neutral-900 p-3">
          <ShareLine share={autonomousShareVal} />
        </div>
      </div>

      {topSpenders.length > 0 ? (
        <Table title="Top autonomous spenders" hint="Background job categories by cost.">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-neutral-500"><th className="pb-1 font-normal">Job</th><th className="pb-1 text-right font-normal">Cost ($)</th></tr></thead>
            <tbody className="font-mono text-neutral-300">
              {topSpenders.slice(0, 10).map((s) => (
                <tr key={s.job} className="border-t border-neutral-900">
                  <td className="py-1 pr-2">{s.job}</td>
                  <td className="py-1 text-right text-neutral-500">${s.total.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Table>
      ) : (
        <Table title="Top autonomous spenders" hint="Background job categories by cost.">
          <p className="text-xs text-neutral-600">No background jobs recorded yet.</p>
        </Table>
      )}

      <Table title="Where it went: projects" hint="Output tokens by the project the session worked in (a directory inside a project counts for the project).">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-neutral-500"><th className="pb-1 font-normal">Project</th><th className="pb-1 text-right font-normal">Output</th><th className="pb-1 pl-4 font-normal">Share</th><th className="pb-1 text-right font-normal">Responses</th></tr></thead>
          <tbody className="font-mono text-neutral-300">
            {projects.slice(0, 15).map((p) => (
              <tr key={p.project} className="border-t border-neutral-900">
                <td className="max-w-[18rem] truncate py-1 pr-2" title={p.project}>{p.project}</td>
                <td className="py-1 text-right">{fmt(p.output)}</td>
                <td className="py-1 pl-4"><div className="h-2 rounded-sm bg-blue-500/70" style={{ width: `${Math.max(2, (p.output / maxProject) * 100)}%` }} /></td>
                <td className="py-1 text-right text-neutral-500">{p.messages.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Table>

      <Table title="Where it went: pipeline tickets" hint="The most expensive tickets. A ticket far above the rest usually means retries; each retry is a new run.">
        {tickets.length === 0 ? <p className="text-xs text-neutral-600">No pipeline runs in this window.</p> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-neutral-500"><th className="pb-1 font-normal">Ticket</th><th className="pb-1 text-right font-normal">Output</th><th className="pb-1 text-right font-normal">Responses</th></tr></thead>
            <tbody className="font-mono text-neutral-300">
              {tickets.slice(0, 15).map((t) => (
                <tr key={`${t.project}#${t.ticket}`} className="border-t border-neutral-900">
                  <td className="py-1 pr-2">{t.project} <span className="text-neutral-500">#{t.ticket}</span></td>
                  <td className="py-1 text-right">{fmt(t.output)}</td>
                  <td className="py-1 text-right text-neutral-500">{t.messages.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Table>
    </div>
  )
}
