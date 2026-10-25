import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import http from 'http'
import fs from 'fs'
import path from 'path'
import { createBenchApiRouter } from '../mobile-backend/bench_api.js'
import { runBenchmark } from '../mobile-backend/bench_cli.js'

describe('benchmark harness', () => {
  let server
  let baseUrl

  beforeAll(async () => {
    return new Promise((resolve) => {
      const router = createBenchApiRouter()
      server = http.createServer((req, res) => {
        req.gatePeer = 'test-peer'
        router(req, res)
      })

      server.listen(7880, 'localhost', () => {
        baseUrl = 'localhost'
        console.log('Benchmark server listening on http://localhost:7880')
        resolve()
      })
    })
  })

  afterAll(async () => {
    return new Promise((resolve) => {
      server.close(() => {
        console.log('Benchmark server closed')
        resolve()
      })
    })
  })

  it('runs benchmark with 0% loss', async () => {
    const timestamp = Date.now()
    const resultsDir = path.join(
      process.cwd(),
      'mobile-backend/bench-results'
    )

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a', '--loss', '0']

    await runBenchmark({
      exit: () => {}, // Don't actually exit
      resultsDir,
      port: 7880,
      now: () => timestamp,
      randomSuffix: 'loss0'
    })

    // Verify results were written
    const files = fs.readdirSync(resultsDir)
    const resultFile = files.find((f) => f.includes('loss0'))
    expect(resultFile).toBeDefined()

    const content = JSON.parse(fs.readFileSync(path.join(resultsDir, resultFile), 'utf-8'))
    expect(content.a).toBeDefined()
    expect(content.a.pings).toBeDefined()
    expect(content.a.pings.count).toBeGreaterThan(0)

    console.log('Benchmark 0% loss results:', JSON.stringify(content.a, null, 2))
  }, 30000)

  it('runs benchmark with 1% loss', async () => {
    const timestamp = Date.now()
    const resultsDir = path.join(
      process.cwd(),
      'mobile-backend/bench-results'
    )

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a', '--loss', '1']

    await runBenchmark({
      exit: () => {}, // Don't actually exit
      resultsDir,
      port: 7880,
      now: () => timestamp,
      randomSuffix: 'loss1'
    })

    // Verify results were written
    const files = fs.readdirSync(resultsDir)
    const resultFile = files.find((f) => f.includes('loss1'))
    expect(resultFile).toBeDefined()

    const content = JSON.parse(fs.readFileSync(path.join(resultsDir, resultFile), 'utf-8'))
    expect(content.a).toBeDefined()
    expect(content.a.pings).toBeDefined()

    console.log('Benchmark 1% loss results:', JSON.stringify(content.a, null, 2))
  }, 30000)

  it('runs benchmark with 5% loss', async () => {
    const timestamp = Date.now()
    const resultsDir = path.join(
      process.cwd(),
      'mobile-backend/bench-results'
    )

    process.argv = ['node', 'bench_cli.js', '--host', baseUrl, '--legs', 'a', '--loss', '5']

    await runBenchmark({
      exit: () => {}, // Don't actually exit
      resultsDir,
      port: 7880,
      now: () => timestamp,
      randomSuffix: 'loss5'
    })

    // Verify results were written
    const files = fs.readdirSync(resultsDir)
    const resultFile = files.find((f) => f.includes('loss5'))
    expect(resultFile).toBeDefined()

    const content = JSON.parse(fs.readFileSync(path.join(resultsDir, resultFile), 'utf-8'))
    expect(content.a).toBeDefined()
    expect(content.a.pings).toBeDefined()

    console.log('Benchmark 5% loss results:', JSON.stringify(content.a, null, 2))
  }, 30000)
})
