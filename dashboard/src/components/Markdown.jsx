import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { linkify } from '../lib/linkify.js'

export const markdownComponents = {
  h1: (props) => <h1 className="mb-3 mt-6 text-xl font-semibold text-white first:mt-0" {...props} />,
  h2: (props) => <h2 className="mb-2 mt-5 text-lg font-semibold text-white" {...props} />,
  h3: (props) => <h3 className="mb-2 mt-4 text-base font-semibold text-neutral-100" {...props} />,
  p: (props) => <p className="mb-3 leading-relaxed text-neutral-300" {...props} />,
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

// dash://ticket/<owner>/<repo>/<n>  |  dash://doc/<project>/<path>
export function parseDashLink(href) {
  const t = href.match(/^dash:\/\/ticket\/([^/]+\/[^/]+)\/(\d+)$/)
  if (t) return { type: 'ticket', repo: t[1], number: Number(t[2]) }
  const d = href.match(/^dash:\/\/doc\/([^/]+)\/(.+)$/)
  if (d) return { type: 'doc', project: d[1], path: d[2] }
  return null
}

// Renders markdown with ticket / ADR references turned into links that stay inside the dashboard.
// `ctx` says which project the text belongs to (see relations:context); `onLink` receives the click.
export default function Markdown({ content, ctx, onLink }) {
  const text = ctx ? linkify(content, ctx) : content
  const components = {
    ...markdownComponents,
    a: ({ href, children, ...rest }) => {
      const dash = href && parseDashLink(href)
      if (dash) {
        return (
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault()
              onLink?.(dash)
            }}
            className="rounded bg-blue-950 px-1 text-blue-300 no-underline hover:bg-blue-900"
            title={dash.type === 'ticket' ? `Open ticket #${dash.number}` : `Open ${dash.path}`}
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
