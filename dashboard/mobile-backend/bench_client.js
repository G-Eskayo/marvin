export function detectReorders(sequence) {
  if (sequence.length < 2) {
    return 0
  }

  let reorders = 0
  let maxSeenSoFar = sequence[0].seqn

  for (let i = 1; i < sequence.length; i++) {
    if (sequence[i].seqn < maxSeenSoFar) {
      reorders++
    } else {
      maxSeenSoFar = sequence[i].seqn
    }
  }

  return reorders
}

export function calculateStats(sequence) {
  if (!sequence || sequence.length === 0) {
    return {
      lossPct: 0,
      reorderCount: 0,
      avgRttMs: 0
    }
  }

  const seqnSet = new Set()
  let minSeqn = Infinity
  let maxSeqn = -Infinity

  for (const packet of sequence) {
    seqnSet.add(packet.seqn)
    minSeqn = Math.min(minSeqn, packet.seqn)
    maxSeqn = Math.max(maxSeqn, packet.seqn)
  }

  const expectedCount = maxSeqn - minSeqn + 1
  const actualCount = seqnSet.size
  const lostCount = expectedCount - actualCount
  const lossPct = (lostCount / expectedCount) * 100

  const rttValues = sequence.map(p => p.rtt).filter(r => typeof r === 'number')
  const avgRttMs = rttValues.length > 0
    ? rttValues.reduce((a, b) => a + b, 0) / rttValues.length
    : 0

  const reorderCount = detectReorders(sequence)

  return {
    lossPct: isNaN(lossPct) ? 0 : lossPct,
    reorderCount,
    avgRttMs
  }
}

export async function runLeg(name, transport, opts = {}) {
  const now = opts.now || Date.now
  const startTime = now()
  const results = {
    name,
    rtt: null,
    ttfb: null,
    throughputMbps: null,
    lossPct: 0,
    reorderCount: 0,
    reconnects: 0,
    unavailable: null
  }

  try {
    await transport.connect()

    const pingStart = now()
    await transport.ping()
    results.rtt = now() - pingStart

    const streamStart = now()
    const streamResult = await transport.stream({ chunks: 10 })
    const streamDuration = now() - streamStart

    const { bytes, ttfbMs, sequence } = streamResult
    results.ttfb = ttfbMs

    if (bytes > 0 && streamDuration > 0) {
      const seconds = streamDuration / 1000
      results.throughputMbps = bytes * 8 / (seconds * 1e6)
    }

    if (sequence && sequence.length > 0) {
      const stats = calculateStats(sequence)
      results.lossPct = stats.lossPct
      results.reorderCount = stats.reorderCount
    }

    await transport.disconnect()
  } catch (err) {
    if (err.code === 'UNAVAILABLE') {
      results.unavailable = err.message
    } else {
      results.unavailable = `${err.code || 'ERROR'}: ${err.message}`
    }
  }

  return results
}
