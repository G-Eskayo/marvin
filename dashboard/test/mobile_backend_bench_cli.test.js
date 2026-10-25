import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'fs'
import path from 'path'
import { tmpdir } from 'os'
import http from 'http'
import { runBenchmark } from '../mobile-backend/bench_cli.js'
import { createBenchApiRouter } from '../mobile-backend/bench_api.js'

describe('bench_cli', () => {
  let tempDir
  let server
  let baseUrl

  beforeEach(async () => {
    tempDir = fs.mkdtempSync(path.join(tmpdir(), 'bench-test-'))

    const router = createBenchApiRouter()
    server = http.createServer((req, res) => {
      req.gatePeer = 'test-peer'
      router(req, res)
    })

    return new Promise((resolve) => {
      server.listen(0, 'localhost', () => {
        const addr = server.address()
        baseUrl = `localhost`
        // Store the port for use in tests
        process.env.TEST_BENCH_PORT = addr.port
        resolve()
      })
    })
  })

  afterEach(async () => {
    try {
      fs.rmSync(tempDir, { recursive: true })
    } catch {}

    return new Promise((resolve) => {
      server.close(() => resolve())
    })
  })

  it('writes JSON results to file with timestamp', async () => {
    const mockExit = vi.fn()
    const timestamp = 1000000000000

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a']

    await runBenchmark({
      exit: mockExit,
      resultsDir: tempDir,
      now: () => timestamp,
      randomSuffix: 'test123',
      port: parseInt(process.env.TEST_BENCH_PORT, 10)
    })

    expect(mockExit).not.toHaveBeenCalled()

    const files = fs.readdirSync(tempDir)
    expect(files.length).toBe(1)
    expect(files[0]).toContain('test123')

    const content = JSON.parse(fs.readFileSync(path.join(tempDir, files[0]), 'utf-8'))
    expect(content.a).toBeDefined()
    expect(content.a.name).toBe('leg-a')
  })

  it('creates bench-results directory if missing', async () => {
    const resultsDir = path.join(tempDir, 'nested', 'bench-results')
    const timestamp = 1000000000000

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a']

    await runBenchmark({
      exit: vi.fn(),
      resultsDir,
      now: () => timestamp,
      randomSuffix: 'test456',
      port: parseInt(process.env.TEST_BENCH_PORT, 10)
    })

    expect(fs.existsSync(resultsDir)).toBe(true)

    const files = fs.readdirSync(resultsDir)
    expect(files.length).toBeGreaterThan(0)
  })

  it('accepts resultsDir as injectable parameter', async () => {
    const mockExit = vi.fn()
    const timestamp = 1000000000000

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a']

    await runBenchmark({
      exit: mockExit,
      resultsDir: tempDir,
      now: () => timestamp,
      randomSuffix: 'test789',
      port: parseInt(process.env.TEST_BENCH_PORT, 10)
    })

    expect(mockExit).not.toHaveBeenCalled()

    const files = fs.readdirSync(tempDir)
    expect(files.length).toBe(1)
  })

  it('--out flag overrides resultsDir', async () => {
    const mockExit = vi.fn()
    const outDir = path.join(tempDir, 'custom-out')
    const timestamp = 1000000000000

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a', '--out', outDir]

    await runBenchmark({
      exit: mockExit,
      resultsDir: tempDir,
      now: () => timestamp,
      randomSuffix: 'testout',
      port: parseInt(process.env.TEST_BENCH_PORT, 10)
    })

    expect(fs.existsSync(outDir)).toBe(true)
    const files = fs.readdirSync(outDir)
    expect(files.length).toBe(1)
    // Results are written to outDir, not tempDir
  })

  it('exits with code 1 when --host is missing', async () => {
    const mockExit = vi.fn()

    process.argv = ['node', 'bench_cli.js']

    await runBenchmark({
      exit: mockExit,
      resultsDir: tempDir,
      now: () => Date.now()
    })

    expect(mockExit).toHaveBeenCalledWith(1)
  })

  it('formats results with pings, streams, errors, and reorders', async () => {
    const mockExit = vi.fn()
    const timestamp = 1000000000000

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a']

    await runBenchmark({
      exit: mockExit,
      resultsDir: tempDir,
      now: () => timestamp,
      randomSuffix: 'testfmt',
      port: parseInt(process.env.TEST_BENCH_PORT, 10)
    })

    const files = fs.readdirSync(tempDir)
    const content = JSON.parse(fs.readFileSync(path.join(tempDir, files[0]), 'utf-8'))

    expect(content.a.pings).toBeDefined()
    expect(typeof content.a.pings).toBe('object')
    expect(content.a.pings.count).toBeGreaterThan(0)

    expect(content.a.streams).toBeDefined()
    expect(typeof content.a.streams).toBe('object')
    expect(content.a.streams.count).toBeGreaterThan(0)

    expect(content.a.errors).toBeDefined()
    expect(Array.isArray(content.a.errors)).toBe(true)

    expect(content.a.reorders).toBeDefined()
    expect(typeof content.a.reorders).toBe('number')
  })

  it('generates unique filenames with random suffix under frozen clock', async () => {
    const mockExit = vi.fn()
    const timestamp = 1000000000000

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a']

    await runBenchmark({
      exit: mockExit,
      resultsDir: tempDir,
      now: () => timestamp,
      randomSuffix: 'rand1',
      port: parseInt(process.env.TEST_BENCH_PORT, 10)
    })

    await runBenchmark({
      exit: mockExit,
      resultsDir: tempDir,
      now: () => timestamp,
      randomSuffix: 'rand2',
      port: parseInt(process.env.TEST_BENCH_PORT, 10)
    })

    const files = fs.readdirSync(tempDir)
    expect(files.length).toBe(2)
    expect(files[0]).not.toEqual(files[1])
  })

  it('supports injectable now() function for timestamp generation', async () => {
    const mockExit = vi.fn()
    const customTime = new Date('2025-01-15T12:30:45.123Z').getTime()

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a']

    await runBenchmark({
      exit: mockExit,
      resultsDir: tempDir,
      now: () => customTime,
      randomSuffix: 'testtime',
      port: parseInt(process.env.TEST_BENCH_PORT, 10)
    })

    const files = fs.readdirSync(tempDir)
    expect(files[0]).toContain('2025-01-15')
    expect(files[0]).toContain('testtime')
  })
})
