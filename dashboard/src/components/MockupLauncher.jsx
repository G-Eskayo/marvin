import { useState } from 'react'

// "Try the mock-up" (G-Eskayo/marvin#938): a PR's clickable mock-up opens in its own sandboxed MARVIN window, read
// from the PR's head commit (mockup_window.js), never the browser or Finder. A mock-up that can't be read (its branch
// deleted, its page gone) says so here in plain words, and the rest of the detail carries on.

// What the button shows after an open: { status: 'open' } or { status: 'error', reason } in plain words.
export function openOutcome(result, error) {
  if (error) return { status: 'error', reason: String(error?.message || error).replace(/^Error invoking remote method '[^']+': (Error: )?/, '') || "This mock-up couldn't be opened" }
  return result?.ok ? { status: 'open' } : { status: 'error', reason: result?.reason || "This mock-up couldn't be opened" }
}

export default function MockupLauncher({ pr, open = (args) => window.api.mr.openMockup(args) }) {
  const mockups = Array.isArray(pr?.mockups) ? pr.mockups : []
  const [state, setState] = useState({}) // path -> { status: 'opening' | 'open' | 'error', reason }
  if (!mockups.length) return null
  const many = mockups.length > 1

  async function onOpen(m) {
    setState((s) => ({ ...s, [m.path]: { status: 'opening' } }))
    try {
      const r = await open({ repo: pr.repo, number: pr.number, sha: pr.headSha || '', ref: pr.headRef || '', path: m.path })
      setState((s) => ({ ...s, [m.path]: openOutcome(r) }))
    } catch (err) {
      setState((s) => ({ ...s, [m.path]: openOutcome(null, err) }))
    }
  }

  return (
    <div data-mockups={mockups.length} className="rounded-lg border border-indigo-800 bg-indigo-950/30 px-4 py-3">
      <div className="flex flex-col gap-2">
        {mockups.map((m) => {
          const s = state[m.path] || {}
          return (
            <div key={m.path} data-mockup={m.path} className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => onOpen(m)}
                disabled={s.status === 'opening'}
                className="min-h-[40px] rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-60"
              >
                {s.status === 'opening' ? 'Opening…' : many ? `Try the mock-up: ${m.name}` : 'Try the mock-up'}
              </button>
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-mono text-xs text-neutral-400" title={m.path}>{m.path}</span>
                <span className="text-xs text-neutral-500">Opens in its own MARVIN window, from this PR's branch. Click through it as you would the real thing.</span>
              </span>
              {s.status === 'error' && <p data-mockup-error="1" className="basis-full text-sm text-amber-300">{s.reason}</p>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
