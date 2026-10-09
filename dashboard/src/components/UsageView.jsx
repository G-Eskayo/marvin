import { useMemo, useState } from 'react'
import { mergeTokenRows, dailySeries, sumRows, projectTable, ticketTable, autonomousSeries, weeklySeries, jobTable } from '../lib/usage_view.js'

const KIND_STYLE = { headless: ['#3b82f6', 'Pipeline (headless)'], interactive: ['#10b981', 'Interactive'], subagent: ['#a78bfa', 'Subagents'] }
const fmt = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}k` : String(n))

function Stat({ label, value, hint }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="text-xl font-semibold text-white">{value}</p>
      {hint && <p className="text-[11px] text-neutral-600">{hint}</p>}
    </div>
  )
}

// Tokens per day, stacked by kind of run. A bar's height is that day's total on the chosen measure.
function DailyBars({ series, metric }) {
  const max = Math.max(1, ...series.map((d) => d.total))
  const W = 760, H = 150, bw = W / series.length
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img" aria-label={`${metric === 'all' ? 'All tokens' : 'Output tokens'} per day, stacked by kind of run`}>
      {series.map((d, i) => {
        let y = H
        return (
          <g key={d.day}>
            <title>{`${d.day}: ${d.total.toLocaleString()} (pipeline ${d.headless.toLocaleString()}, interactive ${d.interactive.toLocaleString()}, subagents ${d.subagent.toLocaleString()})`}</title>
            {['headless', 'interactive', 'subagent'].map((k) => {
              const h = (d[k] / max) * H
              y -= h
              return h > 0 ? <rect key={k} x={i * bw + 1} y={y} width={bw - 2} height={h} fill={KIND_STYLE[k][0]} /> : null
            })}
            {i % 5 === 0 && <text x={i * bw} y={H + 13} fontSize="9" fill="#737373">{d.day.slice(5)}</text>}
          </g>
        )
      })}
      <text x={W} y={10} fontSize="9" fill="#737373" textAnchor="end">peak {fmt(max)}</text>
    </svg>
  )
}

// Autonomous vs interactive tokens per day, with share reference lines.
function AutonomousBars({ series, metric }) {
  const max = Math.max(1, ...series.map((d) => d.total))
  const W = 760, H = 150, bw = W / series.length
  const references = [0.3, 0.4, 0.5]
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img" aria-label={`${metric === 'all' ? 'All tokens' : 'Output tokens'} per day, autonomous vs interactive`}>
      {/* Reference lines */}
      {references.map((ref) => {
        const y = H * (1 - ref)
        return (
          <g key={`ref-${ref}`}>
            <line x1="0" y1={y} x2={W} y2={y} stroke="#525252" strokeDasharray="4,4" opacity="0.5" />
            <text x={W + 2} y={y + 3} fontSize="8" fill="#737373">{Math.round(ref * 100)}%</text>
          </g>
        )
      })}
      {series.map((d, i) => {
        let y = H
        return (
          <g key={d.day}>
            <title>{`${d.day}: ${d.total.toLocaleString()} (autonomous ${d.autonomous.toLocaleString()}, interactive ${d.interactive.toLocaleString()}, share ${(d.share * 100).toFixed(0)}%)`}</title>
            {/* Interactive first */}
            {d.interactive > 0 && <rect x={i * bw + 1} y={H - (d.interactive / max) * H} width={bw - 2} height={(d.interactive / max) * H} fill="#10b981" />}
            {/* Autonomous on top */}
            {d.autonomous > 0 && <rect x={i * bw + 1} y={H - ((d.autonomous + d.interactive) / max) * H} width={bw - 2} height={(d.autonomous / max) * H} fill="#3b82f6" />}
            {i % 5 === 0 && <text x={i * bw} y={H + 13} fontSize="9" fill="#737373">{d.day.slice(5)}</text>}
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
  const [autonomousView, setAutonomousView] = useState('day')
  const rows = useMemo(() => mergeTokenRows(machines, which), [machines, which])
  const projects = useMemo(() => projectTable(machines, which), [machines, which])
  const tickets = useMemo(() => ticketTable(machines, which), [machines, which])
  const jobs = useMemo(() => jobTable(machines, which), [machines, which])
  const end = new Date().toISOString().slice(0, 10)
  const autonomousSeries_ = useMemo(() => autonomousSeries(rows, { days: 30, end, metric }), [rows, metric, end])
  const weeklySeries_ = useMemo(() => weeklySeries(rows, { weeks: 4, end, metric }), [rows, metric, end])

  if (rows.length === 0) return <p className="p-2 text-neutral-500">No token usage scan for {which === 'all' ? 'any machine' : which} yet. It is created within the hour.</p>

  const series = dailySeries(rows, { days: 30, end, metric })
  const d7 = sumRows(rows, { days: 7, end })
  const d30 = sumRows(rows, { days: 30, end })
  const headlessShare = d30.output ? d30.byKind.headless / d30.output : 0
  const maxProject = Math.max(1, ...projects.map((p) => p.output))
  const autonomousAvg = autonomousSeries_.length > 0 ? autonomousSeries_.reduce((s, d) => s + d.share, 0) / autonomousSeries_.length : 0

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
        <h3 className="text-sm font-medium text-neutral-200">Per day, last 30 days</h3>
        <div className="flex gap-1">
          {[['output', 'Output tokens'], ['all', 'All tokens']].map(([id, label]) => (
            <button key={id} onClick={() => setMetric(id)} className={`rounded px-2 py-1 text-xs ${metric === id ? 'bg-neutral-700 text-white' : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'}`}>{label}</button>
          ))}
        </div>
      </div>
      <div className="mt-2 rounded border border-neutral-800 bg-neutral-900 p-3">
        <DailyBars series={series} metric={metric} />
        <div className="mt-1 flex gap-4 text-[11px] text-neutral-500">
          {Object.entries(KIND_STYLE).map(([k, [color, label]]) => (
            <span key={k} className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: color }} />{label}</span>
          ))}
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between">
        <h3 className="text-sm font-medium text-neutral-200">Autonomous share, last 30 days</h3>
        <div className="flex gap-1">
          {[['day', 'By day'], ['week', 'By week']].map(([id, label]) => (
            <button key={id} onClick={() => setAutonomousView(id)} className={`rounded px-2 py-1 text-xs ${autonomousView === id ? 'bg-neutral-700 text-white' : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'}`}>{label}</button>
          ))}
        </div>
      </div>
      <div className="mt-2 rounded border border-neutral-800 bg-neutral-900 p-3">
        <AutonomousBars series={autonomousView === 'day' ? autonomousSeries_ : weeklySeries_} metric={metric} />
        <div className="mt-1 flex gap-4 text-[11px] text-neutral-500">
          <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: '#3b82f6' }} />Autonomous</span>
          <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: '#10b981' }} />Interactive</span>
        </div>
      </div>
      <p className="mt-2 text-xs text-neutral-500">Average: <strong className="text-neutral-400">{(autonomousAvg * 100).toFixed(0)}%</strong> autonomous in this window.</p>

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

      <Table title="Top autonomous spenders" hint="Background jobs, analysis runs, and pipeline tickets by their token cost. Every headless/subagent run passes through the launcher and is tracked here.">
        {jobs.length === 0 ? <p className="text-xs text-neutral-600">No autonomous runs in this window.</p> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-neutral-500"><th className="pb-1 font-normal">Job / Ticket</th><th className="pb-1 text-right font-normal">Output tokens</th><th className="pb-1 text-right font-normal">Cost (USD)</th><th className="pb-1 text-right font-normal">Runs</th></tr></thead>
            <tbody className="font-mono text-neutral-300">
              {jobs.slice(0, 20).map((j) => {
                const label = j.job.match(/^\d+$/) ? `#${j.job}` : j.job
                return (
                  <tr key={`${j.kind}:${j.job}`} className="border-t border-neutral-900">
                    <td className="py-1 pr-2">{label} <span className="text-neutral-500 text-xs">({j.kind})</span></td>
                    <td className="py-1 text-right">{fmt(j.output_tokens)}</td>
                    <td className="py-1 text-right">${j.cost_usd.toFixed(2)}</td>
                    <td className="py-1 text-right text-neutral-500">{j.runs}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Table>
    </div>
  )
}
