import { useEffect, useState } from 'react'

const POLL_MS = 60000

function formatBytes(gb) {
  if (!gb) return '—'
  return `${gb.toFixed(1)} GB`
}

function formatDate(iso) {
  if (!iso) return 'never'
  const d = new Date(iso)
  const now = new Date()
  const days = Math.floor((now - d) / (86400000))
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days}d ago`
  return d.toLocaleDateString()
}

export default function ModelsPanel() {
  const [state, setState] = useState({ models: null, error: null })
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    const refresh = () => window.api.models?.list?.().then((r) => !cancelled && setState(r)).catch((e) => !cancelled && setState({ models: [], error: String(e.message || e) }))
    refresh()
    const i = setInterval(refresh, POLL_MS)
    return () => { cancelled = true; clearInterval(i) }
  }, [])

  const { models, error } = state
  const heavyModels = models?.filter(m => m.heavy) || []
  const lightModels = models?.filter(m => !m.heavy) || []

  return (
    <section className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900" data-testid="models-panel">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between p-3 text-left">
        <span className="text-sm font-medium text-neutral-200">
          Models <span className="text-neutral-500">{models ? `· ${models.length} registered` : ''}</span>
        </span>
        <span className="text-xs text-neutral-500">{open ? 'hide' : 'show'}</span>
      </button>
      {open && (
        <div className="border-t border-neutral-800 p-3">
          {error && <p className="text-xs text-red-400">{error}</p>}
          {!models && !error && <p className="text-xs text-neutral-500">Loading…</p>}
          {models && models.length === 0 && <p className="text-xs text-neutral-500">No models registered.</p>}
          {models && models.length > 0 && (
            <div className="space-y-4">
              {heavyModels.length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-amber-400 mb-2">Heavy Models (exclusive)</h4>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-neutral-700">
                          <th className="text-left px-2 py-1 text-neutral-400">Name</th>
                          <th className="text-right px-2 py-1 text-neutral-400">Size</th>
                          <th className="text-left px-2 py-1 text-neutral-400">Capability</th>
                          <th className="text-left px-2 py-1 text-neutral-400">Used By</th>
                          <th className="text-left px-2 py-1 text-neutral-400">Last Used</th>
                        </tr>
                      </thead>
                      <tbody>
                        {heavyModels.map((m) => (
                          <tr key={m.name} className="border-b border-neutral-800 hover:bg-neutral-800/50">
                            <td className="px-2 py-1 text-neutral-200 font-mono">{m.name}</td>
                            <td className="text-right px-2 py-1 text-neutral-400">{formatBytes(m.size_gb)}</td>
                            <td className="px-2 py-1 text-neutral-400">{m.capability || '—'}</td>
                            <td className="px-2 py-1 text-neutral-400">{m.used_by?.join(', ') || '—'}</td>
                            <td className="px-2 py-1 text-neutral-500">{formatDate(m.last_used)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {lightModels.length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-neutral-300 mb-2">Local Models</h4>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-neutral-700">
                          <th className="text-left px-2 py-1 text-neutral-400">Name</th>
                          <th className="text-right px-2 py-1 text-neutral-400">Size</th>
                          <th className="text-left px-2 py-1 text-neutral-400">Capability</th>
                          <th className="text-left px-2 py-1 text-neutral-400">Used By</th>
                          <th className="text-left px-2 py-1 text-neutral-400">Last Used</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lightModels.map((m) => (
                          <tr key={m.name} className="border-b border-neutral-800 hover:bg-neutral-800/50">
                            <td className="px-2 py-1 text-neutral-200 font-mono">{m.name}</td>
                            <td className="text-right px-2 py-1 text-neutral-400">{formatBytes(m.size_gb)}</td>
                            <td className="px-2 py-1 text-neutral-400">{m.capability || '—'}</td>
                            <td className="px-2 py-1 text-neutral-400">{m.used_by?.join(', ') || '—'}</td>
                            <td className="px-2 py-1 text-neutral-500">{formatDate(m.last_used)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
