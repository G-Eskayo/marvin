export function createMergeServerHealth({ probe, ttlMs = 30_000, now = Date.now } = {}) {
  let cachedResult = null
  let cachedAt = null
  let inflight = null

  async function check() {
    const age = cachedAt !== null ? now() - cachedAt : Infinity
    if (age < ttlMs && cachedResult !== null) return cachedResult

    if (inflight) return inflight

    inflight = (async () => {
      try {
        cachedResult = await probe()
        cachedAt = now()
      } catch {
        cachedResult = false
        cachedAt = now()
      }
      return cachedResult
    })().finally(() => {
      inflight = null
    })

    return inflight
  }

  function peek() {
    return cachedResult
  }

  function lastCheckedAt() {
    return cachedAt
  }

  return { check, peek, lastCheckedAt }
}
