export const MAX_ECHO_BODY_BYTES = 10 * 1024 * 1024
export const DEFAULT_TIMEOUT_MS = 30000

export function clampBytes(value, min = 0, max = Infinity) {
  return Math.max(min, Math.min(max, value))
}

export function clampChunks(count, min = 1, max = 1000) {
  return Math.max(min, Math.min(max, Math.floor(count)))
}

export function createTokenBucket({ tokensPerSecond, maxBurst, now = Date.now }) {
  let tokens = maxBurst
  let lastRefillMs = now()

  return {
    tryConsume(count = 1) {
      const nowMs = now()
      const elapsedSecs = (nowMs - lastRefillMs) / 1000
      tokens = Math.min(maxBurst, tokens + elapsedSecs * tokensPerSecond)
      lastRefillMs = nowMs

      if (tokens >= count) {
        tokens -= count
        return true
      }
      return false
    }
  }
}

export function createBoundedMap(maxSize) {
  const map = new Map()

  return {
    set(key, value) {
      if (map.has(key)) {
        map.delete(key)
      }
      if (map.size >= maxSize) {
        const firstKey = map.keys().next().value
        map.delete(firstKey)
      }
      map.set(key, value)
    },

    get(key) {
      return map.get(key)
    },

    has(key) {
      return map.has(key)
    },

    delete(key) {
      return map.delete(key)
    },

    get size() {
      return map.size
    },

    clear() {
      map.clear()
    },

    keys() {
      return map.keys()
    },

    values() {
      return map.values()
    },

    entries() {
      return map.entries()
    }
  }
}
