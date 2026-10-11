import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createServer } from 'http'
import { request } from 'http'
import { mkdtempSync, rmSync, writeFileSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createHash } from 'crypto'
import { mediaFileFor } from '../electron/main/pr_images.js'

import { createMrMediaRouter } from '../mobile-backend/mr_media.js'

const hashOf = (url) => createHash('sha256').update(url).digest('hex')

function startTestServer(router) {
  const server = createServer(async (req, res) => {
    const handled = await router(req, res)
    if (!handled) {
      res.writeHead(404).end()
    }
  })
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      resolve({ server, url: `http://${addr.address}:${addr.port}` })
    })
  })
}

async function makeRequest(baseUrl, urlPath, method = 'GET', headers = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, baseUrl)
    const client = request(url, { method, headers }, (res) => {
      let data = Buffer.alloc(0)
      res.on('data', (chunk) => {
        data = Buffer.concat([data, chunk])
      })
      res.on('end', () => {
        const contentType = res.headers['content-type']
        let body
        try {
          if (contentType?.includes('application/json')) {
            body = JSON.parse(data.toString())
          } else {
            body = data
          }
        } catch {
          body = data.toString()
        }
        resolve({
          statusCode: res.statusCode,
          headers: res.headers,
          body
        })
      })
    })
    client.on('error', reject)
    client.end()
  })
}

describe('MR Media route', () => {
  let tempDir
  let fakeLoader

  beforeEach(() => {
    tempDir = mkdtempSync(path.join(tmpdir(), 'mr-media-test-'))
    vi.clearAllMocks()

    // Create fake loader that returns test data without network calls
    fakeLoader = {
      load: vi.fn(async (url, kind) => {
        if (kind === 'image') {
          // Return a small test PNG as base64 data URL
          const pngBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
          return {
            ok: true,
            kind: 'image',
            dataUrl: `data:image/png;base64,${pngBase64}`
          }
        }
        if (kind === 'video') {
          // Return the video URL hashed as the prmedia:// id
          const id = hashOf('https://github.com/example/video.mp4')
          return {
            ok: true,
            kind: 'video',
            src: `prmedia://media/${id}`
          }
        }
        if (kind === 'unknown') {
          return {
            ok: true,
            kind: 'unknown'
          }
        }
        return {
          ok: false,
          reason: 'Failed to load media'
        }
      })
    }
  })

  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true })
  })

  describe('GET /mr/media', () => {
    it('returns 400 if url parameter missing', async () => {
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media')
          expect(res.statusCode).toBe(400)
          expect(res.body.error).toContain('Missing url')
        } finally {
          server.close()
        }
      })
    })

    it('returns 400 if url is empty', async () => {
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=')
          expect(res.statusCode).toBe(400)
          expect(res.body.error).toContain('Missing url')
        } finally {
          server.close()
        }
      })
    })

    it('returns image data when kind=image', async () => {
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/image.png&kind=image')
          expect(res.statusCode).toBe(200)
          expect(res.headers['content-type']).toBe('image/png')
          expect(res.headers['cache-control']).toBe('public, max-age=31536000')
          expect(res.body).toBeInstanceOf(Buffer)
          expect(res.body.length).toBeGreaterThan(0)
        } finally {
          server.close()
        }
      })
    })

    it('returns 502 for failed image data format', async () => {
      const badLoader = {
        load: vi.fn(async () => ({
          ok: true,
          kind: 'image',
          dataUrl: 'not-a-valid-data-url'
        }))
      }
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: badLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/image.png&kind=image')
          expect(res.statusCode).toBe(502)
          expect(res.body.error).toContain('Invalid image data format')
        } finally {
          server.close()
        }
      })
    })

    it('streams video without Range header (200)', async () => {
      // Create a test video file
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(1024, 'test data')
      writeFileSync(videoFile, testData)

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video')
          expect(res.statusCode).toBe(200)
          expect(res.headers['content-type']).toBe('video/mp4')
          expect(res.headers['accept-ranges']).toBe('bytes')
          expect(res.headers['content-length']).toBe('1024')
          expect(res.body).toBeInstanceOf(Buffer)
          expect(res.body.length).toBe(1024)
        } finally {
          server.close()
        }
      })
    })

    it('handles Range requests (206 Partial Content)', async () => {
      // Create a test video file with known content
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(1000, 'x')
      writeFileSync(videoFile, testData)

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video', 'GET', {
            range: 'bytes=0-99'
          })
          expect(res.statusCode).toBe(206)
          expect(res.headers['content-type']).toBe('video/mp4')
          expect(res.headers['content-range']).toBe('bytes 0-99/1000')
          expect(res.headers['content-length']).toBe('100')
          expect(res.body.length).toBe(100)
        } finally {
          server.close()
        }
      })
    })

    it('returns 416 for out-of-range request', async () => {
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(1000, 'x')
      writeFileSync(videoFile, testData)

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video', 'GET', {
            range: 'bytes=5000-6000'
          })
          expect(res.statusCode).toBe(416)
          expect(res.headers['content-range']).toBe('bytes */1000')
        } finally {
          server.close()
        }
      })
    })

    it('returns 416 for malformed Range header', async () => {
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(1000, 'x')
      writeFileSync(videoFile, testData)

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video', 'GET', {
            range: 'bytes=invalid-range'
          })
          expect(res.statusCode).toBe(416)
          expect(res.headers['content-range']).toBe('bytes */1000')
        } finally {
          server.close()
        }
      })
    })

    it('returns 502 when video file not found in cache', async () => {
      const badLoaderWithVideo = {
        load: vi.fn(async () => ({
          ok: true,
          kind: 'video',
          src: 'https://github.com/example/video.mp4'
        }))
      }

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: badLoaderWithVideo })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/video.mp4&kind=video')
          expect(res.statusCode).toBe(502)
          expect(res.body.error).toContain('Video file not found')
        } finally {
          server.close()
        }
      })
    })

    it('returns 502 for unknown media kind', async () => {
      const unknownKindLoader = {
        load: vi.fn(async () => ({
          ok: true,
          kind: 'unknown'
        }))
      }
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: unknownKindLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/file.bin&kind=unknown')
          expect(res.statusCode).toBe(502)
          expect(res.body.error).toContain('Unknown media kind')
        } finally {
          server.close()
        }
      })
    })

    it('returns appropriate status code for loader errors', async () => {
      const errorLoader = {
        load: vi.fn(async () => ({
          ok: false,
          reason: 'only https'
        }))
      }
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: errorLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=http://example.com/image.png')
          expect(res.statusCode).toBe(400)
          expect(res.body.error).toContain('https')
        } finally {
          server.close()
        }
      })
    })

    it('returns 404 for not found loader errors', async () => {
      const notFoundLoader = {
        load: vi.fn(async () => ({
          ok: false,
          reason: 'Asset not found'
        }))
      }
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: notFoundLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/missing.png')
          expect(res.statusCode).toBe(404)
          expect(res.body.error).toContain('not found')
        } finally {
          server.close()
        }
      })
    })

    it('returns 502 for generic loader errors', async () => {
      const genericErrorLoader = {
        load: vi.fn(async () => ({
          ok: false,
          reason: 'Download failed'
        }))
      }
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: genericErrorLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/file.bin')
          expect(res.statusCode).toBe(502)
        } finally {
          server.close()
        }
      })
    })

    it('handles exceptions from loader gracefully', async () => {
      const throwingLoader = {
        load: vi.fn(async () => {
          throw new Error('Network timeout')
        })
      }
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: throwingLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/image.png')
          expect(res.statusCode).toBe(502)
          expect(res.body.error).toContain('Network timeout')
        } finally {
          server.close()
        }
      })
    })

    it('unmatched routes return false to allow parent router to handle', async () => {
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/other-route')
          expect(res.statusCode).toBe(404)
        } finally {
          server.close()
        }
      })
    })

    it('allows Range request with open-ended end byte', async () => {
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(1000, 'x')
      writeFileSync(videoFile, testData)

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video', 'GET', {
            range: 'bytes=500-'
          })
          expect(res.statusCode).toBe(206)
          expect(res.headers['content-range']).toBe('bytes 500-999/1000')
          expect(res.headers['content-length']).toBe('500')
        } finally {
          server.close()
        }
      })
    })

    // Test 1: Range end byte clamping (over-specified end should clamp to file size - 1)
    it('clamps Range end-byte to EOF and serves 206', async () => {
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(1000, 'x')
      writeFileSync(videoFile, testData)

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          // Request bytes 0-999999 on a 1000-byte file; should clamp to 0-999
          const res = await makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video', 'GET', {
            range: 'bytes=0-999999'
          })
          expect(res.statusCode).toBe(206)
          expect(res.headers['content-range']).toBe('bytes 0-999/1000')
          expect(res.headers['content-length']).toBe('1000')
          expect(res.body.length).toBe(1000)
        } finally {
          server.close()
        }
      })
    })

    // Test 2: Range boundary case (valid start, end past EOF should clamp)
    it('handles Range with valid start and over-specified end', async () => {
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(1000, 'x')
      writeFileSync(videoFile, testData)

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          // Request bytes 999-999999 on a 1000-byte file; should serve bytes 999-999
          const res = await makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video', 'GET', {
            range: 'bytes=999-999999'
          })
          expect(res.statusCode).toBe(206)
          expect(res.headers['content-range']).toBe('bytes 999-999/1000')
          expect(res.headers['content-length']).toBe('1')
          expect(res.body.length).toBe(1)
        } finally {
          server.close()
        }
      })
    })

    // Test 3: Client aborts mid-stream - test injected createReadStream error handling
    it('handles aborted mid-range request and survives for subsequent requests', async () => {
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(10000, 'x') // larger file to allow abort mid-stream
      writeFileSync(videoFile, testData)

      // Create a mock stream that can be destroyed and whose destroy method we can spy on
      let createdStream = null
      const mockCreateReadStream = vi.fn((filePath, options) => {
        const realStream = require('fs').createReadStream(filePath, options)
        createdStream = realStream
        const destroy = vi.spyOn(realStream, 'destroy')
        return realStream
      })

      const router = createMrMediaRouter({
        cacheDir: tempDir,
        loader: fakeLoader,
        createReadStream: mockCreateReadStream
      })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          // Make a range request but abort early - we'll do this by creating the request
          // and closing the socket before reading all data
          await new Promise((resolve) => {
            const httpReq = request(
              new URL('/mr/media?url=https://github.com/example/video.mp4&kind=video', url),
              { headers: { range: 'bytes=0-9999' } },
              (res) => {
                let chunks = 0
                res.on('data', () => {
                  chunks++
                  if (chunks > 0) {
                    // Abort after first chunk
                    httpReq.abort()
                  }
                })
                res.on('end', () => resolve())
                res.on('close', () => resolve())
              }
            )
            httpReq.on('error', () => resolve())
            httpReq.end()
          })

          // Give the stream a moment to process cleanup
          await new Promise((r) => setTimeout(r, 10))

          // Now make another request to the same server to verify it's still alive
          const res2 = await makeRequest(url, '/mr/media?url=https://example.com/image.png&kind=image')
          expect(res2.statusCode).toBe(200)
          expect(res2.headers['content-type']).toBe('image/png')
        } finally {
          server.close()
        }
      })
    })


    // Test 6: Loader error 'not a valid address'
    it("returns 400 for loader error 'not a valid address'", async () => {
      const loaderWithError = {
        load: vi.fn(async () => ({
          ok: false,
          reason: 'not a valid address'
        }))
      }
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: loaderWithError })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/image.png')
          expect(res.statusCode).toBe(400)
          expect(res.body.error).toContain('not a valid')
        } finally {
          server.close()
        }
      })
    })

    // Test 7: Loader error 'too large'
    it("returns 502 for loader error 'too large'", async () => {
      const loaderWithError = {
        load: vi.fn(async () => ({
          ok: false,
          reason: 'too large (20 MB)'
        }))
      }
      const router = createMrMediaRouter({ cacheDir: tempDir, loader: loaderWithError })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/media?url=https://example.com/video.mp4')
          expect(res.statusCode).toBe(502)
          expect(res.body.error).toContain('too large')
        } finally {
          server.close()
        }
      })
    })

    // Test 8: Concurrent requests with different Range headers
    it('handles concurrent Range requests independently', async () => {
      const videoUrl = 'https://github.com/example/video.mp4'
      const videoId = hashOf(videoUrl)
      const videoFile = path.join(tempDir, `${videoId}.mp4`)
      const testData = Buffer.alloc(1000, 'x')
      writeFileSync(videoFile, testData)

      const router = createMrMediaRouter({ cacheDir: tempDir, loader: fakeLoader })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          // Make two concurrent range requests
          const [res1, res2] = await Promise.all([
            makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video', 'GET', {
              range: 'bytes=0-99'
            }),
            makeRequest(url, '/mr/media?url=https://github.com/example/video.mp4&kind=video', 'GET', {
              range: 'bytes=500-599'
            })
          ])

          // Both should succeed with correct ranges
          expect(res1.statusCode).toBe(206)
          expect(res1.headers['content-range']).toBe('bytes 0-99/1000')
          expect(res1.headers['content-length']).toBe('100')
          expect(res1.body.length).toBe(100)

          expect(res2.statusCode).toBe(206)
          expect(res2.headers['content-range']).toBe('bytes 500-599/1000')
          expect(res2.headers['content-length']).toBe('100')
          expect(res2.body.length).toBe(100)
        } finally {
          server.close()
        }
      })
    })
  })
})
