import { useMemo, useState } from 'react'
import { mergeTokenRows, dailySeries, sumRows, projectTable, ticketTable, autonomousSeries, autonomousWeeklySeries, weeklySeries, jobTable } from '../lib/usage_view.js'

const KIND_STYLE = { headless: ['#3b82f6', 'Pipeline (headless)'], interactive: ['#10b981', 'Interactive'], subagent: ['#a78bfa', 'Subagents'] }
const AUTONOMOUS_STYLE = { autonomous: ['#ec4899', 'Autonomous'], interactive: ['#10b981', 'Interactive'] }
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

// Autonomous vs. interactive output share per day (%), with reference lines at 30/40/50%.
function AutonomousBars({ series, isWeekly = false }) {
  const W = 760, H = 150, bw = W / series.length
  const refLines = [0.3, 0.4, 0.5]
  const timeLabel = isWeekly ? 'week' : 'day'
  const timeKey = isWeekly ? 'week' : 'day'
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img" aria-label={`Autonomous vs. interactive share per ${timeLabel}, with 30/40/50% reference lines`}>
      {refLines.map((pct) => {
        const y = H - (pct * H)
        return (
          <g key={`ref-${pct}`}>
            <line x1="0" y1={y} x2={W} y2={y} stroke="#404040" strokeDasharray="2,2" strokeWidth="0.5" />
            <text x={-3} y={y + 3} fontSize="8" fill="#737373" textAnchor="end">{Math.round(pct * 100)}%</text>
          </g>
        )
      })}
      {series.map((d, i) => {
        const total = d.total || 0
        const share = total > 0 ? d.autonomous / total : 0
        const barHeight = share * H
        return (
          <g key={d[timeKey]}>
            <title>{`${d[timeKey]}: ${share > 0 ? Math.round(share * 100) : 0}% autonomous (${d.autonomous.toLocaleString()} autonomous, ${d.interactive.toLocaleString()} interactive)`}</title>
            {barHeight > 0 && <rect x={i * bw + 1} y={H - barHeight} width={bw - 2} height={barHeight} fill={AUTONOMOUS_STYLE.autonomous[0]} />}
            {i % 5 === 0 && <text x={i * bw} y={H + 13} fontSize="9" fill="#737373">{d[timeKey].slice(5)}</text>}
            {barHeight > 20 && <text x={i * bw + bw / 2} y={H - barHeight / 2 + 4} fontSize="8" fill="white" textAnchor="middle">{Math.round(share * 100)}%</text>}
          </g>
        )
      })}
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
  const rows = useMemo(() => mergeTokenRows(machines, which), [machines, which])
  const projects = useMemo(() => projectTable(machines, which), [machines, which])
  const tickets = useMemo(() => ticketTable(machines, which), [machines, which])
  const jobs = useMemo(() => jobTable(machines, which), [machines, which])
  if (rows.length === 0) return <p className="p-2 text-neutral-500">No token usage scan for {which === 'all' ? 'any machine' : which} yet. It is created within the hour.</p>

  const end = new Date().toISOString().slice(0, 10)
  const series = dailySeries(rows, { days: 30, end, metric })
  const autonomousSeriesData = autonomousSeries(rows, { days: 30, end, metric })
  const autonomousWeeklySeriesData = autonomousWeeklySeries(rows, { weeks: 4, end, metric })
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

      <Table title="Autonomous vs. interactive, last 30 days (by day)" hint="Autonomous (headless/background) runs vs. interactive sessions. Bars show the autonomous share as % of total. Reference lines show 30%, 40%, and 50%.">
        <div className="rounded border border-neutral-800 bg-neutral-900 p-3">
          <AutonomousBars series={autonomousSeriesData} />
          <div className="mt-1 flex gap-4 text-[11px] text-neutral-500">
            {Object.entries(AUTONOMOUS_STYLE).map(([k, [color, label]]) => (
              <span key={k} className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: color }} />{label}</span>
            ))}
          </div>
        </div>
      </Table>

      <Table title="Autonomous vs. interactive, last 4 weeks (by week)" hint="Weekly autonomous share. Bars show the autonomous share as % of total. Reference lines show 30%, 40%, and 50%.">
        <div className="rounded border border-neutral-800 bg-neutral-900 p-3">
          <AutonomousBars series={autonomousWeeklySeriesData} isWeekly={true} />
          <div className="mt-1 flex gap-4 text-[11px] text-neutral-500">
            {Object.entries(AUTONOMOUS_STYLE).map(([k, [color, label]]) => (
              <span key={k} className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: color }} />{label}</span>
            ))}
          </div>
        </div>
      </Table>

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

      <Table title="Top autonomous spenders" hint="Background jobs and pipeline runs tracked by ticket tag, sorted by output tokens. A high-cost autonomous job usually means a complex analysis or retry storm.">
        {jobs.length === 0 ? <p className="text-xs text-neutral-600">No autonomous runs with ticket tags in this window.</p> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-neutral-500"><th className="pb-1 font-normal">Ticket</th><th className="pb-1 text-right font-normal">Output</th><th className="pb-1 text-right font-normal">Runs</th></tr></thead>
            <tbody className="font-mono text-neutral-300">
              {jobs.slice(0, 15).map((j) => (
                <tr key={j.ticket} className="border-t border-neutral-900">
                  <td className="py-1 pr-2">{j.ticket}</td>
                  <td className="py-1 text-right">{fmt(j.output)}</td>
                  <td className="py-1 text-right text-neutral-500">{j.messages.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Table>
    </div>
  )
}
