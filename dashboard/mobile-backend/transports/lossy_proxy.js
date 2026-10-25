function seededRandom(seed) {
  const x = Math.sin(seed++) * 10000
  return x - Math.floor(x)
}

export function createLossyProxy(transport, { lossRate = 0, reorderRate = 0, seed = 0 }) {
  let rngState = seed

  function shouldDrop() {
    if (lossRate <= 0) return false
    const rand = seededRandom(rngState++)
    return rand < lossRate / 100
  }

  function shouldReorder() {
    if (reorderRate <= 0) return false
    const rand = seededRandom(rngState++)
    return rand < reorderRate / 100
  }

  return {
    async connect() {
      return transport.connect()
    },

    async disconnect() {
      return transport.disconnect()
    },

    async ping() {
      if (shouldDrop()) {
        throw new Error('ping dropped (simulated loss)')
      }
      return transport.ping()
    },

    async stream(chunkCount = 10) {
      if (shouldDrop()) {
        throw new Error('stream dropped (simulated loss)')
      }

      const result = await transport.stream(chunkCount)

      if (shouldReorder() && result.chunkSequence && result.chunkSequence.length >= 2) {
        const rand = seededRandom(rngState++)
        const i = Math.floor(rand * (result.chunkSequence.length - 1))
        const temp = result.chunkSequence[i]
        result.chunkSequence[i] = result.chunkSequence[i + 1]
        result.chunkSequence[i + 1] = temp
      }

      return result
    }
  }
}
