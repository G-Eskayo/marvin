import { useEffect, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts'

const COLORS = {
  rebuildable_caches: '#60a5fa',
  build_output: '#34d399',
  worktrees: '#fbbf24',
  models: '#f87171',
  icloud_cache: '#c084fc',
  docker: '#fb923c',
  user_files: '#ec4899',
  other: '#6b7280',
}

function formatBytes(kb) {
  if (kb < 1024) return `${kb} KB`
  if (kb < 1024 * 1024) return `${(kb / 1024).toFixed(1)} MB`
  return `${(kb / 1024 / 1024).toFixed(1)} GB`
}

function GrowthBadge({ growth_kb, growth_pct, regenerable }) {
  if (growth_kb === null) return <span className="text-xs text-neutral-500">–</span>

  const isGrowth = growth_kb > 0
  const color = isGrowth ? 'text-red-400' : 'text-green-400'
  const icon = isGrowth ? '↑' : '↓'

  return (
    <span className={`text-xs font-mono ${color}`}>
      {icon} {Math.abs(growth_pct).toFixed(0)}% ({formatBytes(Math.abs(growth_kb))})
    </span>
  )
}

function CategoryRow({ name, details, regenerable }) {
  return (
    <div className="border-b border-neutral-800 py-3">
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <h4 className="font-mono font-semibold text-white">{name}</h4>
          <p className="text-xs text-neutral-400 mt-1">{details.description}</p>
        </div>
        <div className="text-right ml-4">
          <p className="font-mono text-lg text-white">{formatBytes(details.kb)}</p>
          <p className="text-xs text-neutral-400 mt-1">
            modified {new Date(details.last_changed).toLocaleDateString()}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between mt-2">
        <span className={`text-xs px-2 py-1 rounded ${
          regenerable ? 'bg-amber-900 text-amber-200' : 'bg-neutral-700 text-neutral-300'
        }`}>
          {regenerable ? '🔄 Regenerable' : '📌 Keep'}
        </span>
        <GrowthBadge
          growth_kb={details.growth_kb}
          growth_pct={details.growth_pct}
          regenerable={regenerable}
        />
      </div>
    </div>
  )
}

function CategoryChart({ categories }) {
  const data = Object.entries(categories).map(([name, detail]) => ({
    name: detail.label || name,
    value: detail.kb,
  }))

  return (
    <div className="rounded border border-neutral-800 bg-neutral-900 p-4 mb-6">
      <h4 className="font-mono text-sm font-semibold text-white mb-4">Disk usage by category</h4>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data}>
          <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} fontSize={11} stroke="#525252" />
          <YAxis stroke="#525252" fontSize={11} />
          <Tooltip
            formatter={v => formatBytes(v)}
            contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #404040' }}
            labelStyle={{ color: '#e5e7eb' }}
          />
          <Bar dataKey="value" fill="#60a5fa">
            {data.map((entry, index) => {
              const catName = Object.keys(categories).find(k => categories[k].label === entry.name)
              return <Cell key={index} fill={COLORS[catName] || '#60a5fa'} />
            })}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function DiskCategoriesPanel({ device, onClose }) {
  const [categories, setCategories] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function loadCategories() {
      try {
        const data = await window.api.disk.categories(device)
        if (!cancelled) {
          setCategories(data || {})
        }
      } catch (err) {
        if (!cancelled) {
          setError(String(err))
        }
      } finally {
        setLoading(false)
      }
    }

    loadCategories()
    return () => {
      cancelled = true
    }
  }, [device])

  const totalKb = categories ? Object.values(categories).reduce((sum, c) => sum + (c.kb || 0), 0) : 0
  const totalGrowthKb = categories
    ? Object.values(categories).reduce((sum, c) => sum + (c.growth_kb || 0), 0)
    : 0

  return (
    <div className="p-6">
      {onClose && (
        <button onClick={onClose} className="mb-4 text-sm text-neutral-400 hover:text-neutral-200">
          ← Back
        </button>
      )}
      <h2 className="mb-2 font-mono text-lg font-semibold text-white">Disk by category — {device}</h2>
      <p className="mb-4 text-sm text-neutral-400">
        Week-over-week growth from disk ledger. {totalGrowthKb > 0 ? `↑ ${formatBytes(totalGrowthKb)}` : `↓ ${formatBytes(Math.abs(totalGrowthKb))}`}
      </p>

      {loading && <p className="text-neutral-500">Loading…</p>}
      {error && <p className="text-red-400">Error: {error}</p>}
      {!loading && !error && categories && (
        <>
          <div className="rounded border border-neutral-800 bg-neutral-900 p-4 mb-6">
            <div className="flex justify-between">
              <div>
                <p className="text-xs text-neutral-400">Total</p>
                <p className="font-mono text-2xl font-semibold text-white mt-1">{formatBytes(totalKb)}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-neutral-400">Week-over-week</p>
                <p className={`font-mono text-2xl font-semibold mt-1 ${
                  totalGrowthKb > 0 ? 'text-red-400' : 'text-green-400'
                }`}>
                  {totalGrowthKb > 0 ? '+' : ''}{formatBytes(totalGrowthKb)}
                </p>
              </div>
            </div>
          </div>

          {Object.keys(categories).length > 0 && (
            <CategoryChart categories={categories} />
          )}

          <div className="rounded border border-neutral-800 bg-neutral-900 p-4">
            <h4 className="font-mono text-sm font-semibold text-white mb-4">Categories</h4>
            {Object.entries(categories).map(([name, detail]) => (
              <CategoryRow
                key={name}
                name={detail.label || name}
                details={detail}
                regenerable={detail.regenerable}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
