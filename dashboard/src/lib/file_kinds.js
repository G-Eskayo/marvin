// A file's kind from its name alone (G-Eskayo/marvin#402): the Files tab lists each file's kind in plain words and the
// main process picks how to read it. Shared by main (outbox.js) and the renderer so the two never disagree.

const KINDS = {
  image: { label: 'Image', ext: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'] },
  pdf: { label: 'PDF', ext: ['pdf'] },
  markdown: { label: 'Markdown', ext: ['md', 'markdown'] },
  notebook: { label: 'Notebook', ext: ['ipynb'] },
  json: { label: 'JSON', ext: ['json'] },
  table: { label: 'Table', ext: ['csv', 'tsv'] },
  html: { label: 'Web page', ext: ['html', 'htm'] },
  code: {
    label: 'Code',
    ext: ['js', 'jsx', 'mjs', 'cjs', 'ts', 'tsx', 'py', 'sh', 'bash', 'zsh', 'swift', 'yml', 'yaml', 'toml', 'css', 'xml',
      'sql', 'go', 'rs', 'rb', 'java', 'kt', 'c', 'h', 'cpp', 'm', 'ini', 'plist', 'jsonl', 'ndjson', 'diff', 'patch']
  },
  text: { label: 'Text', ext: ['txt', 'log', 'text', 'rst'] }
}

const BY_EXT = Object.fromEntries(Object.entries(KINDS).flatMap(([kind, { ext }]) => ext.map((e) => [e, kind])))

export const extOf = (name) => {
  if (typeof name !== 'string') return ''
  const base = name.split('/').pop()
  const dot = base.lastIndexOf('.')
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : ''
}

export function fileKind(name) {
  const kind = BY_EXT[extOf(name)]
  return kind ? { kind, label: KINDS[kind].label } : { kind: 'other', label: 'File' }
}

export function formatSize(n) {
  if (typeof n !== 'number' || !Number.isFinite(n) || n < 0) return ''
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let u = 0
  while (v >= 1024 && u < units.length - 1) { v /= 1024; u++ }
  return `${v >= 10 || Number.isInteger(v) ? Math.round(v) : v.toFixed(1)} ${units[u]}`
}
