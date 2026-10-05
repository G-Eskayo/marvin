import { useEffect, useState } from 'react'

const DAYS = 30

function dayKeys(generatedAt) {
  const end = new Date(generatedAt || Date.now())
  return Array.from({ length: DAYS }, (_, i) => {
    const d = new Date(end)
    d.setUTCDate(d.getUTCDate() - (DAYS - 1 - i))
    return d.toISOString().slice(0, 10)
  })
}

function Spark({ byDay, keys }) {
  const vals = keys.map((k) => byDay[k] || 0)
  const max = Math.max(1, ...vals)
  return (
    <svg viewBox={`0 0 ${DAYS * 4} 16`} className="h-4 w-28" role="img" aria-label="calls per day, last 30 days">
      {vals.map((v, i) => (
        <rect key={i} x={i * 4} y={16 - (v / max) * 16} width="3" height={(v / max) * 16 || 0.5} className={v ? 'fill-blue-500' : 'fill-neutral-800'} />
      ))}
    </svg>
  )
}

const pct = (n) => `${Math.round(n * 100)}%`
const rate = (r) => (r.calls ? (r.error + r.invalid) / r.calls : 0)
function ago(iso) {
  if (!iso) return 'never'
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

function Stat({ label, value, hint, bad }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      <p className={`text-xl font-semibold ${bad ? 'text-amber-300' : 'text-white'}`}>{value}</p>
      {hint && <p className="text-[11px] text-neutral-600">{hint}</p>}
    </div>
  )
}

function Table({ rows, keys, nameKey = 'name', showVia = false }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-neutral-500">
          <th className="pb-1 font-normal">Name</th>
          <th className="pb-1 text-right font-normal">Calls</th>
          <th className="pb-1 text-right font-normal" title="errors + invalid calls, as a share of all calls">Failed</th>
          <th className="pb-1 text-right font-normal" title="wrong parameters, tool used before its schema was loaded, unknown skill">Invalid</th>
          <th className="pb-1 text-right font-normal" title="you declined the call">Declined</th>
          <th className="pb-1 pl-4 font-normal">Last 30 days</th>
          <th className="pb-1 pl-2 font-normal">Last used</th>
        </tr>
      </thead>
      <tbody className="font-mono text-neutral-300">
        {rows.map((r) => (
          <tr key={r[nameKey]} className="border-t border-neutral-900">
            <td className="max-w-[16rem] truncate py-1 pr-2" title={r[nameKey]}>
              {r[nameKey]}
              {showVia && (
                <span className="ml-2 font-sans text-[10px] text-neutral-600">
                  {r.via.skill_tool ? `${r.via.skill_tool} via Skill tool` : ''}
                  {r.via.skill_tool && r.via.read ? ' · ' : ''}
                  {r.via.read ? `${r.via.read} via SKILL.md read` : ''}
                </span>
              )}
            </td>
            <td className="py-1 text-right">{r.calls}</td>
            <td className={`py-1 text-right ${rate(r) > 0.25 ? 'text-amber-300' : ''}`}>{pct(rate(r))}</td>
            <td className={`py-1 text-right ${r.invalid ? 'text-red-400' : 'text-neutral-600'}`}>{r.invalid}</td>
            <td className="py-1 text-right text-neutral-500">{r.rejected}</td>
            <td className="py-1 pl-4">
              <Spark byDay={r.by_day} keys={keys} />
            </td>
            <td className="py-1 pl-2 font-sans text-xs text-neutral-500">{ago(r.last_used)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Section({ title, hint, children }) {
  return (
    <section className="mt-6">
      <h3 className="text-sm font-medium text-neutral-200">{title}</h3>
      {hint && <p className="mb-2 text-xs text-neutral-600">{hint}</p>}
      {children}
    </section>
  )
}

export default function ToolUsage() {
  const [data, setData] = useState(undefined)
  useEffect(() => {
    window.api.health.tools().then(setData).catch(() => setData(null))
  }, [])

  if (data === undefined) return <div className="p-2 text-neutral-500">Reading the last 30 days of sessions…</div>
  if (data === null) return <div className="p-2 text-red-400">Could not read tool usage (is ~/.agents/lib/tool_usage.py runnable?).</div>

  const keys = dayKeys(data.generated_at)
  const totalCalls = data.tools.reduce((s, t) => s + t.calls, 0)
  const failed = data.tools.reduce((s, t) => s + t.error + t.invalid, 0)
  const invalid = data.tools.reduce((s, t) => s + t.invalid, 0)
  return (
    <div className="max-w-5xl">
      <p className="mb-3 text-xs text-neutral-500">
        Every tool and skill call in your Claude Code sessions (interactive, headless and subagents), last {data.window_days} days, from {data.files_scanned.toLocaleString()} session
        transcripts. Updated {ago(data.generated_at)}. "Failed" = errored or invalid; Bash failures are mostly non-zero exits, which are often expected (a search with no match).
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Calls" value={totalCalls.toLocaleString()} hint={`${data.tools.length} different tools`} />
        <Stat label="Failed" value={pct(totalCalls ? failed / totalCalls : 0)} hint={`${failed.toLocaleString()} calls`} />
        <Stat label="Invalid calls" value={invalid} hint="used wrongly: bad params, unloaded schema, unknown skill" bad={invalid > 0} />
        <Stat label="Our skills used" value={`${data.inventory.used} / ${data.inventory.known}`} hint={`${data.inventory.never_used.length} never fired`} bad={data.inventory.never_used.length > 0} />
      </div>

      <Section title="Tools" hint="Built-in and MCP tools, by number of calls.">
        <Table rows={data.tools.slice(0, 20)} keys={keys} />
      </Section>

      <Section title="Our skills" hint="Loaded either through the Skill tool or by reading the skill's SKILL.md (how CLAUDE.md's routing table invokes most of them).">
        <Table rows={data.skills} keys={keys} showVia />
        {data.inventory.never_used.length > 0 && (
          <div className="mt-3">
            <p className="text-xs text-amber-300">Never fired in {data.window_days} days ({data.inventory.never_used.length} of ours):</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {data.inventory.never_used.map((n) => (
                <span key={n} className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-xs text-neutral-400">
                  {n}
                </span>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-neutral-600">Either nothing called for them yet, or their triggers aren't wired well. Whether the right skill fired for a given request is not measured here.</p>
          </div>
        )}
      </Section>

      {data.mcp_servers.length > 0 && (
        <Section title="MCP servers">
          <Table rows={data.mcp_servers} keys={keys} nameKey="server" />
        </Section>
      )}
      {data.agents.length > 0 && (
        <Section title="Subagents spawned">
          <Table rows={data.agents} keys={keys} />
        </Section>
      )}

      <Section title="Recent failures" hint="Newest first. Declined and interrupted calls are included so you can see what was stopped.">
        <div className="flex flex-col gap-1">
          {data.recent_failures.slice(0, 15).map((f, i) => (
            <p key={i} className="truncate rounded border border-neutral-900 px-2 py-1 text-xs text-neutral-500" title={f.message}>
              <span className="text-neutral-300">{f.tool}</span> <span className={f.outcome === 'invalid' ? 'text-red-400' : 'text-amber-400'}>{f.outcome}</span> · {ago(f.at)} · {f.kind} · {f.message}
            </p>
          ))}
        </div>
      </Section>
    </div>
  )
}
