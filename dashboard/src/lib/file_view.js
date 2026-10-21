// Pure helpers behind FileView (G-Eskayo/marvin#402): CSV/TSV parsing for the table view and the sandboxed document an
// HTML file is shown in.

export const TABLE_ROW_LIMIT = 1000

// RFC 4180-style: quoted cells may hold the delimiter, newlines and doubled quotes. Never throws; an unclosed quote runs
// to the end of the file. Rows are padded to the widest row so the table lines up.
export function parseDelimited(text, delimiter = ',') {
  if (typeof text !== 'string') return []
  const src = text.replace(/^﻿/, '')
  const rows = []
  let row = []
  let cell = ''
  let quoted = false
  let i = 0
  const endRow = () => { row.push(cell); rows.push(row); row = []; cell = '' }
  while (i < src.length) {
    const ch = src[i]
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') { cell += '"'; i += 2; continue }
        quoted = false
      } else cell += ch
      i++
      continue
    }
    if (ch === '"' && cell === '') quoted = true
    else if (ch === delimiter) { row.push(cell); cell = '' }
    else if (ch === '\r' && src[i + 1] === '\n') { endRow(); i++ }
    else if (ch === '\n' || ch === '\r') endRow()
    else cell += ch
    i++
  }
  if (cell !== '' || row.length || quoted) endRow()
  const kept = rows.filter((r) => !(r.length === 1 && r[0] === ''))
  const width = Math.max(0, ...kept.map((r) => r.length))
  return kept.map((r) => (r.length < width ? [...r, ...Array(width - r.length).fill('')] : r))
}

// The page is shown in <iframe sandbox="" srcdoc>: the empty sandbox already stops scripts, forms and popups. This CSP,
// placed before anything the page brings, stops every network load too (stylesheets, images, fonts, frames), allowing
// only inline styles and data: images/fonts. A meta refresh (which could navigate the frame to a remote page) and any
// CSP the page declares itself are removed.
const SANDBOX_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"

export function sandboxedHtml(html) {
  const body = (typeof html === 'string' ? html : '')
    .replace(/<meta\b[^>]*http-equiv\s*=\s*["']?\s*(refresh|content-security-policy)\b[^>]*>/gi, '')
  return `<meta http-equiv="Content-Security-Policy" content="${SANDBOX_CSP}">${body}`
}
