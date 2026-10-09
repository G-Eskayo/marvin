import { memo, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { linkify } from '../lib/linkify.js'
import { prepareIssueBody, safeUrl, isKeySection } from '../lib/issueBody.js'
import { parseDashLink } from './Markdown.jsx'

// A ticket or PR description, rendered for reading instead of a scrolling text box (owner, 2026-10-09). Hardcoded and
// deterministic (react-markdown + GFM, no AI); prepared once per body (lib/issueBody.js) and memoized, so a board poll
// that brings back the same text doesn't re-render it. Readability: ~70 characters a line, generous line height and
// section spacing, the ticket template's sections given a quiet accent. Images load through the main process
// (window.api.mr.image) so private repos work and the GitHub token stays out of the page.

// Referenced tickets' titles: "#123" is never shown alone (owner rule). Titles the page already has come in through
// `titles`; otherwise a title is fetched once, on hover, and remembered for the session.
const titleCache = new Map()

function TicketRef({ dash, children, titles, onLink }) {
  const key = `${dash.repo}#${dash.number}`
  const known = titles?.[key] ?? titles?.[`#${dash.number}`] ?? titleCache.get(key)
  const [title, setTitle] = useState(known || null)
  const lookup = () => {
    if (title || titleCache.has(key) || !window.api?.boards?.ticket) return
    titleCache.set(key, '')
    window.api.boards
      .ticket(dash.repo, dash.number)
      .then((t) => {
        const name = t?.title || ''
        titleCache.set(key, name)
        setTitle(name)
      })
      .catch(() => titleCache.delete(key))
  }
  return (
    <a
      href="#"
      onMouseEnter={lookup}
      onFocus={lookup}
      onClick={(e) => {
        e.preventDefault()
        onLink?.(dash)
      }}
      title={title ? `${key}: ${title}` : `Open ${key}`}
      className="rounded bg-blue-950 px-1 text-blue-300 no-underline hover:bg-blue-900"
    >
      {children}
      {title ? <span className="text-blue-200/80">{` ${title}`}</span> : null}
    </a>
  )
}

// One image or recording from the body, loaded once per URL for the whole session.
const mediaCache = new Map()
function resolveSrc(src, repo, headRef) {
  const url = safeUrl(src)
  if (!url) return null
  if (/^(https?:|data:)/i.test(url)) return url
  if (!repo || url.startsWith('#')) return null
  const full = repo.includes('/') ? repo : `G-Eskayo/${repo}`
  const clean = url.replace(/^\.?\/+/, '')
  if (clean.split('/').includes('..')) return null
  return `https://raw.githubusercontent.com/${full}/${headRef || 'HEAD'}/${clean}`
}

export function BodyMedia({ src, alt, repo, headRef, loadImage }) {
  const url = resolveSrc(src, repo, headRef)
  const [state, setState] = useState(() => (url && mediaCache.get(url)) || { status: 'loading' })
  useEffect(() => {
    if (!url) return
    const cached = mediaCache.get(url)
    if (cached) { setState(cached); return }
    let live = true
    const load = loadImage || ((u) => window.api?.mr?.image?.(u))
    Promise.resolve(/^data:/i.test(url) ? { ok: true, src: url } : load(url))
      .then((r) => (r?.ok ? { status: 'ok', kind: r.kind === 'video' ? 'video' : 'image', src: r.src || r.dataUrl } : { status: 'error', reason: r?.reason || 'could not load' }))
      .catch((e) => ({ status: 'error', reason: String(e?.message || e) }))
      .then((s) => {
        if (s.status === 'ok') mediaCache.set(url, s)
        if (live) setState(s)
      })
    return () => { live = false }
  }, [url])
  if (!url) return <span className="text-xs text-neutral-500">[image: {alt || 'unavailable'}]</span>
  if (state.status === 'loading') return <span aria-label="Loading image" className="my-3 block h-40 w-full max-w-xl animate-pulse rounded-lg bg-neutral-800" />
  if (state.status === 'error') return <span className="my-2 block text-xs text-amber-400">Couldn't load image{alt ? ` "${alt}"` : ''}: {state.reason}</span>
  if (state.kind === 'video') return <video src={state.src} aria-label={alt || 'Recording'} className="my-3 block max-h-[28rem] max-w-full rounded-lg" controls loop muted playsInline />
  return <img src={state.src} alt={alt || ''} loading="lazy" className="my-3 block max-h-[28rem] max-w-full rounded-lg bg-white/5" />
}

function sectionHeading(Tag, className) {
  return ({ children, node, ...props }) => {
    const text = (node?.children || []).map((c) => c.value || c.children?.map((cc) => cc.value || '').join('') || '').join('')
    const key = isKeySection(text)
    return (
      <Tag
        className={`${className} ${key ? 'border-l-2 border-sky-500/70 pl-3' : ''}`}
        data-key-section={key ? 'true' : undefined}
        {...props}
      >
        {children}
      </Tag>
    )
  }
}

export function issueComponents({ ctxRepo, headRef, titles, onLink, loadImage, compact = false }) {
  const body = compact ? 'text-sm leading-6' : 'text-[15px] leading-7'
  return {
    h1: sectionHeading('h1', 'mb-3 mt-8 text-xl font-semibold text-white first:mt-0'),
    h2: sectionHeading('h2', 'mb-3 mt-8 text-lg font-semibold text-white first:mt-0'),
    h3: sectionHeading('h3', 'mb-2 mt-6 text-base font-semibold text-neutral-100 first:mt-0'),
    h4: (props) => <h4 className="mb-2 mt-4 text-sm font-semibold text-neutral-100" {...props} />,
    p: (props) => <p className={`mb-4 ${body} text-neutral-200`} {...props} />,
    ul: (props) => <ul className={`mb-4 list-disc space-y-1.5 pl-6 ${body} text-neutral-200 [&_.task-list-item]:list-none`} {...props} />,
    ol: (props) => <ol className={`mb-4 list-decimal space-y-1.5 pl-6 ${body} text-neutral-200`} {...props} />,
    li: (props) => <li className="pl-1 marker:text-neutral-500" {...props} />,
    input: ({ checked, type }) =>
      type === 'checkbox' ? (
        <span aria-label={checked ? 'done' : 'not done'} className={`mr-2 inline-flex h-4 w-4 -translate-y-px items-center justify-center rounded border align-middle text-[10px] ${checked ? 'border-emerald-500 bg-emerald-600 text-white' : 'border-neutral-500'}`}>
          {checked ? '✓' : ''}
        </span>
      ) : null,
    blockquote: (props) => <blockquote className={`mb-4 border-l-2 border-neutral-600 pl-4 ${body} text-neutral-300`} {...props} />,
    code: (props) => <code className="rounded bg-neutral-800 px-1 py-0.5 font-mono text-[0.85em] text-neutral-100" {...props} />,
    pre: (props) => <pre className="mb-4 overflow-x-auto rounded-lg bg-neutral-950 p-3 font-mono text-[13px] leading-6 text-neutral-200 [&>code]:bg-transparent [&>code]:p-0" {...props} />,
    hr: (props) => <hr className="my-8 border-neutral-800" {...props} />,
    strong: (props) => <strong className="font-semibold text-white" {...props} />,
    table: (props) => (
      <div className="mb-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm" {...props} />
      </div>
    ),
    th: (props) => <th className="border-b border-neutral-700 px-3 py-2 text-left font-semibold text-neutral-100" {...props} />,
    td: (props) => <td className="border-b border-neutral-800 px-3 py-2 align-top text-neutral-300" {...props} />,
    img: ({ src, alt }) => <BodyMedia src={src} alt={alt} repo={ctxRepo} headRef={headRef} loadImage={loadImage} />,
    a: ({ href, children }) => {
      if (/^\[?▶ Recording/.test(String(children?.[0] ?? children)) && href) {
        return <BodyMedia src={href} alt="Recording" repo={ctxRepo} headRef={headRef} loadImage={loadImage} />
      }
      const dash = href && parseDashLink(href)
      if (dash?.type === 'ticket') return <TicketRef dash={dash} titles={titles} onLink={onLink}>{children}</TicketRef>
      if (dash?.type === 'doc') {
        return (
          <a href="#" onClick={(e) => { e.preventDefault(); onLink?.(dash) }} className="rounded bg-blue-950 px-1 text-blue-300 no-underline hover:bg-blue-900">
            {children}
          </a>
        )
      }
      if (!href) return <span>{children}</span>
      return (
        <a className="text-sky-400 underline decoration-sky-400/40 underline-offset-2 hover:decoration-sky-300" href={href} target="_blank" rel="noreferrer noopener">
          {children}
        </a>
      )
    }
  }
}

// Same-content renders are skipped: a board poll that returns the same body (and updatedAt) doesn't touch the DOM.
// A ctx rebuilt as a fresh object for the same project ({ repo: pr.repo } in a parent's render) counts as the same.
function sameCtx(a, b) {
  return a === b || (Boolean(a) && Boolean(b) && a.repo === b.repo && a.project === b.project && a.adrs === b.adrs)
}

export function sameIssueBody(a, b) {
  return a.body === b.body && a.updatedAt === b.updatedAt && a.stripDecisions === b.stripDecisions && a.compact === b.compact &&
    a.headRef === b.headRef && sameCtx(a.ctx, b.ctx) && a.titles === b.titles
}

function IssueBody({ body, ctx, headRef, titles, onLink, loadImage, stripDecisions = true, compact = false, empty = '(no description)' }) {
  const prepared = useMemo(() => prepareIssueBody(body, { stripDecisions }), [body, stripDecisions])
  const text = useMemo(() => (ctx ? linkify(prepared, ctx) : prepared), [prepared, ctx?.repo, ctx?.project, ctx?.adrs])
  const components = useMemo(
    () => issueComponents({ ctxRepo: ctx?.repo, headRef, titles, onLink, loadImage, compact }),
    [ctx?.repo, headRef, titles, onLink, loadImage, compact]
  )
  if (!text) return <p className="text-sm text-neutral-500">{empty}</p>
  return (
    <div className="issue-body max-w-[70ch] break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml urlTransform={(url) => safeUrl(url) ?? ''}>
        {text}
      </ReactMarkdown>
    </div>
  )
}

export default memo(IssueBody, sameIssueBody)
