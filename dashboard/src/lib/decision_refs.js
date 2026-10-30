// Which of the PR's images a Decision is about (G-Eskayo/marvin#938), so the question can link to it: the question
// names "scene X" (and pr-shots' captions start "X. ..."), or it quotes an image's caption. Minimal on purpose:
// only the question's own text, only exact letters and whole captions, no fuzzy matching.

const SCENE_WORDS = /\bscenes?\s+([a-z](?:\s*(?:,|\band\b|\bor\b|&)\s*[a-z]\b)*)/gi
const MIN_CAPTION = 12

function sceneLetters(text) {
  const out = []
  for (const m of String(text || '').matchAll(SCENE_WORDS)) {
    for (const l of m[1].toLowerCase().split(/\s*(?:,|\band\b|\bor\b|&)\s*/)) if (/^[a-z]$/.test(l) && !out.includes(l)) out.push(l)
  }
  return out
}

// The scene letter an image's caption (or alt) starts with: "b. One answer changed", "Scene b: ...", "(b) ...".
export function sceneOf(img) {
  for (const t of [img?.caption, img?.alt]) {
    const m = String(t || '').trim().match(/^(?:scene\s+)?\(?([a-z])(?:[.):]|\s+[-–—])\s/i)
    if (m) return m[1].toLowerCase()
  }
  return null
}

// [{ label, index }] for one question: scenes in the order named, then any image whose whole caption it quotes.
export function imageRefsFor(question, images) {
  const list = Array.isArray(images) ? images : []
  const text = String(question || '')
  const refs = []
  const add = (label, index) => { if (index >= 0 && !refs.some((r) => r.index === index)) refs.push({ label, index }) }
  for (const letter of sceneLetters(text)) add(`scene ${letter}`, list.findIndex((img) => sceneOf(img) === letter))
  const lower = text.toLowerCase()
  list.forEach((img, index) => {
    const c = String(img?.caption || '').trim().toLowerCase()
    if (c.length >= MIN_CAPTION && lower.includes(c)) add(sceneOf(img) ? `scene ${sceneOf(img)}` : 'the screenshot', index)
  })
  return refs
}
