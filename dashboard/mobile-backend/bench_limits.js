export function clampBytes(size, max) {
  if (size > max) {
    const err = new Error(`Payload exceeds maximum size of ${max} bytes`)
    err.code = 'PAYLOAD_TOO_LARGE'
    err.statusCode = 413
    return err
  }
  return size
}

export function clampChunks(value, defaultValue = 10, max = 1000) {
  if (value === undefined || value === null || value === '') {
    return defaultValue
  }

  const num = parseInt(value, 10)
  if (isNaN(num) || num <= 0) {
    const err = new Error('chunks parameter must be a positive integer')
    err.statusCode = 400
    return err
  }

  return Math.min(num, max)
}

export function createBoundedMap(maxSize = 10000) {
  const entries = new Map()

  return {
    has(key) {
      return entries.has(key)
    },

    get(key) {
      return entries.get(key)
    },

    set(key, value) {
      if (!entries.has(key) && entries.size >= maxSize) {
        const firstKey = entries.keys().next().value
        entries.delete(firstKey)
      }
      entries.set(key, value)
      return this
    },

    get size() {
      return entries.size
    }
  }
}

export function createTokenBucket({ tokensPerSecond = 10, maxBurst = 10, now = Date.now } = {}) {
  let tokens = maxBurst
  let lastRefillTime = now()

  function refill() {
    const currentTime = now()
    const elapsedSeconds = (currentTime - lastRefillTime) / 1000
    const newTokens = elapsedSeconds * tokensPerSecond

    tokens = Math.min(tokens + newTokens, maxBurst)
    lastRefillTime = currentTime
  }

  return {
    tryConsume(amount = 1) {
      refill()

      if (tokens >= amount) {
        tokens -= amount
        return true
      }

      return false
    }
  }
}
