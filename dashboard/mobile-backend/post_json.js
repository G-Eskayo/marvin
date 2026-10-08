import http from 'http'
import https from 'https'

// POST JSON to a webhook URL. Resolves with a fetch-like { ok, status, json() };
// a non-JSON reply body comes back as { error: <body> }. Rejects on network error.
export async function postJson(url, payload) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload)
    const urlObj = new URL(url)
    const options = {
      hostname: urlObj.hostname,
      port: urlObj.port,
      path: urlObj.pathname + urlObj.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }

    const transport = urlObj.protocol === 'https:' ? https : http
    const req = transport.request(options, (res) => {
      let data = ''
      res.on('data', (chunk) => { data += chunk })
      res.on('end', () => {
        const ok = res.statusCode >= 200 && res.statusCode < 300
        try {
          const json = JSON.parse(data)
          resolve({ ok, status: res.statusCode, json: async () => json })
        } catch {
          resolve({ ok, status: res.statusCode, json: async () => ({ error: data }) })
        }
      })
    })

    req.on('error', reject)
    req.write(body)
    req.end()
  })
}
