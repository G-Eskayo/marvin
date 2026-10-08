export function createLiveApiRouter(liveChannel) {
  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    if (req.method !== 'GET' || pathname !== '/live') {
      return false
    }

    // Streaming NDJSON response
    res.writeHead(200, {
      'Content-Type': 'application/x-ndjson',
      'Transfer-Encoding': 'chunked'
    })

    // Connect to the live channel
    const listener = (event) => {
      res.write(JSON.stringify(event) + '\n')
    }

    liveChannel.connect(listener)

    // On client close, disconnect
    req.on('close', () => {
      liveChannel.disconnect()
    })

    return true
  }
}
