import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { dirname } from 'path'

// Persists which pipeline-PR numbers this machine has already seen, so the
// MR Review tab can carry a status dot without opening it: red (at least
// one open PR never seen), blue (open PRs exist, all already seen, still
// awaiting approval), or green (no open PRs at all).
//
// Local-only by design -- "seen" is a per-viewer concept, not shared
// GitHub state, and there's no existing cross-device sync mechanism for
// dashboard UI state (G-Eskayo/marvin#74 already flags that as a separate,
// harder, undesigned problem). If you review on a different machine, that
// machine's own file starts unseen, which is arguably correct: you
// haven't looked at this list on this device yet.

export function readSeenNumbers(path) {
  if (!existsSync(path)) return []
  try {
    const data = JSON.parse(readFileSync(path, 'utf-8'))
    return Array.isArray(data.seen) ? data.seen : []
  } catch {
    return []
  }
}

export function markSeen(path, prNumbers) {
  const existing = new Set(readSeenNumbers(path))
  for (const n of prNumbers) existing.add(n)
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, JSON.stringify({ seen: [...existing] }))
}

export function computeReviewStatus(openPrNumbers, seenNumbers) {
  if (openPrNumbers.length === 0) return 'green'
  const seen = new Set(seenNumbers)
  const hasUnseen = openPrNumbers.some((n) => !seen.has(n))
  return hasUnseen ? 'red' : 'blue'
}
