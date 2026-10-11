import { homedir } from 'os'
import path from 'path'
import { createReadStream, statSync } from 'fs'
import { pipeline } from 'stream/promises'
import { createImageLoader, mediaFileFor } from '../electron/main/pr_images.js'

const MEDIA_CACHE_DIR = path.join(homedir(), '.claude', 'pr-media-cache')

export function createMrMediaRouter({ cacheDir = MEDIA_CACHE_DIR, loader, createReadStream: customCreateReadStream } = {}) {
  const imageLoader = loader || createImageLoader({ cacheDir })
  const readStream = customCreateReadStream || createReadStream

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname
    const searchParams = url.searchParams

    // GET /mr/media?url=<url>&kind=<kind>
    if (req.method === 'GET' && pathname === '/mr/media') {
      const mediaUrl = searchParams.get('url')
      const kind = searchParams.get('kind') || 'auto'

      if (!mediaUrl) {
        res.writeHead(400, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: false, error: 'Missing url parameter' })
        )
        return true
      }

      try {
        const result = await imageLoader.load(mediaUrl, kind)

        if (!result.ok) {
          let statusCode = 502
          if (result.reason?.includes('not found')) statusCode = 404
          if (result.reason?.includes('only https') || result.reason?.includes("isn't loaded") || result.reason?.includes('not a valid')) statusCode = 400
          res.writeHead(statusCode, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: result.reason || 'Failed to load media' })
          )
          return true
        }

        if (result.kind === 'image') {
          // Decode data URL and stream bytes
          const dataUrlMatch = result.dataUrl?.match(/^data:([^;]+);base64,(.+)$/)
          if (!dataUrlMatch) {
            res.writeHead(502, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: 'Invalid image data format' })
            )
            return true
          }

          const mimeType = dataUrlMatch[1]
          const base64Data = dataUrlMatch[2]
          const buffer = Buffer.from(base64Data, 'base64')

          res.writeHead(200, {
            'Content-Type': mimeType,
            'Content-Length': buffer.length,
            'Cache-Control': 'public, max-age=31536000'
          })
          res.end(buffer)
          return true
        }

        if (result.kind === 'video') {
          // Resolve cached video file and stream with Range support
          const videoFile = mediaFileFor(cacheDir, result.src.split('/').pop())
          if (!videoFile) {
            res.writeHead(502, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: 'Video file not found in cache' })
            )
            return true
          }

          const mimeType = `video/${videoFile.mime.split('/')[1]}`
          const fileStats = statSync(videoFile.file)
          const fileSize = fileStats.size

          // Parse Range header if present
          const rangeHeader = req.headers.range
          if (rangeHeader) {
            const rangeMatch = rangeHeader.match(/^bytes=(\d+)-(\d*)$/)
            if (!rangeMatch) {
              res.writeHead(416, {
                'Content-Range': `bytes */${fileSize}`,
                'Content-Type': mimeType
              }).end()
              return true
            }

            const start = parseInt(rangeMatch[1], 10)
            let end = rangeMatch[2] ? parseInt(rangeMatch[2], 10) : fileSize - 1

            if (start >= fileSize || start > end) {
              res.writeHead(416, {
                'Content-Range': `bytes */${fileSize}`,
                'Content-Type': mimeType
              }).end()
              return true
            }

            end = Math.min(end, fileSize - 1)
            const length = end - start + 1
            const stream = readStream(videoFile.file, { start, end })

            res.writeHead(206, {
              'Content-Type': mimeType,
              'Content-Length': length,
              'Content-Range': `bytes ${start}-${end}/${fileSize}`,
              'Accept-Ranges': 'bytes',
              'Cache-Control': 'public, max-age=31536000'
            })

            try {
              await pipeline(stream, res)
            } catch (error) {
              if (!res.headersSent) {
                res.writeHead(502, { 'Content-Type': 'application/json' }).end(
                  JSON.stringify({ ok: false, error: 'Failed to stream video' })
                )
              } else {
                res.destroy()
              }
            }
            return true
          }

          // No Range header: full file response
          const stream = readStream(videoFile.file)

          res.writeHead(200, {
            'Content-Type': mimeType,
            'Content-Length': fileSize,
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'public, max-age=31536000'
          })

          try {
            await pipeline(stream, res)
          } catch (error) {
            if (!res.headersSent) {
              res.writeHead(502, { 'Content-Type': 'application/json' }).end(
                JSON.stringify({ ok: false, error: 'Failed to stream video' })
              )
            } else {
              res.destroy()
            }
          }
          return true
        }

        res.writeHead(502, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: false, error: 'Unknown media kind' })
        )
        return true
      } catch (error) {
        res.writeHead(502, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: false, error: error.message || 'Internal server error' })
        )
        return true
      }
    }

    return false
  }
}
