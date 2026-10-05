import { useEffect, useState } from 'react'
import { cleanIpcError } from '../lib/ipcError.js'

// Which projects MARVIN may work on by itself. A project does nothing automatically until its
// dispatch is on; "Test setup" runs the whole path short of the model and GitHub, so you can see it
// work before you let it.
function Row({ p, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [test, setTest] = useState(null)
  const [error, setError] = useState(null)
  const on = p.dispatch === 'on'

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      await window.api.profiles.setDispatch(p.repo, on ? 'off' : 'on')
      await onChanged()
    } catch (e) {
      setError(cleanIpcError(e))
    } finally {
      setBusy(false)
    }
  }
  async function runTest() {
    setTest({ running: true })
    try {
      setTest(await window.api.profiles.selftest(p.repo))
    } catch (e) {
      setTest({ ok: false, output: cleanIpcError(e) })
    }
  }

  return (
    <div className="rounded border border-neutral-800 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-neutral-200">{p.name}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${on ? 'bg-emerald-950 text-emerald-300' : 'bg-neutral-800 text-neutral-400'}`}>
          automatic work: {on ? 'ON' : 'off'}
        </span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${p.mergeFromDashboard ? 'bg-sky-950 text-sky-300' : 'bg-neutral-800 text-neutral-500'}`}>
          {p.mergeFromDashboard ? 'PRs reviewable in MR Review' : 'PRs reviewed on GitHub'}
        </span>
        <span className="text-[11px] text-neutral-600">runs on {p.machines.join(', ') || 'no machine listed'}</span>
        <div className="ml-auto flex gap-2">
          <button onClick={runTest} disabled={test?.running} className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-800 disabled:opacity-50">
            {test?.running ? 'Testing…' : 'Test setup'}
          </button>
          <button
            onClick={toggle}
            disabled={busy}
            className={`rounded px-2 py-1 text-xs disabled:opacity-50 ${on ? 'border border-neutral-700 text-neutral-300 hover:bg-neutral-800' : 'bg-blue-600 text-white hover:bg-blue-500'}`}
          >
            {on ? 'Turn off' : 'Turn on…'}
          </button>
        </div>
      </div>
      <p className="mt-1 text-[11px] text-neutral-600">
        Checks: {p.checks.map((c) => `${c.label}${c.required ? ' (required)' : ''}${c.enabled ? '' : ' (disabled)'}`).join('; ') || 'none'}
      </p>
      {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
      {test && !test.running && (
        <pre className={`mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-neutral-950 p-2 font-mono text-[11px] ${test.ok ? 'text-neutral-400' : 'text-red-300'}`}>
          {test.ok ? 'Setup works. ' : 'Setup problem: '}
          {test.output.split('\n').slice(0, 14).join('\n')}
        </pre>
      )}
    </div>
  )
}

export default function ProfilesPanel() {
  const [profiles, setProfiles] = useState(undefined)
  const load = () => window.api.profiles.list().then(setProfiles).catch(() => setProfiles([]))
  useEffect(() => {
    load()
  }, [])
  if (!profiles || profiles.length === 0) return null
  return (
    <div className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <p className="text-sm font-medium text-white">Projects MARVIN can work on by itself</p>
      <p className="mt-1 text-xs text-neutral-400">
        Each project has an execution profile (how to build and check it). Nothing runs automatically until you turn a project on; use Test setup first. Turning one on lets the hourly scan claim its ready tickets and open PRs for you to review.
      </p>
      <div className="mt-3 flex flex-col gap-2">
        {profiles.map((p) => (
          <Row key={p.repo} p={p} onChanged={load} />
        ))}
      </div>
    </div>
  )
}
