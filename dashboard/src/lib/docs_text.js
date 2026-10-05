// Pure markdown helpers shared by the Docs tab's renderer (outline) and
// main process (search). ATX headings only, fenced code skipped -- which is
// what the viewer's ReactMarkdown renders as headings, so outline index N is
// the Nth heading element on screen.
const HEADING = /^(#{1,6})\s+(.+?)\s*#*\s*$/

function plain(text) {
  return text
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[`*_]/g, '')
    .trim()
}

function* headingLines(markdown) {
  let fence = null
  const lines = markdown.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^\s*(```+|~~~+)/)
    if (m) {
      if (!fence) fence = m[1][0]
      else if (m[1][0] === fence) fence = null
      continue
    }
    if (fence) continue
    const h = lines[i].match(HEADING)
    if (h) yield { line: i, level: h[1].length, text: plain(h[2]) }
  }
}

export function extractOutline(markdown) {
  return [...headingLines(markdown || '')].map((h, index) => ({ ...h, index }))
}

// Sections keyed by heading index (-1 = text before the first heading).
export function splitSections(markdown) {
  const lines = (markdown || '').split('\n')
  const heads = extractOutline(markdown)
  const sections = []
  let start = 0
  let current = { headingIndex: -1, heading: '' }
  for (const h of heads) {
    sections.push({ ...current, text: lines.slice(start, h.line).join('\n') })
    current = { headingIndex: h.index, heading: h.text }
    start = h.line + 1
  }
  sections.push({ ...current, text: lines.slice(start).join('\n') })
  return sections.filter((s) => s.headingIndex !== -1 || s.text.trim())
}
