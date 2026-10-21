import { useEffect, useState } from 'react'
import FileView from './FileView.jsx'

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
        title={`${item.path} · ${item.label || 'File'}`}
      >
        <span className="flex items-center gap-2">
          <span className="truncate">📄 {item.path.split('/').pop()}</span>
          <span className="shrink-0 rounded bg-neutral-800 px-1 text-[10px] text-neutral-400">{item.label || 'File'}</span>
        </span>
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

function FileViewer({ file, loading, error }) {
  if (error) {
    return <div className="p-6 text-red-400">Failed to load: {error}</div>
  }
  if (loading) {
    return <div className="p-6 text-neutral-500">Loading…</div>
  }
  if (!file) {
    return (
      <div className="flex h-full flex-1 items-center justify-center text-neutral-500">
        Select a file to view it
      </div>
    )
  }
  const fills = file.kind === 'pdf' || file.kind === 'html'
  return (
    <div className={`min-w-0 flex-1 overflow-auto p-6${fills ? ' flex flex-col' : ''}`}>
      <FileView
        key={file.path}
        file={file}
        loadImage={(src) => window.api.outbox.image(file.path, src)}
        onReveal={() => window.api.outbox.reveal(file.path).catch(() => {})}
        onOpenFile={() => window.api.outbox.open(file.path).catch(() => {})}
        onOpenLink={(url) => window.api.outbox.openLink(url).catch(() => {})}
      />
    </div>
  )
}

export default function FilesExplorer() {
  const [tree, setTree] = useState([])
  const [selectedPath, setSelectedPath] = useState(null)
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

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
      setFile(null)
      return
    }

    setLoading(true)
    setError(null)
    // Per-selection flag: a slow read of the previous file can never overwrite the one now selected.
    let live = true
    window.api.outbox
      .content(selectedPath)
      .then((result) => live && setFile(result))
      .catch((err) => live && setError(String(err)))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [selectedPath])

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-neutral-800 p-3">
        <p className="text-xs text-neutral-500">Files in ~/.claude/outbox</p>
      </div>
      <div className="flex min-h-0 flex-1">
        <FileTree tree={tree} onSelect={setSelectedPath} selectedPath={selectedPath} />
        <FileViewer file={file} loading={loading} error={error} />
      </div>
    </div>
  )
}
