// Structured decisions in a PR or ticket description (owner, 2026-10-09): "if I need to choose things for a ticket I need
// options to do so or respond, and that must be met for me to approve; otherwise it is too vague and needs more follow
// up". clarity-captions #99 asked him to pick a dance and a hand-off in prose, and the dashboard only offered Approve or
// Deny. Format (docs/agents/decisions-format.md):
//
//   ## Decisions
//   <!-- marvin:decisions -->
//   ### dance: Which launch animation?
//   - [ ] A: Clap & wiggle
//   - [ ] B: Balance a bubble
//   ### mix: Mix parts of several? (pick any) (optional)
//   - [ ] ...
//   ### character: Any changes to the character? (text) (optional)
//
// One choice and required by default; "(pick any)" = several; "(text)" = a written answer; "(optional)" = not required.
// Answers live in the description itself (ticked boxes, plus "> **Answer:**" / "> **Note:**" lines under a question), so
// the card, the merge gate and GitHub all read one source. Pure (no imports), so the page, the app and the merge server
// share it; the merge-server check is in decisions_gate.js.

export const DECISIONS_MARKER = '<!-- marvin:decisions -->'
const QUESTION_RE = /^###\s+([^\s:]+)\s*:\s*(.+?)\s*$/
const OPTION_RE = /^\s*[-*]\s+\[( |x|X)\]\s+(.+?)\s*$/
const ANSWER_RE = /^>\s*\*\*Answer:\*\*\s?(.*)$/
const NOTE_RE = /^>\s*\*\*Note:\*\*\s?(.*)$/
const ID_RE = /^[a-z0-9][a-z0-9_-]*$/
const FLAG_RE = /\s*\((pick any|text|optional)\)\s*$/i

// Lines with fenced code blanked out, so an example of the format inside ``` is never read as a real section.
function unfencedLines(body) {
  let fence = null
  return String(body || '').split('\n').map((line) => {
    const m = line.match(/^\s*(`{3,}|~{3,})/)
    if (m) {
      if (!fence) { fence = m[1][0]; return null }
      if (m[1][0] === fence) { fence = null; return null }
    }
    return fence ? null : line
  })
}

function splitFlags(text) {
  const flags = { multi: false, text: false, optional: false }
  let rest = text
  for (let m = rest.match(FLAG_RE); m; m = rest.match(FLAG_RE)) {
    const f = m[1].toLowerCase()
    if (f === 'pick any') flags.multi = true
    if (f === 'text') flags.text = true
    if (f === 'optional') flags.optional = true
    rest = rest.slice(0, m.index)
  }
  return { question: rest.trim(), ...flags }
}

// Where the decisions section is: [start, end) line indexes of everything after the marker up to the next "## " heading.
function sectionRange(lines) {
  const start = lines.findIndex((l) => l !== null && l.trim() === DECISIONS_MARKER)
  if (start < 0) return null
  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i] !== null && /^#{1,2}\s/.test(lines[i])) { end = i; break }
  }
  return [start + 1, end]
}

export function parseDecisions(body) {
  const lines = unfencedLines(body)
  const range = sectionRange(lines)
  if (!range) return { present: false, questions: [], problems: [] }
  const questions = []
  const problems = []
  let q = null
  for (let i = range[0]; i < range[1]; i++) {
    const line = lines[i]
    if (line === null) continue
    if (/^###\s/.test(line)) {
      const m = line.match(QUESTION_RE)
      if (!m || !ID_RE.test(m[1])) {
        problems.push(`"${line.trim().slice(0, 80)}" needs an id: write it as "### some-id: question"`)
        q = null
        continue
      }
      const id = m[1]
      const f = splitFlags(m[2])
      if (questions.some((x) => x.id === id)) problems.push(`question id "${id}" is used twice`)
      q = {
        id, question: f.question, kind: f.text ? 'text' : f.multi ? 'multi' : 'single',
        required: !f.optional, options: [], answer: null, note: null, line: i
      }
      questions.push(q)
      continue
    }
    if (!q) continue
    const o = line.match(OPTION_RE)
    if (o) { q.options.push({ label: o[2], checked: o[1] !== ' ' }); continue }
    const a = line.match(ANSWER_RE)
    if (a) { q.answer = a[1].trim() || null; continue }
    const n = line.match(NOTE_RE)
    if (n) { q.note = n[1].trim() || null; continue }
  }
  for (const x of questions) {
    if (x.kind !== 'text' && x.options.length < 2) problems.push(`"${x.id}" offers ${x.options.length} option(s): a choice needs at least two`)
    if (x.kind === 'single' && x.options.filter((o) => o.checked).length > 1) problems.push(`"${x.id}" takes one answer but has several ticked`)
  }
  if (!questions.length) problems.push('the decisions section has no questions')
  return { present: true, questions: questions.map(({ line, ...rest }) => rest), problems }
}

export function isAnswered(q) {
  if (q.kind === 'text') return !!(q.answer && q.answer.trim())
  const n = q.options.filter((o) => o.checked).length
  return q.kind === 'single' ? n === 1 : n >= 1
}

// Required questions still open, by id.
export function pendingDecisions(parsed) {
  if (!parsed?.present) return []
  return parsed.questions.filter((q) => q.required && !isAnswered(q)).map((q) => q.id)
}

// What the card needs: null when the description has no decisions section.
export function summarizeDecisions(body) {
  const parsed = parseDecisions(body)
  if (!parsed.present) return null
  return { ...parsed, pending: pendingDecisions(parsed) }
}

// Does a description ask the owner to choose, in prose, without a decisions section? Deliberately narrow so ordinary
// checklists ("## Acceptance criteria", "## Tests") never trip it: a heading that asks, a ticked-list item that is a
// question, or an explicit "A, B or C" / "which option" ask.
export function vagueness(body) {
  if (parseDecisions(body).present) return null
  const lines = unfencedLines(body).filter((l) => l !== null)
  const text = lines.join('\n')
  const reasons = []
  // The ask word is the whole heading, or is followed only by "for/to ..." or punctuation: "## Choose", "## Open
  // questions", "## Questions for you". A report ("## Choices made", "## Decisions recorded") is not an ask.
  const heading = lines.find((l) => /^#{1,6}\s*(choose|choices|decide|decisions?|pick|questions?|open questions?)(\s+(for|to)\b[^\n]*)?\s*[:?]?\s*$/i.test(l.trim()))
  if (heading) reasons.push(`"${heading.trim()}" asks for a choice`)
  const askItem = lines.find((l) => /^\s*[-*]\s+\[[ xX]\]\s+.*\?\s*\**\s*$/.test(l))
  if (askItem) reasons.push(`"${askItem.trim().slice(0, 80)}" is a question in a checklist`)
  const phrase = text.match(/\b([A-Z]\s*,\s*[A-Z],?\s+or\s+[A-Z]|which (option|one)|pick one|choose (one|between))\b/i)
  if (phrase) reasons.push(`"${phrase[0]}" asks for a choice`)
  return reasons.length ? { reasons } : null
}

// Writes answers into the description: ticks exactly the chosen boxes and puts "> **Answer:**" / "> **Note:**" under
// each question, replacing earlier ones. answers: { id: { choices: [labels], text, note } }. Questions not in answers
// are left as they are. Pure and idempotent.
export function applyAnswers(body, answers) {
  const src = String(body || '')
  const raw = src.split('\n')
  const lines = unfencedLines(src)
  const range = sectionRange(lines)
  if (!range) throw new Error('this description has no decisions section')
  const out = raw.slice(0, range[0])
  let current = null
  let pendingInsert = null // answer/note lines to write after the current question's options
  const flush = () => { if (pendingInsert) { out.push(...pendingInsert); pendingInsert = null } }
  for (let i = range[0]; i < range[1]; i++) {
    const line = lines[i]
    if (line === null) { out.push(raw[i]); continue }
    if (/^###\s/.test(line)) {
      flush()
      const m = line.match(QUESTION_RE)
      current = m && answers[m[1]] ? { id: m[1], a: answers[m[1]], text: splitFlags(m[2]).text } : null
      out.push(raw[i])
      if (current) {
        const extra = []
        if (current.text && current.a.text != null && String(current.a.text).trim()) extra.push(`> **Answer:** ${oneLine(current.a.text)}`)
        if (!current.text && current.a.note != null && String(current.a.note).trim()) extra.push(`> **Note:** ${oneLine(current.a.note)}`)
        if (current.text && current.a.note != null && String(current.a.note).trim()) extra.push(`> **Note:** ${oneLine(current.a.note)}`)
        pendingInsert = extra
        if (current.text) flush()
      }
      continue
    }
    if (current) {
      const o = line.match(OPTION_RE)
      if (o && !current.text) {
        const chosen = (current.a.choices || []).includes(o[2])
        current.sawOption = true
        out.push(raw[i].replace(/\[( |x|X)\]/, chosen ? '[x]' : '[ ]'))
        continue
      }
      if (ANSWER_RE.test(line) || NOTE_RE.test(line)) continue // replaced by the new ones
      if (line.trim() === '' && pendingInsert && current.sawOption) { flush(); out.push(raw[i]); continue }
    }
    out.push(raw[i])
  }
  flush()
  out.push(...raw.slice(range[1]))
  return out.join('\n')
}

const oneLine = (s) => String(s).replace(/\s*\n+\s*/g, ' ').trim()

// The record left on GitHub after submitting: readable, plus a machine-readable block.
export function decisionsComment(parsed, answers) {
  const rows = []
  for (const q of parsed.questions) {
    const a = answers[q.id]
    if (!a) continue
    const value = q.kind === 'text' ? (a.text || '').trim() : (a.choices || []).join(', ')
    rows.push(`- **${q.question}** ${value || '_(no answer)_'}${a.note && String(a.note).trim() ? `. _Note:_ ${oneLine(a.note)}` : ''}`)
  }
  const json = JSON.stringify({ answers }, null, 2)
  return `### Decisions from the owner\n\n${rows.join('\n')}\n\n<details><summary>machine-readable</summary>\n\n\`\`\`marvin-decisions\n${json}\n\`\`\`\n</details>`
}
