import { useEffect, useState } from 'react'
import NextUpQueue, { describeQueueRow } from './NextUpQueue'

const POLL_MS = 30000

function formatDate(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const now = new Date()
    const diff = now - d
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(diff / 3600000)
    if (minutes < 1) return 'just now'
    if (minutes < 60) return `${minutes}m ago`
    if (hours < 24) return `${hours}h ago`
    return d.toLocaleDateString()
  } catch {
    return iso
  }
}

function formatSize(gb) {
  return `${gb} GB`
}

export default function ModelsPanel() {
  const [models, setModels] = useState(null)
  const [queue, setQueue] = useState(null)
  const [error, setError] = useState(null)
  const [openModels, setOpenModels] = useState(true)
  const [openQueue, setOpenQueue] = useState(true)

  useEffect(() => {
    let cancelled = false

    const refresh = async () => {
      try {
        const [modelList, queueList] = await Promise.all([
          window.api.models.list(),
          window.api.models.queue()
        ])
        if (!cancelled) {
          setModels(modelList)
          setQueue(queueList || [])
          setError(null)
        }
      } catch (e) {
        if (!cancelled) {
          setError(String(e.message || e))
          setModels(null)
          setQueue([])
        }
      }
    }

    refresh()
    const i = setInterval(refresh, POLL_MS)
    return () => { cancelled = true; clearInterval(i) }
  }, [])

  return (
    <div className="space-y-4">
      {/* Models section */}
      <section className="rounded-lg border border-neutral-800 bg-neutral-900">
        <button
          onClick={() => setOpenModels(!openModels)}
          className="flex w-full items-center justify-between p-3 text-left"
        >
          <span className="text-sm font-medium text-neutral-200">
            Models <span className="text-neutral-500">{models ? `· ${Object.keys(models).length}` : ''}</span>
          </span>
          <span className="text-xs text-neutral-500">{openModels ? 'hide' : 'show'}</span>
        </button>

        {openModels && (
          <div className="border-t border-neutral-800 p-3">
            {error && <p className="text-xs text-red-400 mb-3">{error}</p>}
            {!models && !error && <p className="text-xs text-neutral-500">Loading…</p>}
            {models && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-neutral-700">
                      <th className="text-left px-2 py-2 text-neutral-400 font-medium">Name</th>
                      <th className="text-right px-2 py-2 text-neutral-400 font-medium">Size</th>
                      <th className="text-left px-2 py-2 text-neutral-400 font-medium">Used By</th>
                      <th className="text-left px-2 py-2 text-neutral-400 font-medium">Last Used</th>
                      <th className="text-left px-2 py-2 text-neutral-400 font-medium">Machine</th>
                      <th className="text-center px-2 py-2 text-neutral-400 font-medium">Heavy</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-800">
                    {Object.entries(models).map(([name, meta]) => (
                      <tr key={name} className="hover:bg-neutral-800/50">
                        <td className="px-2 py-2 text-neutral-200 font-mono">{name}</td>
                        <td className="text-right px-2 py-2 text-neutral-400">{formatSize(meta.size_gb)}</td>
                        <td className="px-2 py-2 text-neutral-400">{meta.used_by || '—'}</td>
                        <td className="px-2 py-2 text-neutral-500">{formatDate(meta.last_used)}</td>
                        <td className="px-2 py-2 text-neutral-500">{meta.machine || 'shared'}</td>
                        <td className="text-center px-2 py-2">
                          {meta.heavy && <span className="text-xs bg-amber-900/50 text-amber-300 px-1.5 py-0.5 rounded">heavy</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Queue section */}
      <section className="rounded-lg border border-neutral-800 bg-neutral-900">
        <button
          onClick={() => setOpenQueue(!openQueue)}
          className="flex w-full items-center justify-between p-3 text-left"
        >
          <span className="text-sm font-medium text-neutral-200">
            Model Queue <span className="text-neutral-500">{queue ? `· ${queue.length} active` : ''}</span>
          </span>
          <span className="text-xs text-neutral-500">{openQueue ? 'hide' : 'show'}</span>
        </button>

        {openQueue && (
          <div className="border-t border-neutral-800 p-3">
            {!queue && !error && <p className="text-xs text-neutral-500">Loading…</p>}
            {queue && queue.length === 0 && <p className="text-xs text-neutral-500">No heavy models currently running.</p>}
            {queue && queue.length > 0 && (
              <ol className="space-y-1">
                {queue.map((task) => (
                  <li key={task.task_id} className="flex items-baseline gap-2 text-sm p-2 bg-neutral-800/50 rounded">
                    <div className="flex-1">
                      <div className="font-mono text-neutral-300">{task.model}</div>
                      <div className="text-xs text-neutral-500">
                        {task.caller} on {task.machine} (PID: {task.pid})
                      </div>
                      <div className="text-xs text-neutral-600">
                        Started: {formatDate(task.created_at)}
                      </div>
                    </div>
                    <span className="shrink-0 text-xs bg-blue-900/50 text-blue-300 px-1.5 py-0.5 rounded">
                      {task.status}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
