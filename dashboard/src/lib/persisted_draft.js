// Persistent draft storage using localStorage with defensive error handling
// for quota exhaustion and private-mode restrictions. Stores strings directly.

export function readStored(key, fallback = '') {
  try {
    if (typeof localStorage === 'undefined') return fallback
    const stored = localStorage.getItem(key)
    return stored === null ? fallback : stored
  } catch (err) {
    // QuotaExceededError, SecurityError (private mode), or other access errors
    console.warn(`[persisted_draft] could not read ${key}: ${err.message}`)
    return fallback
  }
}

export function writeStored(key, value) {
  try {
    if (typeof localStorage === 'undefined') return
    localStorage.setItem(key, value)
  } catch (err) {
    if (err.name === 'QuotaExceededError') {
      console.warn(`[persisted_draft] localStorage quota exceeded`)
    } else if (err.name === 'SecurityError') {
      console.warn(`[persisted_draft] localStorage blocked (private mode?)`)
    } else {
      console.warn(`[persisted_draft] could not write ${key}: ${err.message}`)
    }
  }
}

export function clearStored(key) {
  try {
    if (typeof localStorage === 'undefined') return
    localStorage.removeItem(key)
  } catch (err) {
    console.warn(`[persisted_draft] could not clear ${key}: ${err.message}`)
  }
}
