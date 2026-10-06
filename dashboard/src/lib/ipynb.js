// Jupyter notebook (.ipynb, nbformat 4) -> Markdown the Docs viewer already knows how to render.
// Markdown cells pass through; code cells and text outputs become fenced blocks; image outputs become inline data-URI
// images (so a notebook reads top to bottom like it does on GitHub). HTML outputs are not rendered: a table falls back to
// its text/plain form, which is what pandas prints anyway.

const MAX_OUTPUT_LINES = 80
const ANSI = /\u001b\[[0-9;]*[A-Za-z]/g

export const isNotebookPath = (p) => typeof p === 'string' && /\.ipynb$/i.test(p)

const text = (v) => (Array.isArray(v) ? v.join('') : typeof v === 'string' ? v : '')

function fence(body, lang = '') {
  const longest = Math.max(2, ...(body.match(/`+/g) || []).map((s) => s.length))
  const ticks = '`'.repeat(longest + 1)
  return `${ticks}${lang}\n${body.replace(/\n$/, '')}\n${ticks}`
}

function clip(body) {
  const lines = body.replace(/\n$/, '').split('\n')
  if (lines.length <= MAX_OUTPUT_LINES) return body
  return `${lines.slice(0, MAX_OUTPUT_LINES).join('\n')}\n... ${lines.length - MAX_OUTPUT_LINES} more lines`
}

function renderOutput(o, images) {
  if (o.output_type === 'stream') {
    const body = text(o.text)
    return body.trim() ? fence(clip(body), 'text') : ''
  }
  if (o.output_type === 'error') {
    const tb = (o.traceback || []).map((l) => l.replace(ANSI, '')).join('\n')
    const body = tb || `${o.ename}: ${o.evalue}`
    return fence(clip(body.split('\n').slice(-15).join('\n')), 'text')
  }
  const data = o.data || {}
  for (const type of images ? ['image/png', 'image/jpeg'] : []) {
    if (data[type]) return `![output](data:${type};base64,${text(data[type]).replace(/\s/g, '')})`
  }
  if (images && data['image/svg+xml']) return `![output](data:image/svg+xml;utf8,${encodeURIComponent(text(data['image/svg+xml']))})`
  if (data['text/markdown']) return text(data['text/markdown'])
  if (data['text/plain']) {
    const body = text(data['text/plain'])
    return body.trim() ? fence(clip(body), 'text') : ''
  }
  return '' // widgets, latex, html-only: nothing readable to show
}

export function notebookToMarkdown(raw, { images = true } = {}) {
  let nb
  try {
    nb = JSON.parse(raw)
  } catch {
    nb = null
  }
  if (!nb || !Array.isArray(nb.cells)) return '> This notebook could not be read (it is not valid notebook JSON).'
  const lang = nb.metadata?.language_info?.name || nb.metadata?.kernelspec?.language || 'python'
  const parts = []
  for (const cell of nb.cells) {
    const src = text(cell.source)
    if (cell.cell_type === 'markdown') {
      if (src.trim()) parts.push(src.replace(/\s+$/, ''))
    } else if (cell.cell_type === 'code') {
      if (src.trim()) parts.push(fence(src, lang))
      for (const o of cell.outputs || []) {
        const rendered = renderOutput(o, images)
        if (rendered) parts.push(rendered)
      }
    }
  }
  return parts.join('\n\n') + '\n'
}
