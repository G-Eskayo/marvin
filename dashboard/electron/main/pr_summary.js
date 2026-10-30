// What a PR is, in its own words, for the top of the MR detail (G-Eskayo/marvin#938): the owner reads what to look at
// before the Decisions. The description's opening paragraph (before its first heading), then its first "What it is"
// section if it has one. Pure; Markdown in, Markdown out (the detail renders it with the description renderer).

const MAX_CHARS = 1600
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/
const LINK_ONLY = /^\s*(?:closes|fixes|resolves|refs?|part of|for)\s+(?:[\w.-]+\/[\w.-]+)?#\d+[.,]?\s*$/i
const MEDIA_ONLY = /^\s*(?:!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>|<video\b[\s\S]*)\s*$/i

const stripComments = (s) => s.replace(/<!--[\s\S]*?-->/g, '')

// Splits the body into lines with fenced code kept intact (a "#" inside a fence isn't a heading).
function lines(body) {
  const out = []
  let fence = null
  for (const raw of stripComments(String(body || '')).split('\n')) {
    const line = raw.replace(/\r$/, '')
    const f = line.match(/^\s*(```|~~~)/)
    if (f) fence = fence ? (fence === f[1] ? null : fence) : f[1]
    out.push({ line, inFence: !!fence || !!f })
  }
  return out
}

function openingParagraph(ls) {
  const para = []
  for (const { line, inFence } of ls) {
    if (!inFence && HEADING.test(line)) break
    if (!line.trim()) {
      if (para.length) break
      continue
    }
    if (!para.length && (LINK_ONLY.test(line) || MEDIA_ONLY.test(line))) continue
    para.push(line)
  }
  return para.join('\n').trim()
}

function whatItIs(ls) {
  let level = 0
  const out = []
  for (const { line, inFence } of ls) {
    const h = !inFence && line.match(HEADING)
    if (level) {
      if (h && h[1].length <= level) break
      out.push(line)
    } else if (h && /^what it is\b/i.test(h[2].replace(/[*_`]/g, ''))) {
      level = h[1].length
    }
  }
  return out.join('\n').trim()
}

// Cut at a paragraph or line break, never mid-word, and say it was cut.
function cap(text) {
  if (text.length <= MAX_CHARS) return text
  const cut = text.slice(0, MAX_CHARS)
  const at = Math.max(cut.lastIndexOf('\n\n'), cut.lastIndexOf('\n'))
  return `${(at > MAX_CHARS / 2 ? cut.slice(0, at) : cut.replace(/\s+\S*$/, '')).trimEnd()} …`
}

export function prSummary(body) {
  if (typeof body !== 'string' || !body.trim()) return ''
  const ls = lines(body.slice(0, 200_000))
  const parts = [openingParagraph(ls), whatItIs(ls)].filter(Boolean)
  return parts.length ? cap(parts.join('\n\n')) : ''
}
