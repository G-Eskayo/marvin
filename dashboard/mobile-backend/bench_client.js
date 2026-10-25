export function throughputMbps(bytes, elapsedMs) {
  return (bytes * 8) / (elapsedMs * 1000)
}

export function detectReorders(chunks) {
  let lastIdx = -1
  let reorders = 0
  for (let i = 0; i < chunks.length; i++) {
    if (chunks[i] < lastIdx) {
      reorders++
    }
    lastIdx = Math.max(lastIdx, chunks[i])
  }
  return reorders
}

export function calculateStats(results) {
  if (results.length === 0) {
    return {
      count: 0,
      mean: 0,
      stddev: 0,
      min: 0,
      max: 0
    }
  }

  const sorted = [...results].sort((a, b) => a - b)
  const mean = sorted.reduce((sum, x) => sum + x, 0) / sorted.length
  const variance = sorted.reduce((sum, x) => sum + Math.pow(x - mean, 2), 0) / sorted.length
  const stddev = Math.sqrt(variance)

  return {
    count: sorted.length,
    mean: parseFloat(mean.toFixed(2)),
    stddev: parseFloat(stddev.toFixed(2)),
    min: sorted[0],
    max: sorted[sorted.length - 1],
    p50: sorted[Math.floor(sorted.length * 0.5)],
    p95: sorted[Math.floor(sorted.length * 0.95)],
    p99: sorted[Math.floor(sorted.length * 0.99)]
  }
}

export async function runLeg(name, transport, opts = {}) {
  const now = opts.now || Date.now
  const maxRetries = opts.maxRetries !== undefined ? opts.maxRetries : 1
  const results = {
    name,
    pings: [],
    streams: [],
    errors: [],
    reorders: 0
  }

  const numPings = opts.numPings || 10
  const numStreams = opts.numStreams || 5
  const streamChunks = opts.streamChunks || 10

  try {
    await transport.connect()
  } catch (err) {
    results.errors.push(`connect failed: ${err.message}`)
    return results
  }

  for (let i = 0; i < numPings; i++) {
    let lastErr
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        const result = await transport.ping()
        results.pings.push(result.ttfbMs)
        lastErr = null
        break
      } catch (err) {
        lastErr = err
        if (attempt === maxRetries && i === numPings - 1) {
          try {
            await transport.disconnect()
            await transport.connect()
          } catch (reconnectErr) {
            results.errors.push(`reconnect failed: ${reconnectErr.message}`)
            return results
          }
        }
      }
    }
    if (lastErr) {
      results.errors.push(`ping ${i} failed: ${lastErr.message}`)
    }
  }

  for (let i = 0; i < numStreams; i++) {
    let lastErr
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        const result = await transport.stream(streamChunks)
        results.streams.push({
          totalBytes: result.totalBytes,
          elapsedMs: result.elapsedMs,
          throughputMbps: throughputMbps(result.totalBytes, result.elapsedMs),
          chunkSequence: result.chunkSequence
        })
        if (result.chunkSequence) {
          results.reorders += detectReorders(result.chunkSequence)
        }
        lastErr = null
        break
      } catch (err) {
        lastErr = err
      }
    }
    if (lastErr) {
      results.errors.push(`stream ${i} failed: ${lastErr.message}`)
    }
  }

  try {
    await transport.disconnect()
  } catch (err) {
    results.errors.push(`disconnect failed: ${err.message}`)
  }

  return results
}
