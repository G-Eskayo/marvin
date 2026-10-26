import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import FileView from './FileView.jsx'
import Related, { useRelated } from './Related.jsx'
import { extractOutline } from '../lib/docs_text.js'
import { isNotebookPath, notebookToMarkdown } from '../lib/ipynb.js'
import { docsCacheFrom, savedCopyLine } from '../lib/docs_cache.js'
import { getCachedFile, putCachedFile, clearCachedFiles, prefetchTextFiles } from '../lib/outbox_text_cache.js'
import { KINDS, KIND_LABEL, groupTree, visibleKinds, toggleChip, mainView, searchGroups, countLine, overviewPicks, formatDay, matchedBy, deliverableSummary, rankedResults } from '../lib/docs_view.js'
import { formatSize as kindSize } from '../lib/file_kinds.js'
import { DeliverablesGrid, DeliverableHeader, FolderGrid, TicketChip, Thumbs } from './DocsDeliverables.jsx'

function formatTimestamp(iso) {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

const MASTER_ID = '__master__'
const UNSORTED_ID = '__unsorted__'

const RepoList = memo(function RepoList({ repos, generatedAt, refreshing, onRefresh, selected, onSelect }) {
  return (
    <div className="flex w-60 shrink-0 flex-col border-r border-neutral-800">
      <div className="flex items-center justify-between border-b border-neutral-800 p-3">
        <span className="text-xs uppercase tracking-wide text-neutral-500">Projects ({repos.filter((r) => r.id !== MASTER_ID && r.id !== UNSORTED_ID).length})</span>
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
                } ${repo.id === MASTER_ID ? 'border-b border-neutral-800 font-medium text-amber-200' : repo.id === UNSORTED_ID ? 'border-b border-neutral-800 text-neutral-300' : repo.status === 'dormant' || repo.status === 'archived' ? 'text-neutral-500' : 'text-neutral-300'}`}
              >
                <span className="truncate">{repo.name}</span>
                {repo.id === UNSORTED_ID && <span className="ml-auto shrink-0 rounded bg-neutral-800 px-1.5 text-[11px] text-neutral-400">{repo.count}</span>}
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
})

// Level 2 of the drill-down: ONE chip row (Docs / Decisions / Deliverables) at the top of the tree column, level with
// the sidebar's "Projects" header. It filters the tree while browsing and the results while searching (#570).
function ChipRow({ chips, counts, onToggle }) {
  return (
    <div className="flex items-center gap-1 border-b border-neutral-800 px-2 py-2.5">
      {KINDS.map((k) => (
        <button
          key={k}
          data-chip={k}
          onClick={() => onToggle(k)}
          className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
            chips.has(k) ? 'border-neutral-500 bg-neutral-700 text-white' : 'border-neutral-700 text-neutral-400 hover:border-neutral-500 hover:text-neutral-200'
          }`}
        >
          {KIND_LABEL[k]} <span className="text-neutral-500">{counts[k]}</span>
        </button>
      ))}
    </div>
  )
}

function GroupHeader({ label, count, open, onToggle, selected }) {
  return (
    <button data-group={label.toLowerCase()} onClick={onToggle} className={`mt-3 flex w-full items-center rounded px-1 py-1 text-left text-xs uppercase tracking-wide first:mt-0 ${selected ? 'bg-neutral-800 text-white' : 'text-neutral-300 hover:text-white'}`}>
      <span className="mr-1 text-[9px] text-neutral-500">{open ? '▾' : '▸'}</span>
      {label}
      <span className="ml-auto text-[10px] normal-case text-neutral-600">{count}</span>
    </button>
  )
}

function FolderRow({ label, count, open, onToggle, selected, depth = 0, children, title }) {
  return (
    <button
      onClick={onToggle}
      title={title || label}
      style={{ paddingLeft: `${8 + depth * 14}px` }}
      className={`flex w-full items-center rounded py-1 pr-2 text-left text-sm transition-colors ${selected ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'}`}
    >
      <span className="mr-1 text-[9px] text-neutral-500">{open ? '▾' : '▸'}</span>
      <span className="truncate">{label}</span>
      {children}
      {count != null && <span className="ml-auto pl-2 text-[10px] text-neutral-600">{count}</span>}
    </button>
  )
}

function KindBadge({ label }) {
  return <span className="ml-auto shrink-0 rounded bg-neutral-800 px-1 text-[10px] text-neutral-400">{label}</span>
}

function MoreRow({ n, noun, onClick }) {
  return (
    <button onClick={onClick} className="px-2 py-0.5 text-left text-[11px] text-neutral-600 hover:text-neutral-400">
      + {n} more{noun ? ` ${noun}` : ''}
    </button>
  )
}

// One outbox folder's children, read when it is expanded (outbox:list, one folder at a time, local).
function OutboxChildren({ path, depth, sel, onSelectFile, onSelectFolder, open, toggle }) {
  const [listing, setListing] = useState(null)
  useEffect(() => {
    let live = true
    window.api.outbox
      .list(path)
      .then((l) => {
        if (!live) return
        setListing(l)
        prefetchTextFiles(l.entries, (p) => window.api.outbox.content(p)) // at idle: the next open renders at once
      })
      .catch(() => live && setListing({ entries: [], more: 0 }))
    return () => {
      live = false
    }
  }, [path])
  if (!listing) return <p style={{ paddingLeft: `${8 + depth * 14}px` }} className="py-0.5 text-[11px] text-neutral-600">…</p>
  return (
    <>
      {listing.entries.map((c) =>
        c.type === 'dir' ? (
          <div key={c.path}>
            <FolderRow label={c.name} depth={depth} open={open.has(c.path)} selected={sel?.type === 'folder' && sel.path === c.path} onToggle={() => { toggle(c.path); onSelectFolder(c.path) }} />
            {open.has(c.path) && <OutboxChildren path={c.path} depth={depth + 1} sel={sel} onSelectFile={onSelectFile} onSelectFolder={onSelectFolder} open={open} toggle={toggle} />}
          </div>
        ) : (
          <button
            key={c.path}
            onClick={() => onSelectFile(c.path)}
            title={c.path}
            style={{ paddingLeft: `${22 + depth * 14}px` }}
            className={`flex w-full items-center gap-2 rounded py-1 pr-2 text-left text-sm transition-colors ${sel?.type === 'deliverable' && sel.path === c.path ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'}`}
          >
            <span className="truncate">{c.name}</span>
            <KindBadge label={c.label} />
          </button>
        )
      )}
      {listing.more > 0 && <p style={{ paddingLeft: `${22 + depth * 14}px` }} className="py-0.5 text-[11px] text-neutral-600">+ {listing.more} more</p>}
    </>
  )
}

// Level 3: the tree. Three collapsible groups; only the ones the chips allow show.
// Which groups and folders are open, remembered per project while the app runs (recommended default, #570 Decisions).
const treeMemory = new Map() // projectId -> { closed, open, allFolders, allDecisions }

const DocTree = memo(function DocTree({ projectId, groups, chips, sel, onSelectDoc, onSelectFolder, onSelectFile, onTicket, unsorted, leftovers, onSelectUnsortedRoot }) {
  const saved = treeMemory.get(projectId)
  const [closed, setClosed] = useState(() => saved?.closed || new Set(['decisions']))
  const [open, setOpen] = useState(() => saved?.open || new Set())
  const [allFolders, setAllFolders] = useState(() => saved?.allFolders || false)
  const [allDecisions, setAllDecisions] = useState(() => saved?.allDecisions || false)
  useEffect(() => {
    treeMemory.set(projectId, { closed, open, allFolders, allDecisions })
  }, [projectId, closed, open, allFolders, allDecisions])
  const toggle = (key) => setOpen((o) => toggleChip(o, key))
  const show = new Set(visibleKinds(chips))
  // Decisions start collapsed (marvin has 69); choosing the Decisions chip opens them.
  const isOpen = (k) => (k === 'decisions' && chips.has('decisions') ? !closed.has('decisions-chip') : !closed.has(k))
  const flip = (k) => setClosed((c) => toggleChip(c, k === 'decisions' && chips.has('decisions') ? 'decisions-chip' : k))
  const docItem = (item) => <TreeItem key={item.path} item={item} selected={sel?.type === 'doc' && sel.path === item.path} onSelect={onSelectDoc} />

  if (unsorted) {
    return (
      <div className="p-2">
        <GroupHeader label="Deliverables" count={groups.deliverables.count + (leftovers || []).reduce((n, l) => n + l.entries.length, 0)} open selected={!sel} onToggle={onSelectUnsortedRoot} />
        <DeliverableRows entries={groups.deliverables.items} sel={sel} open={open} toggle={toggle} onSelectFolder={onSelectFolder} onSelectFile={onSelectFile} onTicket={onTicket} />
        {leftovers?.length > 0 && <p className="mt-3 px-1 text-xs uppercase tracking-wide text-neutral-500">Left in mixed folders</p>}
        {(leftovers || []).map((l) => (
          <div key={l.parent}>
            <FolderRow label={`${l.parent}/`} count={`${l.entries.length} left`} open={open.has(`left:${l.parent}`)} onToggle={() => toggle(`left:${l.parent}`)} />
            {open.has(`left:${l.parent}`) && <DeliverableRows entries={l.entries} depth={1} sel={sel} open={open} toggle={toggle} onSelectFolder={onSelectFolder} onSelectFile={onSelectFile} onTicket={onTicket} short />}
          </div>
        ))}
      </div>
    )
  }

  const folders = groups.docs.sections
  const decisions = groups.decisions.items
  if (!groups.docs.count && !groups.decisions.count && !groups.deliverables.count) return null // still loading: no empty groups flash
  return (
    <div className="p-2">
      {show.has('docs') && (
        <>
          <GroupHeader label="Docs" count={groups.docs.count} open={isOpen('docs')} onToggle={() => flip('docs')} />
          {isOpen('docs') && (
            <>
              {groups.docs.top.map(docItem)}
              {(allFolders ? folders : folders.slice(0, 4)).map((f) => (
                <div key={f.section}>
                  <FolderRow label={f.section} count={f.items.length} open={open.has(f.section)} onToggle={() => toggle(f.section)} />
                  {open.has(f.section) && <div className="pl-3">{f.items.map(docItem)}</div>}
                </div>
              ))}
              {!allFolders && folders.length > 4 && <MoreRow n={folders.length - 4} noun="folders" onClick={() => setAllFolders(true)} />}
            </>
          )}
        </>
      )}
      {show.has('decisions') && (
        <>
          <GroupHeader label="Decisions" count={groups.decisions.count} open={isOpen('decisions')} onToggle={() => flip('decisions')} />
          {isOpen('decisions') && (
            <>
              {(allDecisions ? decisions : decisions.slice(0, 8)).map(docItem)}
              {!allDecisions && decisions.length > 8 && <MoreRow n={decisions.length - 8} onClick={() => setAllDecisions(true)} />}
            </>
          )}
        </>
      )}
      {show.has('deliverables') && (
        <>
          <GroupHeader label="Deliverables" count={groups.deliverables.count} open={isOpen('deliverables')} onToggle={() => flip('deliverables')} />
          {isOpen('deliverables') && <DeliverableRows entries={groups.deliverables.items} sel={sel} open={open} toggle={toggle} onSelectFolder={onSelectFolder} onSelectFile={onSelectFile} onTicket={onTicket} />}
        </>
      )}
    </div>
  )
})

function DeliverableRows({ entries, depth = 0, sel, open, toggle, onSelectFolder, onSelectFile, onTicket, short = false }) {
  return entries.map((e) => {
    const label = short ? e.path.split('/').pop() : e.name
    if (!e.isDir) {
      return (
        <button
          key={e.path}
          onClick={() => onSelectFile(e.path)}
          title={e.path}
          style={{ paddingLeft: `${8 + depth * 14}px` }}
          className={`flex w-full items-center gap-2 rounded py-1 pr-2 text-left text-sm transition-colors ${sel?.type === 'deliverable' && sel.path === e.path ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'}`}
        >
          <span className="truncate">{label}</span>
          <KindBadge label={(e.kinds || [])[0] || 'File'} />
        </button>
      )
    }
    return (
      <div key={e.path}>
        <FolderRow label={label} depth={depth} count={e.count} open={open.has(e.path)} selected={sel?.type === 'folder' && sel.path === e.path} onToggle={() => { toggle(e.path); onSelectFolder(e.path) }} title={`${e.path} · ${matchedBy(e)}`}>
          <TicketChip number={e.ticket} onOpen={onTicket} />
        </FolderRow>
        {open.has(e.path) && <OutboxChildren path={e.path} depth={depth + 1} sel={sel} onSelectFile={onSelectFile} onSelectFolder={onSelectFolder} open={open} toggle={toggle} />}
      </div>
    )
  })
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

// The saved copy's age and check (#565), after the source line: the dot and pulse are DispatchStatusBadge's classes.
const COPY_DOT = { checking: 'animate-pulse bg-blue-500', ok: 'bg-emerald-500', stale: 'bg-neutral-600' }
function SavedCopyNote({ line }) {
  if (!line) return null
  return (
    <>
      <span className="px-1">·</span>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${COPY_DOT[line.dot]}`} />
      <span className="text-neutral-500">{line.text}</span>
    </>
  )
}

const HEADING_SELECTOR = 'h1,h2,h3,h4,h5,h6'

// Docs already read this session (#570 speed budget: a reopen renders once, with no IPC). Bounded; cleared by the
// `docs` trigger (a local doc or git ref changed) and per repo when a GitHub-only project's check finds a change.
const docTexts = new Map()
function rememberDoc(key, text) {
  if (typeof text !== 'string' || text.length > 400 * 1024) return
  docTexts.delete(key)
  docTexts.set(key, text)
  while (docTexts.size > 60) docTexts.delete(docTexts.keys().next().value)
}

// A function whose identity never changes but always calls the latest `fn`: lets the memoized sidebar and tree skip
// re-rendering when only the main pane's content changes (speed budget, #570).
function useStable(fn) {
  const ref = useRef(fn)
  ref.current = fn
  return useCallback((...args) => ref.current(...args), [])
}

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

function DocViewer({ content: rawContent, path, loading, error, scrollRef, onJump, ctx, onLink, rel, onTicket, onDoc, onPr, after = null, related = true }) {
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
        {/* The shared file viewer (#402): same renderer as the Files tab, and inline images open the full-size viewer. */}
        <FileView key={path} file={{ kind: 'markdown', content, name: path, path }} markdown={{ ctx, onLink }} />
        {after}
        {related && <Related rel={rel} onTicket={onTicket} onDoc={onDoc} onPr={onPr} />}
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

// A search: one list ranked by match, each result tagged with its kind (#611); the chip row (same row, same spot) filters
// it, and the
// count line says what it hides (mock-up ticket-403-f-4).
function SearchResults({ state, query, chips, onOpen, nameOf, files, onOpenProject }) {
  if (!state) return <div className="p-6 text-neutral-500">Searching…</div>
  const { results, indexing, docCount, deliverableCount, indexedAt } = state
  const grouped = searchGroups(results, chips)
  return (
    <div className="max-w-3xl p-6">
      <p className="mb-3 text-xs text-neutral-500">
        {countLine({ query, docCount, deliverableCount, chips, grouped })}
        {indexing ? ' · refreshing index…' : indexedAt && !chips.size ? ` · indexed ${formatTimestamp(indexedAt)}` : ''}
      </p>
      {results.length === 0 && <p className="text-neutral-500">Nothing matched. All words must appear in the same section.</p>}
      {/* One list ranked by match, best first whatever its kind; each card carries its kind's tag (#611). */}
      <ul className="mb-4 flex flex-col gap-2">
        {rankedResults(results, chips).map((r, i) => (
          <li key={`${r.repo}/${r.path}/${r.headingIndex}/${i}`}>
            <ResultCard r={r} nameOf={nameOf} onOpen={onOpen} />
          </li>
        ))}
      </ul>
      <FilesSection files={files} onOpenProject={onOpenProject} />
    </div>
  )
}

function ResultCard({ r, nameOf, onOpen }) {
  const deliverable = r.kind === 'deliverable'
  const rel = deliverable ? r.path.replace(/^outbox\//, '').replace(/\/$/, '') : null
  const [info, setInfo] = useState(null)
  useEffect(() => {
    if (!deliverable) return
    let live = true
    window.api.outbox.summary(rel).then((s) => live && setInfo(s)).catch(() => {})
    return () => {
      live = false
    }
  }, [rel])
  const where = deliverable ? `${nameOf(r.repo)} / outbox / ${r.path.replace(/^outbox\//, '')}` : `${nameOf(r.repo)} / ${r.path}`
  // A deliverable's first heading is its path words; only a heading inside the file itself is worth showing as the title.
  const title = deliverable ? (r.headingIndex > 0 ? r.heading : r.label) : r.heading || r.label
  return (
    <button onClick={() => onOpen(r)} className="w-full rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-left transition-colors hover:border-neutral-600">
      <p className="flex items-center text-xs text-neutral-500">
        {where}
        {r.tag && <span className="ml-1 shrink-0 rounded bg-neutral-800 px-1 text-[10px] text-neutral-400">{r.tag}</span>}
        <StateBadge state={r.state} />
      </p>
      <p className="mt-0.5 text-sm font-medium text-white">
        <Highlight text={title} terms={r.terms} />
      </p>
      {deliverable && info ? (
        <p className="mt-1 text-xs text-neutral-400">{info.isDir ? `${info.count} files · name match` : `${(info.kinds || [])[0] || 'File'} · in ${rel.split('/').slice(0, -1).join('/') || 'the outbox'}`}</p>
      ) : (
        <p className="mt-1 text-xs leading-relaxed text-neutral-400">
          <Highlight text={r.snippet} terms={r.terms} />
        </p>
      )}
      {deliverable && info && <Thumbs rels={info.covers} />}
    </button>
  )
}

// The overview's summary cards (mock-ups f-3, f-5a): one per group the chips allow, with "Show all N →".
function SummaryCards({ groups, chips, headings, onShowAll, onOpenDoc, onOpenDeliverable }) {
  const picks = overviewPicks(groups)
  const show = visibleKinds(chips)
  const row = (key, left, right, onClick) => (
    <button key={key} onClick={onClick} className="grid w-full grid-cols-[14rem_1fr] gap-4 py-0.5 text-left text-sm hover:text-white">
      <span className="truncate font-mono text-xs leading-5 text-neutral-500">{left}</span>
      <span className="truncate text-neutral-300">{right}</span>
    </button>
  )
  const box = (kind, count, rows) => (
    <div key={kind} className="mt-3 rounded-lg border border-neutral-800 bg-neutral-900 p-3">
      <p className="mb-2 flex items-center text-xs uppercase tracking-wide text-neutral-400">
        {KIND_LABEL[kind]} <span className="ml-2 normal-case text-neutral-600">{count}</span>
        <button onClick={() => onShowAll(kind)} className="ml-auto normal-case tracking-normal text-neutral-400 hover:text-white">Show all {count} →</button>
      </p>
      {rows}
    </div>
  )
  return (
    <div className="mt-4">
      {show.includes('docs') && picks.docs.length > 0 && box('docs', groups.docs.count, picks.docs.map((d) => row(d.path, d.path, headings[d.path] || d.label, () => onOpenDoc(d.path))))}
      {show.includes('decisions') && picks.decisions.length > 0 && box('decisions', groups.decisions.count, picks.decisions.map((d) => row(d.path, d.label || d.path.split('/').pop(), headings[d.path] || d.label, () => onOpenDoc(d.path))))}
      {show.includes('deliverables') && picks.deliverables.length > 0 && box('deliverables', groups.deliverables.count, picks.deliverables.map((e) => row(e.path, e.name, deliverableSummary(e), () => onOpenDeliverable(e))))}
    </div>
  )
}

export default function DocsExplorer({ nav, onOpenBoard, onOpenTicket, onOpenPr }) {
  const [cache, setCache] = useState({ generated_at: null, repos: [] })
  const [refreshing, setRefreshing] = useState(false)
  const [selectedRepo, setSelectedRepo] = useState(null)
  const [tree, setTree] = useState([])
  const [deliverables, setDeliverables] = useState([])
  const [leftovers, setLeftovers] = useState([])
  const [chips, setChips] = useState(() => new Set())
  // What the tree selected: { type: 'doc' | 'folder' | 'deliverable', path } (level 3), or null for the project itself.
  const [sel, setSel] = useState(null)
  const [content, setContent] = useState(null)
  const [file, setFile] = useState(null)
  const [listing, setListing] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [searchState, setSearchState] = useState(null)
  const [showResults, setShowResults] = useState(false)
  const [pendingHeading, setPendingHeading] = useState(null)
  const [source, setSource] = useState(null)
  // #565: a GitHub-only project's saved copy and its one open-time check ({ copy, status }).
  const [copyCheck, setCopyCheck] = useState(null)
  const [headings, setHeadings] = useState({})
  const [docsTick, setDocsTick] = useState(0)
  const [filesState, setFilesState] = useState(null)
  const scrollRef = useRef(null)
  const [boardSummary, setBoardSummary] = useState(null)
  const handledNav = useRef(null)
  const selectedPath = sel?.type === 'doc' ? sel.path : null
  const openRef = useRef({ repo: null, path: null })
  openRef.current = { repo: selectedRepo, path: selectedPath }

  useEffect(() => {
    window.api.docs.repos().then((r) => setCache(docsCacheFrom(r))).catch(() => {})
    // #611: opening Docs fast-forwards clean local clones in the background (at most once per project per 30 min).
    window.api.docs.freshen?.().catch(() => {})
  }, [])

  // Debounced search; a stale response never overwrites a newer query's. Only a new QUERY opens the results: a docs
  // change (docsTick) re-runs the search quietly, or a doc opened from a result got yanked back to the list (2026-10-09).
  const lastQuery = useRef(null)
  useEffect(() => {
    if (!query.trim()) {
      setSearchState(null)
      setShowResults(false)
      lastQuery.current = query
      return
    }
    if (lastQuery.current !== query) setShowResults(true)
    lastQuery.current = query
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

  // Local docs, git refs or the outbox changed (file watches in the main process): refresh what is on screen in
  // place, without resetting scroll or selection.
  useEffect(
    () =>
      window.api.triggers.on((t) => {
        if (t.topic === 'outbox') clearCachedFiles() // outbox changed: never show stale deliverable text
        if (t.topic === 'docs') docTexts.clear() // a doc changed on disk: re-read on the next open
        if (t.topic === 'docs' || t.topic === 'outbox') setDocsTick((n) => n + 1)
      }),
    []
  )
  // The badges' background git status came back different: redraw the tree in place.
  const [statesTick, setStatesTick] = useState(0)
  useEffect(() => window.api.triggers.on((t) => t.topic === 'docs-states' && setStatesTick((n) => n + 1)), [])
  useEffect(() => {
    if (statesTick && selectedRepo) loadTree(selectedRepo, { keep: true })
  }, [statesTick])
  useEffect(() => {
    if (docsTick === 0) return
    window.api.docs.repos().then((r) => setCache(docsCacheFrom(r))).catch(() => {})
    if (selectedRepo) loadTree(selectedRepo, { keep: true })
    if (selectedRepo && selectedPath) {
      window.api.docs
        .content(selectedRepo, selectedPath)
        .then((text) => {
          rememberDoc(`${selectedRepo}\0${selectedPath}`, text)
          setContent((cur) => (cur === text ? cur : text))
        })
        .catch(() => {})
    }
  }, [docsTick])

  // Relationships: how #12 / ADR 0033 in this project's text resolve, and what points at this doc.
  const [docCtx, setDocCtx] = useState(null)
  useEffect(() => {
    setDocCtx(null)
    if (selectedRepo && selectedRepo !== MASTER_ID && selectedRepo !== UNSORTED_ID) window.api.relations.context(selectedRepo).then(setDocCtx).catch(() => {})
  }, [selectedRepo, docsTick])
  const isRealDoc = selectedRepo && selectedRepo !== MASTER_ID && selectedRepo !== UNSORTED_ID && selectedPath && selectedPath !== 'PROJECT.md'
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

  // Deep link from an Activity board, an MR, or an old Files link: open that project's card, doc or deliverable.
  useEffect(() => {
    if (nav?.tab === 'docs' && nav.projectId && handledNav.current !== nav.at) {
      handledNav.current = nav.at
      setQuery('')
      handleSelectRepo(nav.projectId)
      if (nav.outboxPath) openDeliverableFile(nav.outboxPath)
      else if (nav.path) openFile(nav.projectId, nav.path)
    }
  }, [nav?.at])

  // The board line shows where the project's tickets stand, on the overview and the Deliverables grid.
  const selectedProject = cache.repos.find((r) => r.id === selectedRepo)
  const view = mainView({ chips, selection: sel, searching: showResults })
  const projectLevel = view === 'overview' || view === 'grid'
  useEffect(() => {
    setBoardSummary(null)
    if (!selectedProject?.board || !selectedProject.repo || !projectLevel) return
    let live = true
    window.api.boards
      .summary(selectedProject.repo)
      .then((r) => live && setBoardSummary(r))
      .catch(() => {})
    return () => {
      live = false
    }
  }, [selectedRepo, projectLevel, docsTick, selectedProject?.board])

  const groups = useMemo(() => groupTree(tree, deliverables), [tree, deliverables])

  // The overview's summary rows show each doc's first heading (local files or the saved copy, never the network).
  useEffect(() => {
    if (!selectedRepo || selectedRepo === MASTER_ID || selectedRepo === UNSORTED_ID || view !== 'overview') return
    const picks = overviewPicks(groups)
    const paths = [...picks.docs, ...picks.decisions].map((d) => d.path).filter((p) => !(p in headings))
    if (!paths.length) return
    let live = true
    window.api.docs.headings(selectedRepo, paths).then((h) => live && setHeadings((cur) => ({ ...cur, ...h }))).catch(() => {})
    return () => {
      live = false
    }
  }, [selectedRepo, groups, view])

  const nameOf = (id) => cache.repos.find((r) => r.id === id)?.name || (id === UNSORTED_ID ? 'Unsorted' : id)

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

  // Opening a project (keep = false) draws its tree from saved state, then, for a GitHub-only project, sends the one
  // conditional request (#565). A change updates the tree and the open file in place: no reload, no spinner.
  function loadTree(repoName, { keep = false } = {}) {
    if (!keep) {
      setTree([])
      setDeliverables([])
      setLeftovers([])
      setCopyCheck(null)
      setHeadings({})
    }
    window.api.docs
      .tree(repoName)
      .then((r) => {
        setTree(r.tree)
        setDeliverables(r.deliverables || [])
        setLeftovers(r.leftovers || [])
        setSource({ source: r.source, dir: r.dir })
        if (keep || r.source !== 'github' || !r.copy) return
        setCopyCheck({ copy: r.copy, status: 'checking' })
        return window.api.docs.revalidate(repoName).then((v) => {
          if (openRef.current.repo !== repoName) return
          setCopyCheck({ copy: v.copy || r.copy, status: v.status })
          if (v.tree) setTree(v.tree)
          const open = openRef.current.path
          if (v.status === 'changed') for (const k of [...docTexts.keys()]) if (k.startsWith(`${repoName}\0`)) docTexts.delete(k)
          if (v.status === 'changed' && open && open !== 'PROJECT.md') {
            window.api.docs
              .content(repoName, open)
              .then((text) => openRef.current.repo === repoName && openRef.current.path === open && setContent((cur) => (cur === text ? cur : text)))
              .catch(() => {})
          }
        })
      })
      .catch((err) => setError(String(err)))
  }

  function handleSelectRepo(repoName) {
    setSelectedRepo(repoName)
    setSel(null)
    setContent(null)
    setFile(null)
    setShowResults(false)
    loadTree(repoName)
    if (repoName !== UNSORTED_ID) openFile(repoName, repoName === MASTER_ID ? 'WHERE-THINGS-ARE.md' : 'PROJECT.md')
  }

  function openFile(repoName, filePath, headingIndex = null) {
    setSel({ type: 'doc', path: filePath })
    setFile(null)
    setError(null)
    setShowResults(false)
    setPendingHeading(headingIndex)
    const key = `${repoName}\0${filePath}`
    if (docTexts.has(key)) {
      setContent(docTexts.get(key)) // read before: one render, no IPC; a docs trigger clears these
      setLoading(false)
      return
    }
    setContent(null)
    setLoading(true)
    window.api.docs
      .content(repoName, filePath)
      .then((text) => {
        rememberDoc(key, text)
        setContent(text)
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false))
  }

  // A deliverable file opens in the main pane through #402's FileView, as a doc does.
  const fileReq = useRef(0)
  function openDeliverableFile(rel) {
    const req = ++fileReq.current
    setSel({ type: 'deliverable', path: rel })
    setShowResults(false)
    setError(null)
    const cached = getCachedFile(rel)
    if (cached) {
      setFile(cached) // already read: one render, no IPC
      setLoading(false)
      return
    }
    setFile(null)
    setLoading(true)
    window.api.outbox
      .content(rel)
      .then((f) => {
        putCachedFile(rel, f)
        if (req === fileReq.current) setFile(f)
      })
      .catch((err) => req === fileReq.current && setError(String(err)))
      .finally(() => req === fileReq.current && setLoading(false))
  }

  function openFolder(rel) {
    const req = ++fileReq.current
    setSel({ type: 'folder', path: rel })
    setShowResults(false)
    setListing(null)
    window.api.outbox
      .list(rel)
      .then((l) => req === fileReq.current && setListing(l))
      .catch(() => req === fileReq.current && setListing({ entries: [], more: 0 }))
  }

  function handleOpenResult(r) {
    if (r.repo !== selectedRepo) {
      setSelectedRepo(r.repo)
      loadTree(r.repo)
    }
    if (r.kind === 'deliverable') {
      const rel = r.path.replace(/^outbox\//, '').replace(/\/$/, '')
      return r.isDir ? openFolder(rel) : openDeliverableFile(rel)
    }
    openFile(r.repo, r.path, r.headingIndex)
  }

  // Which deliverable a file or folder belongs to (for its "matched by" line).
  const ownerOf = (rel) => [...deliverables, ...leftovers.flatMap((l) => l.entries)].find((e) => rel === e.path || rel.startsWith(`${e.path}/`))
  const openTicket = (n) => selectedProject?.repo && onOpenTicket?.(selectedProject.repo, n)
  const matchedTo = (e) => (e?.reason ? `matched to ${nameOf(selectedRepo)} by ${e.reason.replace(/^phrase/, 'the phrase')}` : matchedBy(e))
  const unsorted = selectedRepo === UNSORTED_ID
  const counts = { docs: groups.docs.count, decisions: groups.decisions.count, deliverables: groups.deliverables.count }

  // The chip row filters the levels below it: when it hides what is open, the main pane goes back to the project.
  function onToggleChip(k) {
    const next = toggleChip(chips, k)
    setChips(next)
    const shown = new Set(visibleKinds(next))
    const kindOfSel = !sel ? null : sel.type === 'doc' ? (sel.path === 'PROJECT.md' ? null : sel.path.startsWith('docs/adr/') ? 'decisions' : 'docs') : 'deliverables'
    if (kindOfSel && !shown.has(kindOfSel)) openFile(selectedRepo, 'PROJECT.md')
  }

  const stable = {
    refresh: useStable(handleRefresh),
    selectRepo: useStable(handleSelectRepo),
    unsortedRoot: useStable(() => setSel(null)),
    selectDoc: useStable((p) => openFile(selectedRepo, p)),
    openFolder: useStable(openFolder),
    openFile: useStable(openDeliverableFile),
    ticket: useStable((n) => openTicket(n))
  }

  function sourceText() {
    if (!source) return null
    if (source.source === 'unsorted') return '~/.claude/outbox items no project claims · name one <project>-<topic>-<date> and it files itself'
    if (source.source === 'local') return `Reading local clone · ${source.dir.replace(/^\/Users\/[^/]+/, '~')}`
    if (source.source === 'github') return 'Reading GitHub · no clone of this project on this machine'
    if (source.source === 'master') return 'Generated daily by the tidy agent from the project catalog'
    return 'Generated from the project catalog (no docs of its own yet)'
  }

  function renderMain() {
    if (showResults) return <SearchResults state={searchState} query={query} chips={chips} onOpen={handleOpenResult} nameOf={nameOf} files={filesState} onOpenProject={handleSelectRepo} />
    if (error) return <div className="p-6 text-red-400">Failed to load: {error}</div>
    if (view === 'folder') {
      const owner = ownerOf(sel.path)
      return (
        <>
          <DeliverableHeader
            title={sel.path.split('/').pop()}
            detail={['Deliverable folder', owner && owner.path === sel.path ? formatDay(owner.date) : null, owner && owner.path === sel.path ? `${owner.count} files` : null, owner ? matchedTo(owner) : null].filter(Boolean).join(' · ')}
            onReveal={() => window.api.outbox.reveal(sel.path).catch(() => {})}
          />
          <FolderGrid listing={listing} onOpen={(item) => (item.type === 'dir' ? openFolder(item.path) : openDeliverableFile(item.path))} />
        </>
      )
    }
    if (view === 'file') {
      const owner = ownerOf(sel.path)
      const parent = sel.path.split('/').slice(0, -1).join('/')
      return (
        <>
          <DeliverableHeader
            title={sel.path.split('/').pop()}
            detail={['Deliverable', parent || null, file?.label, file?.size != null ? kindSize(file.size) : null, owner ? matchedTo(owner) : null].filter(Boolean).join(' · ')}
            onReveal={() => window.api.outbox.reveal(sel.path).catch(() => {})}
          />
          {loading || !file ? (
            <div className="p-6 text-neutral-500">Loading…</div>
          ) : (
            <div className={`p-6${file.kind === 'pdf' || file.kind === 'html' ? ' flex h-full flex-col' : ''}`}>
              <FileView
                key={file.path}
                file={file}
                fitImage
                loadImage={(src) => window.api.outbox.image(file.path, src)}
                onReveal={() => window.api.outbox.reveal(file.path).catch(() => {})}
                onOpenFile={() => window.api.outbox.open(file.path).catch(() => {})}
                onOpenLink={(url) => window.api.outbox.openLink(url).catch(() => {})}
              />
            </div>
          )}
        </>
      )
    }
    if (unsorted) {
      return (
        <div className="p-6">
          <DeliverablesGrid entries={deliverables} onOpen={(e) => (e.isDir ? openFolder(e.path) : openDeliverableFile(e.path))} title={false} />
          {leftovers.length > 0 && (
            <p className="mt-6 text-xs text-neutral-500">Left over in mixed folders: {leftovers.map((l) => `${l.parent}/ (${l.entries.length})`).join(' · ')}</p>
          )}
        </div>
      )
    }
    if (view === 'grid') {
      return (
        <div className="p-6">
          <DeliverablesGrid entries={deliverables} onOpen={(e) => (e.isDir ? openFolder(e.path) : openDeliverableFile(e.path))} onTicket={openTicket} />
        </div>
      )
    }
    const overview = view === 'overview' && selectedRepo !== MASTER_ID
    return (
      <DocViewer
        content={content}
        path={selectedPath}
        loading={loading}
        error={null}
        scrollRef={scrollRef}
        onJump={jumpToHeading}
        ctx={docCtx}
        onLink={onLink}
        rel={rel}
        onTicket={onOpenTicket}
        onDoc={openDoc}
        onPr={onOpenPr}
        related={!overview}
        after={
          overview ? (
            <SummaryCards
              groups={groups}
              chips={chips}
              headings={headings}
              onShowAll={(k) => setChips(new Set([k]))}
              onOpenDoc={(p) => openFile(selectedRepo, p)}
              onOpenDeliverable={(e) => (e.isDir ? openFolder(e.path) : openDeliverableFile(e.path))}
            />
          ) : null
        }
      />
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-neutral-800 p-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Escape' && setQuery('')}
          placeholder="Search all docs and deliverables…  (every word must appear in the same section)"
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
          onRefresh={stable.refresh}
          selected={selectedRepo}
          onSelect={stable.selectRepo}
        />
        {selectedRepo && (
          <div className="flex w-72 shrink-0 flex-col border-r border-neutral-800">
            {!unsorted && selectedRepo !== MASTER_ID && <ChipRow chips={chips} counts={counts} onToggle={onToggleChip} />}
            <div className="min-h-0 flex-1 overflow-auto">
              {selectedRepo === MASTER_ID ? (
                <div className="p-2">{tree.map((e) => <TreeItem key={e.path} item={e} selected={selectedPath === e.path} onSelect={(p) => openFile(selectedRepo, p)} />)}</div>
              ) : (
                <DocTree
                  key={selectedRepo}
                  projectId={selectedRepo}
                  groups={groups}
                  chips={chips}
                  sel={sel}
                  unsorted={unsorted}
                  leftovers={leftovers}
                  onSelectUnsortedRoot={stable.unsortedRoot}
                  onSelectDoc={stable.selectDoc}
                  onSelectFolder={stable.openFolder}
                  onSelectFile={stable.openFile}
                  onTicket={stable.ticket}
                />
              )}
            </div>
          </div>
        )}
        <div className="flex-1 overflow-auto">
          {!showResults && source && selectedRepo && (
            <p className="flex items-center gap-1 border-b border-neutral-900 px-6 py-1 text-[11px] text-neutral-600">
              {sourceText()}
              <SavedCopyNote line={source.source === 'github' && copyCheck ? savedCopyLine(copyCheck.copy, copyCheck.status) : null} />
            </p>
          )}
          {!showResults && boardSummary && projectLevel && (
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
          {renderMain()}
        </div>
      </div>
    </div>
  )
}

