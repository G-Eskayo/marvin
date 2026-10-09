import { useEffect, useState } from 'react'
import MetricsScorecard from './MetricsScorecard.jsx'
import ToolsView from './ToolsView.jsx'
import UsageView from './UsageView.jsx'
import GithubView from './GithubView.jsx'
import { machineFreshness } from '../lib/usage_view.js'

const SECTIONS = [
  { id: 'tools', label: 'Tools & skills' },
  { id: 'usage', label: 'Usage' },
  { id: 'github', label: 'GitHub' },
  { id: 'pipeline', label: 'Pipeline results' }
]

const FRESH_STYLE = { ok: 'text-neutral-500', unreachable: 'text-red-400', 'no-data': 'text-amber-400' }

// What MARVIN is actually doing: which tools and skills get used (and whether it goes well), how much the sessions use, and the
// pipeline's benchmark results, and what spends the shared GitHub allowance. Tools, Usage and GitHub cover both machines; pick one
// to look at it alone.
export default function MetricsPage() {
  const [section, setSection] = useState('tools')
  const [which, setWhich] = useState('all')
  const [data, setData] = useState(undefined) // { report, error } | undefined while loading
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    window.api.metrics.usage().then(setData).catch((e) => setData({ report: null, error: String(e) })).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const machines = data?.report?.machines || []
  return (
    <div className="p-6">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <nav className="flex gap-1">
          {SECTIONS.map((s) => (
            <button key={s.id} onClick={() => setSection(s.id)} className={`rounded-md px-3 py-1.5 text-sm ${section === s.id ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'}`}>
              {s.label}
            </button>
          ))}
        </nav>
        {section !== 'pipeline' && machines.length > 0 && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {[{ machine: 'all' }, ...machines].map((m) => (
              <button key={m.machine} onClick={() => setWhich(m.machine)} className={`rounded px-2 py-1 text-xs ${which === m.machine ? 'bg-blue-700 text-white' : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'}`}>
                {m.machine === 'all' ? 'Both machines' : m.machine}{m.this ? ' (this one)' : ''}
              </button>
            ))}
            <button onClick={load} disabled={loading} className="rounded bg-neutral-900 px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-50">{loading ? 'Reading…' : 'Refresh'}</button>
          </div>
        )}
      </div>

      {section === 'pipeline' ? (
        <MetricsScorecard />
      ) : data === undefined ? (
        <p className="text-neutral-500">Reading the session transcripts on both machines. The first read can take a few seconds…</p>
      ) : (
        <>
          {data.error && <p className="mb-3 text-sm text-amber-300">{data.error}{data.report ? ' Showing the last good result.' : ''}</p>}
          {machines.length > 0 && (
            <p className="mb-3 text-xs">
              {machines.map((m) => {
                const f = machineFreshness(m)
                return <span key={m.machine} className={`mr-4 ${FRESH_STYLE[f.state]}`}>{m.machine}: {f.text}</span>
              })}
            </p>
          )}
          {section === 'tools' ? <ToolsView machines={machines} which={which} /> : section === 'github' ? <GithubView machines={machines} which={which} /> : <UsageView machines={machines} which={which} />}
        </>
      )}
    </div>
  )
}
