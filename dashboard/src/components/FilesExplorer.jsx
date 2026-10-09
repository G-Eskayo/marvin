import { useEffect, useState, useRef } from 'react'
import Markdown from './Markdown.jsx'

function TreeItem({ item, depth = 0, onSelect, selectedPath }) {
  const [expanded, setExpanded] = useState(false)
  const isSelected = selectedPath === item.path

  if (item.type === 'file') {
    return (
      <button
        onClick={() => onSelect(item.path)}
        style={{ paddingLeft: `${depth * 16}px` }}
        className={`w-full truncate px-2 py-1 text-left text-sm transition-colors ${
          isSelected ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'
        }`}
        title={item.path}
      >
        📄 {item.path.split('/').pop()}
      </button>
    )
  }

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{ paddingLeft: `${depth * 16}px` }}
        className="w-full truncate px-2 py-1 text-left text-sm text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200"
        title={item.path}
      >
        {expanded ? '▼' : '▶'} 📁 {item.path.split('/').pop()}
      </button>
      {expanded && item.children && (
        <div>
          {item.children.map((child) => (
            <TreeItem key={child.path} item={child} depth={depth + 1} onSelect={onSelect} selectedPath={selectedPath} />
          ))}
        </div>
      )}
    </div>
  )
}

function FileTree({ tree, onSelect, selectedPath }) {
  return (
    <div className="flex w-56 shrink-0 flex-col overflow-auto border-r border-neutral-800 p-2">
      {tree.length === 0 ? (
        <p className="p-3 text-xs text-neutral-500">No files in outbox yet</p>
      ) : (
        tree.map((item) => <TreeItem key={item.path} item={item} onSelect={onSelect} selectedPath={selectedPath} />)
      )}
    </div>
  )
}

function FileViewer({ filePath, content, kind, truncated, loading, error }) {
  if (error) {
    return <div className="p-6 text-red-400">Failed to load: {error}</div>
  }
  if (loading) {
    return <div className="p-6 text-neutral-500">Loading…</div>
  }
  if (content === null) {
    return (
      <div className="flex h-full items-center justify-center text-neutral-500">
        Select a file to view it
      </div>
    )
  }

  return (
    <div className="min-w-0 flex-1 overflow-auto p-6">
      {truncated && <div className="mb-4 rounded bg-amber-950 p-3 text-sm text-amber-200">File was truncated (over 2 MB)</div>}
      {kind === 'markdown' && (
        <>
          <Markdown content={content} />
        </>
      )}
      {kind === 'json' && (
        <pre className="mb-3 overflow-auto rounded-lg bg-neutral-900 p-3 font-mono text-sm text-neutral-200">
          {(() => {
            try {
              return JSON.stringify(JSON.parse(content), null, 2)
            } catch {
              return content
            }
          })()}
        </pre>
      )}
      {kind === 'text' && (
        <pre className="mb-3 overflow-auto rounded-lg bg-neutral-900 p-3 font-mono text-sm text-neutral-200">
          {content}
        </pre>
      )}
    </div>
  )
}

export default function FilesExplorer() {
  const [tree, setTree] = useState([])
  const [selectedPath, setSelectedPath] = useState(null)
  const [content, setContent] = useState(null)
  const [kind, setKind] = useState(null)
  const [truncated, setTruncated] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const loadingRef = useRef(false)

  // Load the outbox tree on mount
  useEffect(() => {
    window.api.outbox
      .tree()
      .then((t) => setTree(t))
      .catch((err) => setError(String(err)))
  }, [])

  // Load file content when selection changes
  useEffect(() => {
    if (!selectedPath) {
      setContent(null)
      setKind(null)
      setTruncated(false)
      return
    }

    setLoading(true)
    setError(null)
    loadingRef.current = true

    window.api.outbox
      .content(selectedPath)
      .then((result) => {
        if (loadingRef.current) {
          setContent(result.content)
          setKind(result.kind)
          setTruncated(result.truncated)
        }
      })
      .catch((err) => {
        if (loadingRef.current) {
          setError(String(err))
        }
      })
      .finally(() => {
        if (loadingRef.current) {
          setLoading(false)
        }
      })

    return () => {
      loadingRef.current = false
    }
  }, [selectedPath])

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-neutral-800 p-3">
        <p className="text-xs text-neutral-500">Files in ~/.claude/outbox</p>
      </div>
      <div className="flex min-h-0 flex-1">
        <FileTree tree={tree} onSelect={setSelectedPath} selectedPath={selectedPath} />
        <FileViewer filePath={selectedPath} content={content} kind={kind} truncated={truncated} loading={loading} error={error} />
      </div>
    </div>
  )
}
