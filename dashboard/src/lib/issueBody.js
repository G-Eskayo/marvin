// Ticket and PR descriptions, prepared for reading (owner, 2026-10-09): "format descriptions in tickets instead of just
// having them as scrollable text boxes", hardcoded (no AI), cheap, and high quality to read. Pure and deterministic:
// the same body always gives the same markdown, and each body is prepared once (memo below), so poll ticks cost nothing.
//
// What it does to a GitHub body before react-markdown sees it:
// - HTML comments disappear (<!-- marvin:decisions --> and friends were showing as literal text).
// - The Decisions section is cut out when the page renders it with the Decisions component, so it isn't shown twice.
// - The little HTML GitHub bodies use becomes markdown: <img> → image, <video>/<source> → a recording link, <br> → line
//   break, <details>/<summary> → plain text (summary in bold). Every other tag is dropped and its text kept, so no raw
//   HTML ever reaches the page (react-markdown would otherwise print it as escaped text).
// Code (fenced or `inline`) is never touched.

import { DECISIONS_MARKER } from '../../webhook-server/decisions.js'

const FENCE_RE = /^\s*(`{3,}|~{3,})/

// [isCode, text] chunks: fenced blocks and inline code are protected; everything else may be rewritten.
function splitProtected(body) {
  const out = []
  let buf = []
  let fence = null
  for (const line of String(body).split('\n')) {
    const m = line.match(FENCE_RE)
    if (fence) {
      buf.push(line)
      if (m && m[1][0] === fence) {
        out.push([true, buf.join('\n')])
        buf = []
        fence = null
      }
      continue
    }
    if (m) {
      if (buf.length) out.push([false, buf.join('\n')])
      buf = [line]
      fence = m[1][0]
      continue
    }
    buf.push(line)
  }
  if (buf.length) out.push([Boolean(fence), buf.join('\n')])
  return out
}

function attr(tag, name) {
  const m = tag.match(new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'))
  return m ? (m[1] ?? m[2] ?? m[3] ?? '').trim() : ''
}

function rewriteHtml(text) {
  return text
    .split(/(`[^`\n]*`)/)
    .map((part, i) => {
      if (i % 2 === 1) return part // inline code
      return part
        .replace(/<!--[\s\S]*?-->/g, '')
        .replace(/<img\b[^>]*>/gi, (tag) => {
          const src = attr(tag, 'src')
          return src ? `![${attr(tag, 'alt').replace(/[[\]]/g, '')}](${src})` : ''
        })
        .replace(/<video\b[^>]*>([\s\S]*?)<\/video>/gi, (whole, inner) => {
          const src = attr(whole, 'src') || attr(inner.match(/<source\b[^>]*>/i)?.[0] || '', 'src')
          return src ? `[▶ Recording](${src})` : ''
        })
        .replace(/<(?:video|source)\b[^>]*>/gi, (tag) => {
          const src = attr(tag, 'src')
          return src ? `[▶ Recording](${src})` : ''
        })
        .replace(/<br\s*\/?>/gi, '  \n')
        .replace(/<summary\b[^>]*>([\s\S]*?)<\/summary>/gi, (_m, t) => `**${t.trim()}**\n\n`)
        .replace(/<\/?[a-z][a-z0-9-]*\b[^>]*>/gi, '')
    })
    .join('')
}

// Removes the Decisions section (the marker, its questions, and a "## Decisions" heading directly above it) up to the
// next level-1/2 heading, the same range decisions.js reads.
function stripDecisionsSection(text) {
  const lines = text.split('\n')
  const at = lines.findIndex((l) => l.trim() === DECISIONS_MARKER)
  if (at < 0) return text
  let start = at
  let k = at - 1
  while (k >= 0 && lines[k].trim() === '') k--
  if (k >= 0 && /^#{1,3}\s+decisions\b/i.test(lines[k].trim())) start = k
  let end = lines.length
  for (let i = at + 1; i < lines.length; i++) {
    if (/^#{1,2}\s/.test(lines[i])) { end = i; break }
  }
  return [...lines.slice(0, start), ...lines.slice(end)].join('\n')
}

const MAX_BODY = 200_000
const MEMO_MAX = 200
const memo = new Map()
export const prepareStats = { transforms: 0 }

export function prepareIssueBody(body, { stripDecisions = true } = {}) {
  const raw = String(body ?? '')
  const key = `${stripDecisions ? 1 : 0}\u0000${raw}`
  const hit = memo.get(key)
  if (hit !== undefined) return hit
  prepareStats.transforms++
  let text = raw.length > MAX_BODY ? `${raw.slice(0, MAX_BODY)}\n\n_…description cut off here (it is very long); open it on GitHub for the rest._` : raw
  if (stripDecisions) text = stripDecisionsSection(text)
  const out = splitProtected(text)
    .map(([code, chunk]) => (code ? chunk : rewriteHtml(chunk)))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
  if (memo.size >= MEMO_MAX) memo.delete(memo.keys().next().value)
  memo.set(key, out)
  return out
}

// Links from a ticket body are untrusted (anyone can write a GitHub issue). Only web, mail, in-dashboard and same-page
// links survive; javascript:, file:, vbscript: and the rest are dropped to plain text.
export function safeUrl(url) {
  const u = String(url || '').trim()
  if (!u) return null
  if (/^(https?:|mailto:|dash:\/\/(ticket|doc)\/)/i.test(u)) return u
  if (/^data:image\/(png|jpe?g|gif|webp);/i.test(u)) return u
  if (u.startsWith('#')) return u
  if (/^[a-z][a-z0-9+.-]*:/i.test(u) || u.startsWith('//')) return null
  return u // repo-relative; images resolve it against the repo
}

// Section headings in the ticket template get a quiet accent so the eye finds them (ADHD + dyslexia friendly).
const KEY_SECTIONS = ['what to build', 'acceptance criteria', "how we'll try to break it", 'how we will try to break it', 'blocked by', 'your task', 'what happened', 'cause', 'why', 'decisions', 'what changed', 'not verified', 'not done']
export function isKeySection(text) {
  const t = String(text || '').toLowerCase().replace(/[^a-z' ]/g, ' ').replace(/\s+/g, ' ').trim()
  return KEY_SECTIONS.some((k) => t === k || t.startsWith(`${k} `))
}
