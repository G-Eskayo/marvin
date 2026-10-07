import { useEffect, useMemo, useRef, useState } from 'react'
import Markdown from './Markdown.jsx'
import Related, { useRelated } from './Related.jsx'
import { extractOutline } from '../lib/docs_text.js'
import { isNotebookPath, notebookToMarkdown } from '../lib/ipynb.js'
import { docsCacheFrom } from '../lib/docs_cache.js'

function formatTimestamp(iso) {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

const MASTER_ID = '__master__'

function RepoList({ repos, generatedAt, refreshing, onRefresh, selected, onSelect }) {
  return (
    <div className="flex w-60 shrink-0 flex-col border-r border-neutral-800">
      <div className="flex items-center justify-between border-b border-neutral-800 p-3">
        <span className="text-xs uppercase tracking-wide text-neutral-500">Projects ({Math.max(0, repos.length - 1)})</span>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          title={`Rediscover projects now. Last built: ${formatTimestamp(generatedAt)}`}
          className="text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
        >
          {refreshing ? '…' : '↻'}
        </button>
      </div>
      {repos.length === 0 ? (
        <p className="p-3 text-xs text-neutral-500">Building the project catalog… click ↻ if this stays empty.</p>
      ) : (
        <ul className="overflow-auto">
          {repos.map((repo) => (
            <li key={repo.id}>
              <button
                onClick={() => onSelect(repo.id)}
                title={repo.kind === 'portfolio-only' ? 'On the portfolio site only (no repo or folder of its own)' : repo.kind === 'local' ? 'Local folder, not on GitHub' : undefined}
                className={`flex w-full items-center truncate px-3 py-2 text-left text-sm transition-colors ${
                  selected === repo.id ? 'bg-neutral-800 text-white' : 'hover:bg-neutral-900'
                } ${repo.id === MASTER_ID ? 'border-b border-neutral-800 font-medium text-amber-200' : repo.status === 'dormant' || repo.status === 'archived' ? 'text-neutral-500' : 'text-neutral-300'}`}
              >
                <span className="truncate">{repo.name}</span>
                {repo.local && <span title={`Local clone: ${repo.local}`} className="ml-1 text-[10px] text-emerald-500">●</span>}
                {repo.kind === 'portfolio-only' && <span className="ml-1 text-[10px] text-neutral-600">site</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-auto border-t border-neutral-900 p-2 text-[10px] leading-snug text-neutral-600">
        <span className="text-emerald-500">●</span> local clone on this machine (reads your files, shows uncommitted edits) · dim = dormant · site = portfolio page only
      </p>
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

const STATE_BADGE = {
  uncommitted: { text: 'uncommitted', cls: 'bg-amber-950 text-amber-300', hint: 'Changed on this machine, not committed yet' },
  unpushed: { text: 'unpushed', cls: 'bg-sky-950 text-sky-300', hint: 'Committed here but not on GitHub yet (vs. last fetched origin/main)' }
}

function StateBadge({ state }) {
  const b = STATE_BADGE[state]
  if (!b) return null
  return (
    <span title={b.hint} className={`ml-1 shrink-0 rounded px-1 py-px text-[10px] ${b.cls}`}>
      {b.text}
    </span>
  )
}

function TreeItem({ item, selected, onSelect }) {
  return (
    <button
      onClick={() => onSelect(item.path)}
      className={`flex w-full items-center rounded px-2 py-1 text-left text-sm transition-colors ${
        selected ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'
      }`}
    >
      <span className="truncate">{item.label}</span>
      <StateBadge state={item.state} />
    </button>
  )
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

function DocViewer({ content: rawContent, path, loading, error, scrollRef, onJump, ctx, onLink, rel, onTicket, onDoc, onPr }) {
  // A notebook is converted to markdown here, so the outline, the heading jump and the renderer all see the same text.
  const content = useMemo(() => (rawContent !== null && isNotebookPath(path) ? notebookToMarkdown(rawContent) : rawContent), [rawContent, path])
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
        <Markdown content={content} ctx={ctx} onLink={onLink} />
        <Related rel={rel} onTicket={onTicket} onDoc={onDoc} onPr={onPr} />
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

function formatSize(n) {
  if (n == null) return ''
  for (const u of ['B', 'K', 'M', 'G']) {
    if (n < 1024) return `${Math.round(n)}${u}`
    n /= 1024
  }
  return `${Math.round(n)}T`
}

function FileRow({ f, onOpenProject }) {
  return (
    <button
      onClick={() => window.api.docs.reveal(f.path).catch(() => {})}
      title="Show in Finder"
      className="w-full rounded border border-neutral-800 px-3 py-2 text-left transition-colors hover:border-neutral-600"
    >
      <p className="flex items-center gap-2 text-sm text-neutral-200">
        <span className="truncate">{f.name}</span>
        <span className="shrink-0 rounded bg-neutral-800 px-1 text-[10px] text-neutral-400">{f.bucket}</span>
        {f.project && (
          <span
            role="link"
            onClick={(e) => {
              e.stopPropagation()
              onOpenProject(f.project.id)
            }}
            className="shrink-0 rounded bg-emerald-950 px-1 text-[10px] text-emerald-300 hover:bg-emerald-900"
            title="Open this project's card"
          >
            {f.project.name}
          </span>
        )}
      </p>
      <p className="mt-0.5 truncate text-[11px] text-neutral-600">
        {f.mtime ? new Date(f.mtime * 1000).toLocaleDateString() : ''} · {f.isDir ? 'folder' : formatSize(f.size)} · {f.path}
      </p>
    </button>
  )
}

function FileGroup({ title, files, onOpenProject }) {
  const [all, setAll] = useState(false)
  if (!files.length) return null
  const shown = all ? files : files.slice(0, 6)
  return (
    <div className="mt-3">
      <p className="mb-1 text-xs text-neutral-500">
        {title} ({files.length})
      </p>
      <div className="flex flex-col gap-1">
        {shown.map((f) => (
          <FileRow key={f.path} f={f} onOpenProject={onOpenProject} />
        ))}
      </div>
      {files.length > 6 && (
        <button onClick={() => setAll(!all)} className="mt-1 text-xs text-neutral-500 hover:text-neutral-300">
          {all ? 'Show fewer' : `Show all ${files.length}`}
        </button>
      )}
    </div>
  )
}

function FilesSection({ files, onOpenProject }) {
  return (
    <div className="mt-8 border-t border-neutral-800 pt-4">
      <h3 className="text-sm font-medium text-neutral-300">Files on this Mac</h3>
      <p className="text-[11px] text-neutral-600">Documents, Desktop, Downloads and Developer — by name or by text inside the file (same search as the findit command). Click to show in Finder.</p>
      {files === null && <p className="mt-2 text-xs text-neutral-500">Searching files…</p>}
      {files?.error && <p className="mt-2 text-xs text-red-400">File search failed: {files.error}</p>}
      {files && !files.error && files.name.length + files.content.length === 0 && <p className="mt-2 text-xs text-neutral-500">No files matched.</p>}
      {files && (
        <>
          <FileGroup title="Name matches" files={files.name} onOpenProject={onOpenProject} />
          <FileGroup title="Found by text inside the file" files={files.content} onOpenProject={onOpenProject} />
        </>
      )}
    </div>
  )
}

function SearchResults({ state, query, onOpen, nameOf, files, onOpenProject }) {
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
              <p className="flex items-center text-xs text-neutral-500">
                {nameOf(r.repo)} / {r.path}
                <StateBadge state={r.state} />
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
      <FilesSection files={files} onOpenProject={onOpenProject} />
    </div>
  )
}

export default function DocsExplorer({ nav, onOpenBoard, onOpenTicket, onOpenPr }) {
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
  const [source, setSource] = useState(null)
  const [docsTick, setDocsTick] = useState(0)
  const [filesState, setFilesState] = useState(null)
  const scrollRef = useRef(null)
  const [boardSummary, setBoardSummary] = useState(null)
  const handledNav = useRef(null)

  useEffect(() => {
    window.api.docs.repos().then((r) => setCache(docsCacheFrom(r))).catch(() => {})
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
  }, [query, docsTick])

  // Spotlight is slower and costlier than the doc index: wait for typing to settle, and only
  // re-run when the query changes (not on every doc-change trigger).
  useEffect(() => {
    setFilesState(null)
    if (!query.trim()) return
    let live = true
    const id = setTimeout(() => {
      window.api.docs
        .files(query)
        .then((r) => live && setFilesState(r))
        .catch((err) => live && setFilesState({ name: [], content: [], error: String(err) }))
    }, 500)
    return () => {
      live = false
      clearTimeout(id)
    }
  }, [query])

  // Local docs or git refs changed (file watch in the main process): refresh what is on screen
  // in place, without resetting scroll or selection.
  useEffect(() => window.api.triggers.on((t) => t.topic === 'docs' && setDocsTick((n) => n + 1)), [])
  useEffect(() => {
    if (docsTick === 0) return
    window.api.docs.repos().then((r) => setCache(docsCacheFrom(r))).catch(() => {})
    if (selectedRepo) loadTree(selectedRepo, { keep: true })
    if (selectedRepo && selectedPath) {
      window.api.docs
        .content(selectedRepo, selectedPath)
        .then((text) => setContent((cur) => (cur === text ? cur : text)))
        .catch(() => {})
    }
  }, [docsTick])

  // Relationships: how #12 / ADR 0033 in this project's text resolve, and what points at this doc.
  const [docCtx, setDocCtx] = useState(null)
  useEffect(() => {
    setDocCtx(null)
    if (selectedRepo && selectedRepo !== MASTER_ID) window.api.relations.context(selectedRepo).then(setDocCtx).catch(() => {})
  }, [selectedRepo, docsTick])
  const isRealDoc = selectedRepo && selectedRepo !== MASTER_ID && selectedPath && selectedPath !== 'PROJECT.md'
  const rel = useRelated(
    () => (isRealDoc ? window.api.relations.doc(selectedRepo, selectedPath) : Promise.resolve({ docs: [], tickets: [], prs: [] })),
    [selectedRepo, selectedPath, docsTick]
  )

  // Open any doc, in any project (from a link in text or from the Related list).
  function openDoc(project, path) {
    setQuery('')
    setShowResults(false)
    if (project !== selectedRepo) {
      setSelectedRepo(project)
      loadTree(project)
    }
    openFile(project, path)
  }
  const onLink = (link) => (link.type === 'ticket' ? onOpenTicket?.(link.repo, link.number) : openDoc(link.project, link.path))

  // Deep link from an Activity board or an MR: open that project's card (once per navigation).
  useEffect(() => {
    if (nav?.tab === 'docs' && nav.projectId && handledNav.current !== nav.at) {
      handledNav.current = nav.at
      setQuery('')
      handleSelectRepo(nav.projectId)
      if (nav.path) openFile(nav.projectId, nav.path)
    }
  }, [nav?.at])

  // The project card shows where its tickets stand (counts per column) with a link to the board.
  const selectedProject = cache.repos.find((r) => r.id === selectedRepo)
  useEffect(() => {
    setBoardSummary(null)
    if (!selectedProject?.board || !selectedProject.repo || selectedPath !== 'PROJECT.md') return
    let live = true
    window.api.boards
      .summary(selectedProject.repo)
      .then((r) => live && setBoardSummary(r))
      .catch(() => {})
    return () => {
      live = false
    }
  }, [selectedRepo, selectedPath, docsTick, selectedProject?.board])

  const nameOf = (id) => cache.repos.find((r) => r.id === id)?.name || id

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
      setCache(docsCacheFrom(await window.api.docs.refresh()))
    } catch (err) {
      setError(String(err))
    } finally {
      setRefreshing(false)
    }
  }

  function loadTree(repoName, { keep = false } = {}) {
    if (!keep) setTree([])
    window.api.docs
      .tree(repoName)
      .then((r) => {
        setTree(r.tree)
        setSource({ source: r.source, dir: r.dir })
      })
      .catch((err) => setError(String(err)))
  }

  function handleSelectRepo(repoName) {
    setSelectedRepo(repoName)
    setSelectedPath(null)
    setContent(null)
    setShowResults(false)
    loadTree(repoName)
    openFile(repoName, repoName === MASTER_ID ? 'WHERE-THINGS-ARE.md' : 'PROJECT.md')
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
            <SearchResults state={searchState} query={query} onOpen={handleOpenResult} nameOf={nameOf} files={filesState} onOpenProject={handleSelectRepo} />
          ) : (
            <>
              {source && selectedRepo && (
                <p className="border-b border-neutral-900 px-6 py-1 text-[11px] text-neutral-600">
                  {source.source === 'local' ? `Reading local clone · ${source.dir.replace(/^\/Users\/[^/]+/, '~')}` : source.source === 'github' ? 'Reading GitHub · no clone of this project on this machine' : source.source === 'master' ? 'Generated daily by the tidy agent from the project catalog' : 'Generated from the project catalog (no docs of its own yet)'}
                </p>
              )}
              {boardSummary && (
                <div className="flex items-center gap-3 border-b border-neutral-900 px-6 py-2 text-xs text-neutral-400">
                  <span className="text-neutral-500">Board</span>
                  {[['ready', 'ready'], ['progress', 'in progress'], ['review', 'in review'], ['blocked', 'blocked'], ['done', 'done']].map(([id, label]) => (
                    <span key={id} className={id === 'blocked' && boardSummary.counts.blocked ? 'text-red-400' : ''}>
                      {boardSummary.counts[id] ?? 0} {label}
                    </span>
                  ))}
                  <button onClick={() => onOpenBoard?.(selectedProject.repo)} className="ml-auto text-neutral-300 hover:text-white">
                    Open board →
                  </button>
                </div>
              )}
              <DocViewer content={content} path={selectedPath} loading={loading} error={error} scrollRef={scrollRef} onJump={jumpToHeading} ctx={docCtx} onLink={onLink} rel={rel} onTicket={onOpenTicket} onDoc={openDoc} onPr={onOpenPr} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
