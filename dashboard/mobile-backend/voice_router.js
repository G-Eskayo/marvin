// Which brain takes a spoken turn (ADR 0075 point 5), and whether it is a side effect that must be confirmed on the
// phone (ADR 0005, ADR 0043).
//
// Safety does not rest on this classifier. A side effect it misses goes to the deep brain, which runs read-only from
// voice and cannot act; a question it mistakes for an action costs one phone tap. Both mistakes are safe.

const FILLER = /^(?:(?:hey|ok|okay|so|and|um|uh|well|right|marvin|please|kindly|go ahead and|just|now|then|also)\b[\s,.!]*|(?:can|could|would|will) you\b\s*|i(?:'d| would) like you to\b\s*|i want you to\b\s*|let's\b\s*|let us\b\s*)+/i

const ACTION_VERBS = new Set([
  'merge', 'approve', 'deny', 'reject', 'close', 'reopen', 'open', 'create', 'file', 'raise', 'delete', 'remove',
  'drop', 'cancel', 'deploy', 'ship', 'release', 'publish', 'restart', 'reboot', 'kill', 'stop', 'start', 'run',
  'launch', 'install', 'uninstall', 'update', 'upgrade', 'send', 'email', 'text', 'message', 'post', 'reply',
  'comment', 'push', 'commit', 'rebase', 'revert', 'label', 'assign', 'schedule', 'book', 'buy', 'order', 'pay',
  'turn', 'set', 'add', 'move', 'rename', 'archive', 'unsubscribe', 'forward', 'dispatch', 'requeue', 'queue',
  'park', 'unpark', 'claim', 'write', 'edit', 'change', 'fix', 'shut', 'lock', 'unlock', 'play', 'pause', 'call'
])

const QUESTION_START = /^(?:what|what's|whats|which|when|where|who|whose|why|how|did|does|do|has|have|had|is|are|was|were|tell me|show me|list|any|anything)\b/i

// Things the fast brain can't know: MARVIN's own state, or the world right now. Those need the deep brain's tools.
const NEEDS_TOOLS = /\b(?:prs?|pull requests?|tickets?|issues?|main|builds?|board|merged?|pipeline|queue|ci|tests?|deploy(?:ed|s)?|brief|calendar|emails?|inbox|health|vitals|mini|laptop|repo|branch|weather|rain|snow|forecast|temperature|news|score|price|stock|today's|tomorrow|tonight|yesterday|this week|last week|latest|status)\b/i

const FAST_MAX_WORDS = 14

function stripFiller(text) {
  return String(text || '').trim().replace(FILLER, '').trim()
}

export function isSideEffectRequest(text) {
  const raw = String(text || '').trim()
  if (!raw) return false
  const polite = /^(?:(?:hey|ok|okay|so|marvin|please)\b[\s,]*)*(?:can|could|would|will) you\b/i.test(raw)
  if (!polite && QUESTION_START.test(raw.replace(/^(?:(?:hey|ok|okay|so|marvin)\b[\s,]*)+/i, ''))) return false
  const first = stripFiller(raw).split(/[\s,.!?]+/)[0]?.toLowerCase()
  return ACTION_VERBS.has(first)
}

const PRONOUNS = { my: 'your', me: 'you', mine: 'yours', myself: 'yourself' }

export function planFor(text) {
  let rest = stripFiller(text).replace(/[\s,]*\bplease\b[\s,]*/gi, ' ').replace(/[.?!\s]+$/, '').trim()
  rest = rest.replace(/\b(my|me|mine|myself)\b/gi, (w) => PRONOUNS[w.toLowerCase()])
  if (!/[\p{L}\p{N}]/u.test(rest)) return "That needs your OK. Confirm on your phone."
  return `I'd ${rest.charAt(0).toLowerCase()}${rest.slice(1)}. Confirm on your phone.`
}

function withTimeout(promise, ms, fallback) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(fallback), ms)
    Promise.resolve(promise).then(
      (v) => { clearTimeout(timer); resolve(v) },
      () => { clearTimeout(timer); resolve(fallback) }
    )
  })
}

// Returns { kind: 'action' | 'fast' | 'deep', intent, hits }.
// `classify` is the route classifier (skills/route/scripts/route.py, keyword pass): it names an intent once a request
// carries at least two of its keywords. Zero-hit short small talk is the fast brain's; anything else goes deep.
export async function chooseBrain(text, { classify, classifyTimeoutMs = 300 } = {}) {
  if (isSideEffectRequest(text)) return { kind: 'action', intent: null, hits: 0 }
  let routed = { intent: null, hits: 0 }
  if (classify) {
    let call
    try { call = classify(text) } catch { call = null }
    routed = (await withTimeout(call, classifyTimeoutMs, null)) || { intent: null, hits: 0 }
  }
  const words = String(text).trim().split(/\s+/).filter(Boolean).length
  const deep = routed.hits >= 2 || words > FAST_MAX_WORDS || NEEDS_TOOLS.test(text)
  return { kind: deep ? 'deep' : 'fast', intent: routed.intent || null, hits: routed.hits || 0 }
}
