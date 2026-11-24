// Speakable text for the voice endpoint (ADR 0075): what a model writes for a screen, made fit to be read aloud.
// No Markdown, no code, no URLs read out, one line of plain sentences.

const ABBREVIATIONS = ['e.g.', 'i.e.', 'etc.', 'vs.', 'dr.', 'mr.', 'mrs.', 'ms.', 'st.', 'no.', 'approx.']

function siteName(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return 'a link'
  }
}

export function toSpeakable(text) {
  if (typeof text !== 'string') return ''
  let t = text.replace(/\r\n?/g, '\n')

  t = t.replace(/```[\s\S]*?(```|$)/g, '\n') // fenced code: never read code aloud
  t = t.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1') // images
  t = t.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1') // links: the text, not the URL
  t = t.replace(/<(https?:\/\/[^>\s]+)>/g, (_, u) => siteName(u))
  t = t.replace(/\bhttps?:\/\/[^\s)>\]]+/g, (u) => siteName(u.replace(/[.,;:!?]+$/, '')))
  t = t.replace(/<\/?[a-zA-Z][^>]*>/g, '') // HTML tags
  t = t.replace(/^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/gm, '') // table separator rows
  t = t.replace(/^\s*\|(.*)\|\s*$/gm, (_, row) => row.split('|').map((c) => c.trim()).filter(Boolean).join(', '))
  t = t.replace(/^\s{0,3}#{1,6}\s+/gm, '') // headings
  t = t.replace(/^\s*>+\s?/gm, '') // blockquotes
  t = t.replace(/^\s*([-*+]|\d+[.)])\s+/gm, '') // list markers
  t = t.replace(/^\s*([-*_]\s*){3,}$/gm, '') // horizontal rules
  t = t.replace(/`([^`]*)`/g, '$1') // inline code
  t = t.replace(/(\*\*|__)(.+?)\1/g, '$2')
  t = t.replace(/(^|[^\w*])[*_]([^*_\n]+)[*_](?=[^\w*]|$)/g, '$1$2')
  t = t.replace(/[*`|<>]/g, '')
  t = t.replace(/~~(.+?)~~/g, '$1')

  // Each remaining line is a sentence or part of one; a line with no closing punctuation gets a full stop.
  const lines = t.split('\n').map((l) => l.replace(/\s+/g, ' ').trim()).filter((l) => /[\p{L}\p{N}]/u.test(l))
  return lines.map((l, i) => (i < lines.length - 1 && !/[.!?:;,]$/.test(l) ? `${l}.` : l)).join(' ').trim()
}

// Split finished sentences off the front of a buffer. Returns [sentences, rest].
function takeSentences(buffer) {
  const out = []
  let start = 0
  for (let i = 0; i < buffer.length; i++) {
    const ch = buffer[i]
    if (ch !== '.' && ch !== '!' && ch !== '?') continue
    const next = buffer[i + 1]
    if (next === undefined) break // can't tell yet: a decimal or "e.g." may follow
    if (!/\s/.test(next)) continue // 0.83, e.g.x, a URL
    if (ch === '.') {
      const head = buffer.slice(start, i + 1).toLowerCase()
      const lastWord = head.split(/\s+/).pop()
      if (ABBREVIATIONS.includes(lastWord)) continue
    }
    out.push(buffer.slice(start, i + 1))
    start = i + 1
  }
  return [out, buffer.slice(start)]
}

function clean(sentences) {
  return sentences.map((s) => toSpeakable(s)).filter((s) => /[\p{L}\p{N}]/u.test(s))
}

// Streaming splitter: push model tokens in, get finished speakable sentences out as soon as each one ends.
export function createSentenceStream() {
  let buffer = ''
  return {
    push(token) {
      if (typeof token !== 'string' || !token) return []
      buffer += token
      const [done, rest] = takeSentences(buffer)
      buffer = rest
      return clean(done)
    },
    flush() {
      const [done, rest] = takeSentences(buffer + ' ')
      buffer = ''
      return clean([...done, rest])
    }
  }
}

export function splitSentences(text) {
  const s = createSentenceStream()
  return [...s.push(text), ...s.flush()]
}

const REST_ON_PHONE = "I've put the rest in the Thread on your phone."

// Cap a reply to what is comfortable to hear: a few sentences, a few hundred characters.
export function capSpoken(text, { maxSentences = 3, maxChars = 400 } = {}) {
  const speakable = toSpeakable(text)
  if (!speakable) return { speech: '', truncated: false }
  const sentences = splitSentences(speakable)
  const kept = []
  let length = 0
  for (const s of sentences) {
    if (kept.length >= maxSentences || length + s.length > maxChars) break
    kept.push(s)
    length += s.length + 1
  }
  if (kept.length === sentences.length) return { speech: kept.join(' '), truncated: false }
  if (kept.length === 0) {
    // One huge sentence: cut at a word boundary.
    const cut = sentences[0].slice(0, maxChars)
    const atWord = cut.slice(0, Math.max(cut.lastIndexOf(' '), 1)).trim()
    kept.push(`${atWord}…`)
  }
  return { speech: `${kept.join(' ')} ${REST_ON_PHONE}`, truncated: true }
}
