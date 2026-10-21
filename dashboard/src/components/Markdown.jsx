import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { linkify } from '../lib/linkify.js'

export const markdownComponents = {
  h1: (props) => <h1 className="mb-3 mt-6 text-xl font-semibold text-white first:mt-0" {...props} />,
  h2: (props) => <h2 className="mb-2 mt-5 text-lg font-semibold text-white" {...props} />,
  h3: (props) => <h3 className="mb-2 mt-4 text-base font-semibold text-neutral-100" {...props} />,
  p: (props) => <p className="mb-3 leading-relaxed text-neutral-300" {...props} />,
  // react-markdown 10 no longer passes `inline`: a fenced block arrives wrapped in <pre>, so style code by that.
  code: (props) => <code className="rounded bg-neutral-800 px-1 py-0.5 font-mono text-sm text-neutral-200" {...props} />,
  pre: (props) => (
    <pre className="mb-3 overflow-auto rounded-lg bg-neutral-900 p-3 font-mono text-sm text-neutral-200 [&>code]:bg-transparent [&>code]:p-0" {...props} />
  ),
  h4: (props) => <h4 className="mb-1 mt-3 text-sm font-semibold text-neutral-100" {...props} />,
  strong: (props) => <strong className="font-semibold text-neutral-100" {...props} />,
  hr: (props) => <hr className="my-5 border-neutral-800" {...props} />,
  li: (props) => <li className="mb-1" {...props} />,
  table: (props) => (
    <div className="mb-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  th: (props) => <th className="border border-neutral-700 bg-neutral-900 px-2 py-1 text-left font-semibold text-neutral-100" {...props} />,
  td: (props) => <td className="border border-neutral-800 px-2 py-1 align-top text-neutral-300" {...props} />,
  // onOpen (optional): clicking opens the image in the shared full-size viewer (ImageViewer).
  img: ({ alt, onOpen, node: _node, ...props }) => (
    <img
      alt={alt}
      className={`my-3 max-w-full rounded-lg bg-white/5${onOpen ? ' cursor-zoom-in' : ''}`}
      onClick={onOpen ? () => onOpen(props.src) : undefined}
      {...props}
    />
  ),
  ul: (props) => <ul className="mb-3 list-disc pl-6 text-neutral-300" {...props} />,
  ol: (props) => <ol className="mb-3 list-decimal pl-6 text-neutral-300" {...props} />,
  blockquote: (props) => <blockquote className="mb-3 border-l-2 border-neutral-700 pl-3 text-neutral-400" {...props} />
}

// dash://ticket/<owner>/<repo>/<n>  |  dash://doc/<project>/<path>
export function parseDashLink(href) {
  const t = href.match(/^dash:\/\/ticket\/([^/]+\/[^/]+)\/(\d+)$/)
  if (t) return { type: 'ticket', repo: t[1], number: Number(t[2]) }
  const d = href.match(/^dash:\/\/doc\/([^/]+)\/(.+)$/)
  if (d) return { type: 'doc', project: d[1], path: d[2] }
  const f = href.match(/^file:\/\/(\/.+)$/)
  if (f) {
    try {
      return { type: 'file', path: decodeURIComponent(f[1]) }
    } catch {
      return null
    }
  }
  return null
}

// Renders markdown with ticket / ADR references turned into links that stay inside the dashboard.
// `ctx` says which project the text belongs to (see relations:context); `onLink` receives the click.
// A repo-relative image in a README (docs/images/x.png) points at the repo, not at the app: resolve it on GitHub.
export function resolveImage(src, repo) {
  if (!src || !repo || /^([a-z]+:|\/\/|data:)/i.test(src)) return src
  const full = repo.includes('/') ? repo : `G-Eskayo/${repo}`  // the Docs tab passes owner/repo (catalog), others a bare name
  return `https://raw.githubusercontent.com/${full}/HEAD/${src.replace(/^\.?\//, '')}`
}

// An image whose bytes come from the main process (an outbox markdown file's `shots/x.png`, G-Eskayo/marvin#402).
// `load(src)` resolves to { ok, dataUrl } | { ok: false, reason }; a failure shows a short note, never a broken icon.
function LoadedImage({ src, alt, load, onOpen }) {
  const [state, setState] = useState({ status: 'loading' })
  useEffect(() => {
    let live = true
    setState({ status: 'loading' })
    Promise.resolve()
      .then(() => load(src))
      .then((r) => live && setState(r?.ok ? { status: 'ok', src: r.dataUrl } : { status: 'error', reason: r?.reason || 'not found' }))
      .catch((err) => live && setState({ status: 'error', reason: String(err?.message || err) }))
    return () => { live = false }
  }, [src])
  if (state.status === 'error') return <span className="my-3 block text-xs text-red-400">Image {src} couldn't load: {state.reason}</span>
  if (state.status === 'loading') return <span className="my-3 block h-24 animate-pulse rounded-lg bg-neutral-800" aria-label="Loading image" />
  return markdownComponents.img({ alt, src: state.src, onOpen })
}

// Markdown images: `loadImage` (optional) fetches a relative image's bytes; `onOpenImage({ src, alt })` (optional)
// opens a clicked image in the shared full-size viewer.
function MarkdownImage({ src, alt, repo, loadImage, onOpenImage }) {
  const isRelative = src && !/^([a-z][a-z0-9+.-]*:|\/\/)/i.test(src)
  const onOpen = onOpenImage ? (resolved) => onOpenImage({ src: resolved, alt }) : undefined
  if (loadImage && isRelative) return <LoadedImage src={src} alt={alt} load={loadImage} onOpen={onOpen} />
  return markdownComponents.img({ alt, src: resolveImage(src, repo), onOpen })
}

export default function Markdown({ content, ctx, onLink, loadImage, onOpenImage }) {
  const text = ctx ? linkify(content, ctx) : content
  const components = {
    ...markdownComponents,
    img: ({ src, alt }) => <MarkdownImage src={src} alt={alt} repo={ctx?.repo} loadImage={loadImage} onOpenImage={onOpenImage} />,
    a: ({ href, children, ...rest }) => {
      const dash = href && parseDashLink(href)
      if (dash) {
        return (
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault()
              // A folder or file on this Mac opens straight from here, wherever the markdown is shown.
              if (dash.type === 'file') window.api?.docs?.openLink?.(dash.path)?.catch?.(() => {})
              else onLink?.(dash)
            }}
            className="rounded bg-blue-950 px-1 text-blue-300 no-underline hover:bg-blue-900"
            title={dash.type === 'ticket' ? `Open ticket #${dash.number}` : dash.type === 'file' ? `Open on this Mac: ${dash.path}` : `Open ${dash.path}`}
          >
            {children}
          </a>
        )
      }
      return (
        <a className="text-blue-400 hover:underline" href={href} target="_blank" rel="noreferrer" {...rest}>
          {children}
        </a>
      )
    }
  }
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} urlTransform={(url) => url}>
      {text}
    </ReactMarkdown>
  )
}
