import { statSync } from 'fs'

// Parse a Range header and return { start, end } for valid ranges, or null for invalid ones.
function parseRange(rangeHeader, fileSize) {
  if (!rangeHeader || typeof rangeHeader !== 'string') return null
  const match = rangeHeader.match(/^bytes=(\d+)-(\d*)$/)
  if (!match) return null

  const start = Number(match[1])
  const end = match[2] === '' ? fileSize - 1 : Number(match[2])

  if (start > end || start < 0 || end >= fileSize) return null
  return { start, end }
}

// Stream a file with HTTP Range support. Handles Range headers, returns 206 for valid ranges,
// 416 for out-of-bounds ranges, and 200 for no/malformed Range headers.
export function streamFileWithRange(req, res, filePath, mime) {
  let stat
  try {
    stat = statSync(filePath)
  } catch (err) {
    res.writeHead(404, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ ok: false, error: `file not found: ${err.message}` }))
    return
  }

  const fileSize = stat.size
  const rangeHeader = req.headers.range

  if (rangeHeader) {
    const range = parseRange(rangeHeader, fileSize)
    if (range === null) {
      res.writeHead(416, {
        'Content-Range': `bytes */${fileSize}`,
        'Content-Type': mime || 'application/octet-stream'
      })
      res.end()
      return
    }

    const { start, end } = range
    const length = end - start + 1

    res.writeHead(206, {
      'Content-Type': mime || 'application/octet-stream',
      'Content-Length': length,
      'Content-Range': `bytes ${start}-${end}/${fileSize}`,
      'Accept-Ranges': 'bytes'
    })
    res.createReadStream(filePath, { start, end }).pipe(res)
    return
  }

  res.writeHead(200, {
    'Content-Type': mime || 'application/octet-stream',
    'Content-Length': fileSize,
    'Accept-Ranges': 'bytes'
  })
  res.createReadStream(filePath).pipe(res)
}
