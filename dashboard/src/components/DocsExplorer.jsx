import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { extractOutline } from '../lib/docs_text.js'

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

const HEADING_SELECTOR = 'h1,h2,h3,h4,h5,h6'

function Outline({ content, onJump }) {
  const outline = useMemo(() => extractOutline(content).filter((h) => h.level <= 3), [content])
  if (outline.length < 3) return null
  return (
    <nav className="sticky top-0 hidden max-h-screen w-56 shrink-0 overflow-auto border-l border-neutral-800 p-3 xl:block">
      <p className="mb-2 text-xs uppercase tracking-wide text-neutral-500">On this page</p>
      {outline.map((h) => (
        <button
          key={h.index}
          onClick={() => onJump(h.index)}
          style={{ paddingLeft: `${(h.level - 1) * 10}px` }}
          className="block w-full truncate py-0.5 text-left text-xs text-neutral-400 hover:text-white"
          title={h.text}
        >
          {h.text}
        </button>
      ))}
    </nav>
  )
}

function DocViewer({ content, loading, error, scrollRef, onJump }) {
  if (error) return <div className="p-6 text-red-400">Failed to load: {error}</div>
  if (loading) return <div className="p-6 text-neutral-500">Loading…</div>
  if (content === null) {
    return (
      <div className="flex h-full items-center justify-center text-neutral-500">
        Select a file to view it, or search above
      </div>
    )
  }
  return (
    <div className="flex">
      <div ref={scrollRef} className="min-w-0 max-w-3xl flex-1 p-6">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {content}
        </ReactMarkdown>
      </div>
      <Outline content={content} onJump={onJump} />
    </div>
  )
}

function Highlight({ text, terms }) {
  if (!terms.length) return text
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'ig')
  return text.split(re).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="rounded bg-amber-500/30 px-0.5 text-amber-100">
        {part}
      </mark>
    ) : (
      part
    )
  )
}

function SearchResults({ state, query, onOpen }) {
  if (!state) return <div className="p-6 text-neutral-500">Searching…</div>
  const { results, indexing, docCount, indexedAt } = state
  return (
    <div className="max-w-3xl p-6">
      <p className="mb-3 text-xs text-neutral-500">
        {results.length} result{results.length === 1 ? '' : 's'} for “{query}” across {docCount} docs
        {indexing ? ' · refreshing index…' : indexedAt ? ` · indexed ${formatTimestamp(indexedAt)}` : ''}
      </p>
      {results.length === 0 && <p className="text-neutral-500">Nothing matched. All words must appear in the same section.</p>}
      <ul className="flex flex-col gap-2">
        {results.map((r, i) => (
          <li key={`${r.repo}/${r.path}/${r.headingIndex}/${i}`}>
            <button
              onClick={() => onOpen(r)}
              className="w-full rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-left transition-colors hover:border-neutral-600"
            >
              <p className="text-xs text-neutral-500">
                {r.repo} / {r.path}
              </p>
              <p className="mt-0.5 text-sm font-medium text-white">
                <Highlight text={r.heading || r.label} terms={r.terms} />
              </p>
              <p className="mt-1 text-xs leading-relaxed text-neutral-400">
                <Highlight text={r.snippet} terms={r.terms} />
              </p>
            </button>
          </li>
        ))}
      </ul>
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
  const [query, setQuery] = useState('')
  const [searchState, setSearchState] = useState(null)
  const [showResults, setShowResults] = useState(false)
  const [pendingHeading, setPendingHeading] = useState(null)
  const scrollRef = useRef(null)

  useEffect(() => {
    window.api.docs.repos().then(setCache).catch(() => {})
  }, [])

  // Debounced search; a stale response never overwrites a newer query's.
  useEffect(() => {
    if (!query.trim()) {
      setSearchState(null)
      setShowResults(false)
      return
    }
    setShowResults(true)
    let live = true
    const id = setTimeout(() => {
      window.api.docs
        .search(query)
        .then((r) => live && setSearchState(r))
        .catch((err) => live && setError(String(err)))
    }, 200)
    return () => {
      live = false
      clearTimeout(id)
    }
  }, [query])

  function jumpToHeading(index) {
    const el = scrollRef.current?.querySelectorAll(HEADING_SELECTOR)[index]
    el?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  // After a file opened from a search result renders, scroll to the matched section.
  useEffect(() => {
    if (pendingHeading === null || content === null) return
    if (pendingHeading >= 0) jumpToHeading(pendingHeading)
    setPendingHeading(null)
  }, [content, pendingHeading])

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

  function loadTree(repoName) {
    setTree([])
    window.api.docs.tree(repoName).then(setTree).catch((err) => setError(String(err)))
  }

  function handleSelectRepo(repoName) {
    setSelectedRepo(repoName)
    setSelectedPath(null)
    setContent(null)
    setShowResults(false)
    loadTree(repoName)
  }

  function openFile(repoName, filePath, headingIndex = null) {
    setSelectedPath(filePath)
    setContent(null)
    setLoading(true)
    setError(null)
    setShowResults(false)
    setPendingHeading(headingIndex)
    window.api.docs
      .content(repoName, filePath)
      .then((text) => setContent(text))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false))
  }

  function handleOpenResult(r) {
    if (r.repo !== selectedRepo) {
      setSelectedRepo(r.repo)
      loadTree(r.repo)
    }
    openFile(r.repo, r.path, r.headingIndex)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-neutral-800 p-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Escape' && setQuery('')}
          placeholder="Search all docs…  (every word must appear in the same section)"
          className="w-full max-w-xl rounded border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm text-white placeholder-neutral-600 focus:border-neutral-500 focus:outline-none"
        />
        {query && !showResults && (
          <button onClick={() => setShowResults(true)} className="text-xs text-neutral-400 hover:text-neutral-200">
            ← Back to results
          </button>
        )}
      </div>
      <div className="flex min-h-0 flex-1">
        <RepoList
          repos={cache.repos}
          generatedAt={cache.generated_at}
          refreshing={refreshing}
          onRefresh={handleRefresh}
          selected={selectedRepo}
          onSelect={handleSelectRepo}
        />
        {selectedRepo && <DocTree tree={tree} selectedPath={selectedPath} onSelect={(p) => openFile(selectedRepo, p)} />}
        <div className="flex-1 overflow-auto">
          {showResults ? (
            <SearchResults state={searchState} query={query} onOpen={handleOpenResult} />
          ) : (
            <DocViewer content={content} loading={loading} error={error} scrollRef={scrollRef} onJump={jumpToHeading} />
          )}
        </div>
      </div>
    </div>
  )
}
