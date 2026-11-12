// Probes the merge server's health and caches the result to avoid repeated queries.
// Follows rework.js's cache shape: module-level cache, TTL constant, single-flight inflight.

const TTL_MS = 30_000
let cache = null
let inflight = null

export const MERGE_SERVER_DOWN_MESSAGE = 'The Mac mini isn\'t answering, so approvals will wait.'

export async function probeMergeServerHealth(url, { fetchImpl, timeoutMs = 3000 } = {}) {
  try {
    const signal = AbortSignal.timeout(timeoutMs)
    const response = await fetchImpl(url, { signal })

    if (!response.ok) {
      return { down: true, error: `HTTP ${response.status}` }
    }

    return { down: false }
  } catch (err) {
    const isTimeout = err instanceof DOMException && err.name === 'TimeoutError'
    const networkErrors = ['ECONNREFUSED', 'ENOTFOUND', 'EHOSTUNREACH']
    const errorCode = err.cause?.code || err.code
    const isNetworkError = (errorCode && networkErrors.includes(errorCode)) ||
                           networkErrors.some(code => err.message && err.message.includes(code))

    if (isTimeout || isNetworkError) {
      return { down: true, error: err.message }
    }

    // Unexpected error: default to "assume up" (resilient, matches other best-effort lookups)
    return { down: false, error: err.message }
  }
}

export async function getMergeServerHealth({ url, now = Date.now(), fetchImpl = fetch, ttlMs = TTL_MS } = {}) {
  // Return cached value if still fresh
  if (cache && now - cache.at < ttlMs) {
    return cache.value
  }

  // Reuse in-flight probe if one is already running
  if (inflight) {
    return inflight
  }

  // Start a new probe and share it
  inflight = (async () => {
    try {
      const result = await probeMergeServerHealth(url, { fetchImpl, timeoutMs: 3000 })
      cache = { at: now, value: result }
      return result
    } catch (err) {
      // If the probe itself throws unexpectedly, assume the server is up
      const result = { down: false, error: `Probe failed: ${err.message}` }
      cache = { at: now, value: result }
      return result
    } finally {
      inflight = null
    }
  })()

  return inflight
}

export function clearMergeServerHealthCache() {
  cache = null
  inflight = null
}
