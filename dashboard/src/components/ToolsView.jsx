import { useMemo, useState } from 'react'
import { mergeRows, mergeInventory, mergeFailures } from '../lib/usage_view.js'

const DAYS = 30
const KINDS = [['all', 'All runs'], ['interactive', 'Interactive'], ['headless', 'Pipeline (headless)'], ['subagent', 'Subagents']]

function dayKeys(generatedAt) {
  const end = new Date(generatedAt || Date.now())
  return Array.from({ length: DAYS }, (_, i) => {
    const d = new Date(end)
    d.setUTCDate(d.getUTCDate() - (DAYS - 1 - i))
    return d.toISOString().slice(0, 10)
  })
}

// One cell per day, shaded by how busy that day was for THIS row; hover for the date and the count.
function Strip({ byDay, keys }) {
  const vals = keys.map((k) => byDay[k] || 0)
  const max = Math.max(1, ...vals)
  return (
    <div className="flex gap-px" role="img" aria-label="calls per day, last 30 days">
      {vals.map((v, i) => (
        <span
          key={keys[i]}
          title={`${keys[i]}: ${v} call${v === 1 ? '' : 's'}`}
          className="h-4 w-1.5 rounded-sm"
          style={{ background: v ? `rgba(59,130,246,${0.25 + 0.75 * (v / max)})` : 'rgb(38,38,38)' }}
        />
      ))}
    </div>
  )
}

const pct = (n) => `${Math.round(n * 100)}%`
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

function Table({ rows, keys, nameKey = 'name', showVia = false, kind, showPurpose = false, showCauses = false }) {
  const callsOf = (r) => (kind === 'all' ? r.calls : r.by_kind?.[kind] || 0)
  const shown = rows.filter((r) => callsOf(r) > 0)
  if (shown.length === 0) return <p className="text-xs text-neutral-600">Nothing for this filter.</p>
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-neutral-500">
          <th className="pb-1 font-normal">Name</th>
          {showPurpose && <th className="pb-1 font-normal">Purpose</th>}
          <th className="pb-1 text-right font-normal">Calls</th>
          <th className="pb-1 text-right font-normal" title="errors + invalid calls, as a share of all calls (all runs)">Failed</th>
          <th className="pb-1 text-right font-normal" title="expected non-zero exits (grep no match, tests failing)">Expected</th>
          <th className="pb-1 text-right font-normal" title="wrong parameters, tool used before its schema was loaded, unknown skill">Invalid</th>
          <th className="pb-1 text-right font-normal" title="you declined the call">Declined</th>
          <th className="pb-1 pl-4 font-normal">Last 30 days (each cell is a day)</th>
          <th className="pb-1 pl-2 font-normal">Last used</th>
        </tr>
      </thead>
      <tbody className="font-mono text-neutral-300">
        {shown.map((r) => {
          const rate = r.calls ? (r.error + r.invalid) / r.calls : 0
          const expectedRate = r.calls ? (r.expected || 0) / r.calls : 0
          return (
            <tr key={r[nameKey]} className="border-t border-neutral-900">
              <td className="max-w-[16rem] truncate py-1 pr-2" title={r[nameKey]}>
                {r[nameKey]}
                {showVia && (
                  <span className="ml-2 font-sans text-[10px] text-neutral-600">
                    {r.via?.skill_tool ? `${r.via.skill_tool} via Skill tool` : ''}
                    {r.via?.skill_tool && r.via?.read ? ' · ' : ''}
                    {r.via?.read ? `${r.via.read} via SKILL.md read` : ''}
                  </span>
                )}
              </td>
              {showPurpose && <td className="py-1 pr-2 text-xs text-neutral-400 max-w-xs truncate" title={r.purpose}>{r.purpose}</td>}
              <td className="py-1 text-right">{callsOf(r).toLocaleString()}</td>
              <td className={`py-1 text-right ${rate > 0.25 ? 'text-amber-300' : ''}`}>{pct(rate)}</td>
              <td className={`py-1 text-right ${expectedRate > 0.1 ? 'text-blue-400' : 'text-neutral-600'}`}>{(r.expected || 0)}</td>
              <td className={`py-1 text-right ${r.invalid ? 'text-red-400' : 'text-neutral-600'}`}>{r.invalid}</td>
              <td className="py-1 text-right text-neutral-500">{r.rejected}</td>
              <td className="py-1 pl-4"><Strip byDay={r.by_day} keys={keys} /></td>
              <td className="py-1 pl-2 font-sans text-xs text-neutral-500">{ago(r.last_used)}</td>
            </tr>
          )
        })}
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

// Which tools and skills were used, when, and whether it went well, for the chosen machine(s).
export default function ToolsView({ machines, which }) {
  const [kind, setKind] = useState('all')
  const [query, setQuery] = useState('')
  const scans = machines.filter((m) => (which === 'all' || m.machine === which) && m.tools)
  const q = query.trim().toLowerCase()
  const match = (r, key = 'name') => !q || String(r[key]).toLowerCase().includes(q)

  const tools = useMemo(() => mergeRows(machines, which, 'tools'), [machines, which])
  const skills = useMemo(() => mergeRows(machines, which, 'skills'), [machines, which])
  const servers = useMemo(() => mergeRows(machines, which, 'mcp_servers', 'server'), [machines, which])
  const agents = useMemo(() => mergeRows(machines, which, 'agents'), [machines, which])
  const inventory = useMemo(() => mergeInventory(machines, which), [machines, which])
  const failures = useMemo(() => mergeFailures(machines, which), [machines, which])

  if (scans.length === 0) return <p className="p-2 text-neutral-500">No tool usage scan for {which === 'all' ? 'any machine' : which} yet. It is created within the hour, or open the other machine's dashboard.</p>
  const keys = dayKeys(scans[0].tools.generated_at)
  const totalCalls = tools.reduce((s, t) => s + t.calls, 0)
  const failed = tools.reduce((s, t) => s + t.error + t.invalid, 0)
  const invalid = tools.reduce((s, t) => s + t.invalid, 0)
  const files = scans.reduce((s, m) => s + (m.tools.files_scanned || 0), 0)

  return (
    <div className="max-w-5xl">
      <p className="mb-3 text-xs text-neutral-500">
        Every tool and skill call in the Claude Code sessions on {which === 'all' ? 'both machines' : which} (interactive, pipeline and subagents), last {scans[0].tools.window_days} days, from{' '}
        {files.toLocaleString()} session transcripts. "Failed" = errored or invalid; Bash failures are mostly non-zero exits, which are often expected (a search with no match).
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Calls" value={totalCalls.toLocaleString()} hint={`${tools.length} different tools`} />
        <Stat label="Failed" value={pct(totalCalls ? failed / totalCalls : 0)} hint={`${failed.toLocaleString()} calls`} />
        <Stat label="Expected" value={tools.reduce((s, t) => s + (t.expected || 0), 0)} hint="expected non-zero exits (e.g. grep, tests)" />
        <Stat label="Invalid calls" value={invalid} hint="used wrongly: bad params, unloaded schema, unknown skill" bad={invalid > 0} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by name"
          className="w-48 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-200 outline-none focus:border-blue-600"
        />
        {KINDS.map(([id, label]) => (
          <button key={id} onClick={() => setKind(id)} className={`rounded px-2 py-1 text-xs ${kind === id ? 'bg-neutral-700 text-white' : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'}`}>
            {label}
          </button>
        ))}
      </div>

      <Section title="Tools" hint="Built-in and MCP tools, by number of calls.">
        <Table rows={tools.filter((r) => match(r)).slice(0, 40)} keys={keys} kind={kind} showPurpose />
      </Section>

      <Section title="Our skills" hint="Loaded through the Skill tool or by reading the skill's SKILL.md (how CLAUDE.md's routing table invokes most of them).">
        <Table rows={skills.filter((r) => match(r))} keys={keys} showVia kind={kind} showPurpose />
        {inventory.never_used.length > 0 && (
          <div className="mt-3">
            <p className="text-xs text-amber-300">Never fired in {scans[0].tools.window_days} days ({inventory.never_used.length} of ours):</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {inventory.never_used.map((n) => (
                <span key={n} className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-xs text-neutral-400">{n}</span>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-neutral-600">Either nothing called for them yet, or their triggers aren't wired well. Whether the right skill fired for a given request is not measured here.</p>
          </div>
        )}
      </Section>

      {servers.length > 0 && <Section title="MCP servers"><Table rows={servers.filter((r) => match(r, 'server'))} keys={keys} nameKey="server" kind={kind} /></Section>}
      {agents.length > 0 && <Section title="Subagents spawned"><Table rows={agents.filter((r) => match(r))} keys={keys} kind={kind} /></Section>}

      <Section title="Recent failures" hint="Newest first. Includes expected non-zero exits (grep, tests) for auditability. Declined and interrupted calls shown for context.">
        <div className="flex flex-col gap-1">
          {failures.filter((f) => !q || f.tool.toLowerCase().includes(q) || (f.cause || '').toLowerCase().includes(q)).slice(0, 20).map((f, i) => (
            <div key={i} className="rounded border border-neutral-900 px-2 py-1 text-xs">
              <p className="text-neutral-500">
                <span className="text-neutral-300">{f.tool}</span> {f.input && <span className="text-neutral-600">({f.input})</span>}
                {' '}
                <span className={f.outcome === 'invalid' ? 'text-red-400' : f.outcome === 'expected' ? 'text-blue-400' : 'text-amber-400'}>{f.outcome}</span>
                {' '}
                {f.cause && <span className="text-neutral-500">• {f.cause}</span>}
                {' '}
                <span className="text-neutral-600">{ago(f.at)} · {f.kind}</span>
                {which === 'all' && machines.length > 1 ? <span className="text-neutral-600"> · {f.machine}</span> : ''}
              </p>
              <p className="text-neutral-600 truncate" title={f.message}>{f.message}</p>
            </div>
          ))}
        </div>
      </Section>
    </div>
  )
}
