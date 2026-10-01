import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function formatTimestamp(iso) {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

function RepoList({ repos, generatedAt, refreshing, onRefresh, selected, onSelect }) {
  return (
    <div className="flex w-56 shrink-0 flex-col border-r border-neutral-800">
      <div className="flex items-center justify-between border-b border-neutral-800 p-3">
        <span className="text-xs uppercase tracking-wide text-neutral-500">Projects</span>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          title={`Last discovered: ${formatTimestamp(generatedAt)}`}
          className="text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
        >
          {refreshing ? '…' : '↻'}
        </button>
      </div>
      {repos.length === 0 ? (
        <p className="p-3 text-xs text-neutral-500">
          No doc-first repos discovered yet. Click ↻ to scan (looks for a CONTEXT.md at the root of each repo).
        </p>
      ) : (
        <ul className="overflow-auto">
          {repos.map((repo) => (
            <li key={repo.name}>
              <button
                onClick={() => onSelect(repo.name)}
                className={`block w-full truncate px-3 py-2 text-left text-sm transition-colors ${
                  selected === repo.name ? 'bg-neutral-800 text-white' : 'text-neutral-300 hover:bg-neutral-900'
                }`}
              >
                {repo.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function DocTree({ tree, selectedPath, onSelect }) {
  return (
    <div className="flex w-56 shrink-0 flex-col overflow-auto border-r border-neutral-800 p-2">
      {tree.map((entry) =>
        entry.section ? (
          <div key={entry.section} className="mt-3">
            <p className="px-1 text-xs uppercase tracking-wide text-neutral-500">{entry.section}</p>
            {entry.items.map((item) => (
              <TreeItem key={item.path} item={item} selected={selectedPath === item.path} onSelect={onSelect} />
            ))}
          </div>
        ) : (
          <TreeItem key={entry.path} item={entry} selected={selectedPath === entry.path} onSelect={onSelect} />
        )
      )}
    </div>
  )
}

function TreeItem({ item, selected, onSelect }) {
  return (
    <button
      onClick={() => onSelect(item.path)}
      className={`block w-full truncate rounded px-2 py-1 text-left text-sm transition-colors ${
        selected ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'
      }`}
    >
      {item.label}
    </button>
  )
}

const markdownComponents = {
  h1: (props) => <h1 className="mb-3 mt-6 text-xl font-semibold text-white first:mt-0" {...props} />,
  h2: (props) => <h2 className="mb-2 mt-5 text-lg font-semibold text-white" {...props} />,
  h3: (props) => <h3 className="mb-2 mt-4 text-base font-semibold text-neutral-100" {...props} />,
  p: (props) => <p className="mb-3 leading-relaxed text-neutral-300" {...props} />,
  a: (props) => <a className="text-blue-400 hover:underline" target="_blank" rel="noreferrer" {...props} />,
  code: ({ inline, ...props }) =>
    inline ? (
      <code className="rounded bg-neutral-800 px-1 py-0.5 font-mono text-sm text-neutral-200" {...props} />
    ) : (
      <code className="block overflow-auto rounded-lg bg-neutral-900 p-3 font-mono text-sm text-neutral-200" {...props} />
    ),
  ul: (props) => <ul className="mb-3 list-disc pl-6 text-neutral-300" {...props} />,
  ol: (props) => <ol className="mb-3 list-decimal pl-6 text-neutral-300" {...props} />,
  blockquote: (props) => <blockquote className="mb-3 border-l-2 border-neutral-700 pl-3 text-neutral-400" {...props} />
}

function DocViewer({ content, loading, error }) {
  if (error) return <div className="p-6 text-red-400">Failed to load: {error}</div>
  if (loading) return <div className="p-6 text-neutral-500">Loading…</div>
  if (content === null) {
    return (
      <div className="flex h-full items-center justify-center text-neutral-500">
        Select a file to view it
      </div>
    )
  }
  return (
    <div className="max-w-3xl p-6">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  )
}

export default function DocsExplorer() {
  const [cache, setCache] = useState({ generated_at: null, repos: [] })
  const [refreshing, setRefreshing] = useState(false)
  const [selectedRepo, setSelectedRepo] = useState(null)
  const [tree, setTree] = useState([])
  const [selectedPath, setSelectedPath] = useState(null)
  const [content, setContent] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    window.api.docs.repos().then(setCache).catch(() => {})
  }, [])

  async function handleRefresh() {
    setRefreshing(true)
    try {
      const repos = await window.api.docs.refresh()
      setCache({ generated_at: new Date().toISOString(), repos })
    } catch (err) {
      setError(String(err))
    } finally {
      setRefreshing(false)
    }
  }

  function handleSelectRepo(repoName) {
    setSelectedRepo(repoName)
    setSelectedPath(null)
    setContent(null)
    setTree([])
    window.api.docs.tree(repoName).then(setTree).catch((err) => setError(String(err)))
  }

  function handleSelectFile(filePath) {
    setSelectedPath(filePath)
    setContent(null)
    setLoading(true)
    setError(null)
    window.api.docs
      .content(selectedRepo, filePath)
      .then((text) => setContent(text))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false))
  }

  return (
    <div className="flex h-full">
      <RepoList
        repos={cache.repos}
        generatedAt={cache.generated_at}
        refreshing={refreshing}
        onRefresh={handleRefresh}
        selected={selectedRepo}
        onSelect={handleSelectRepo}
      />
      {selectedRepo && <DocTree tree={tree} selectedPath={selectedPath} onSelect={handleSelectFile} />}
      <div className="flex-1 overflow-auto">
        <DocViewer content={content} loading={loading} error={error} />
      </div>
    </div>
  )
}
