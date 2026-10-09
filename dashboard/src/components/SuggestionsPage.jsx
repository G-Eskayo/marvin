import { useEffect, useState } from 'react'
import Markdown from './Markdown.jsx'

const PRIORITY_COLORS = {
  1: 'text-red-400',
  2: 'text-orange-400',
  3: 'text-yellow-400',
  4: 'text-blue-400',
  5: 'text-neutral-400'
}

const STATUS_COLORS = {
  pending: 'text-white',
  resolved: 'text-neutral-500'
}

const IMPACT_RANK = { 'token-reduction': 0, 'speed': 1, 'organization': 2, 'pipeline-logic': 3, 'reliability': 4, 'robustness': 5 }
const EFFORT_RANK = { 'low': 0, 'medium': 1, 'high': 2 }

function impactLabel(impact) {
  if (!impact) return '—'
  return impact.replace(/-/g, ' ')
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-neutral-500">
      <p className="text-lg font-medium text-neutral-300">No suggestions yet</p>
      <p className="max-w-md text-sm">Architecture and optimization suggestions will appear here after architecture-review or audit runs.</p>
    </div>
  )
}

function ErrorState({ error }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-neutral-500">
      <p className="text-lg font-medium text-red-400">Could not load suggestions</p>
      <p className="max-w-md text-sm text-neutral-400">{error}</p>
    </div>
  )
}

export function SuggestionRow({ entry, isSelected, onClick, isResolved }) {
  const statusColor = STATUS_COLORS[entry.status] || STATUS_COLORS.pending
  const rowClass = isResolved ? 'text-neutral-600' : 'text-neutral-300'

  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-3 border-b border-neutral-800 px-4 py-3 text-left transition-colors hover:bg-neutral-800 ${
        isSelected ? 'bg-neutral-800' : ''
      } ${rowClass}`}
    >
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{entry.title}</div>
        <div className="flex gap-3 text-xs text-neutral-500 mt-1">
          {entry.priority && <span>P{entry.priority}</span>}
          <span className={statusColor}>{entry.status}</span>
          {entry.impact && <span>{impactLabel(entry.impact)}</span>}
          {entry.effort && <span>{entry.effort}</span>}
        </div>
      </div>
    </button>
  )
}

export function SuggestionDetail({ entry }) {
  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-6">
        <h1 className="font-mono text-xl font-semibold text-white">{entry.title}</h1>
        <div className="flex gap-3 text-xs text-neutral-500 mt-2">
          {entry.priority && <span>Priority: {entry.priority}</span>}
          <span className={STATUS_COLORS[entry.status] || STATUS_COLORS.pending}>
            Status: {entry.status}
          </span>
          {entry.impact && <span>Impact: {impactLabel(entry.impact)}</span>}
          {entry.effort && <span>Effort: {entry.effort}</span>}
        </div>
        {entry.status !== 'pending' && (
          <p className="mt-3 text-xs text-neutral-500">This suggestion has been {entry.status}.</p>
        )}
      </div>

      {/* Render the body as markdown */}
      <div className="prose-invert max-w-none">
        <Markdown content={entry.body} />
      </div>
    </div>
  )
}

export default function SuggestionsPage() {
  const [suggestions, setSuggestions] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedIndex, setSelectedIndex] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const result = await window.api.suggestions.list()
        if (!cancelled) {
          if (result.error) {
            setError(result.error)
            setSuggestions([])
          } else {
            setSuggestions(result.suggestions || [])
            setError(null)
          }
          setLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setError(`Error: ${err.message}`)
          setSuggestions([])
          setLoading(false)
        }
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-neutral-400">
        <p className="text-sm">Loading suggestions…</p>
      </div>
    )
  }

  if (error) {
    return <ErrorState error={error} />
  }

  if (suggestions.length === 0) {
    return <EmptyState />
  }

  const selectedEntry = selectedIndex !== null ? suggestions[selectedIndex] : null

  return (
    <div className="flex h-full gap-4 bg-neutral-950">
      {/* Master list */}
      <div className="w-80 border-r border-neutral-800 overflow-auto">
        <div className="sticky top-0 bg-neutral-900 border-b border-neutral-800 px-4 py-3">
          <h2 className="font-mono text-sm font-semibold text-white">{suggestions.length} Suggestions</h2>
        </div>
        <div>
          {suggestions.map((entry, idx) => (
            <SuggestionRow
              key={idx}
              entry={entry}
              isSelected={selectedIndex === idx}
              isResolved={entry.status !== 'pending'}
              onClick={() => setSelectedIndex(idx)}
            />
          ))}
        </div>
      </div>

      {/* Detail pane */}
      <div className="flex-1 overflow-auto">
        {selectedEntry ? (
          <SuggestionDetail entry={selectedEntry} />
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-neutral-500">
            <p className="text-sm">Select a suggestion to view details</p>
          </div>
        )}
      </div>
    </div>
  )
}
