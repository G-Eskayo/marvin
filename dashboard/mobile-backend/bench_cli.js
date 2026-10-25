#!/usr/bin/env node

import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { createHttpTailscaleTransport } from './transports/http_tailscale.js'
import { createLossyProxy } from './transports/lossy_proxy.js'
import { runLeg, calculateStats } from './bench_client.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DEFAULT_BENCH_RESULTS_DIR = path.join(__dirname, 'bench-results')

function parseArgs() {
  const args = process.argv.slice(2)
  const opts = {
    legs: 'a',
    host: null,
    loss: 0,
    out: null
  }

  for (let i = 0; i < args.length; i++) {
    const arg = args[i]
    if (arg === '--legs') {
      opts.legs = args[++i] || 'a'
    } else if (arg === '--host') {
      opts.host = args[++i]
    } else if (arg === '--loss') {
      opts.loss = parseFloat(args[++i] || '0')
    } else if (arg === '--out') {
      opts.out = args[++i]
    }
  }

  return opts
}

function formatResults(legName, legResult) {
  const pingStats = calculateStats(legResult.pings || [])
  const streamStats = calculateStats(
    (legResult.streams || []).map((s) => s.throughputMbps)
  )

  return {
    name: legName,
    pings: pingStats,
    streams: streamStats,
    errors: legResult.errors || [],
    reorders: legResult.reorders || 0
  }
}

export async function runBenchmark(injected = {}) {
  const opts = parseArgs()
  const exit = injected.exit || process.exit
  let resultsDir = injected.resultsDir || DEFAULT_BENCH_RESULTS_DIR
  const now = injected.now || Date.now
  const randomSuffix = injected.randomSuffix || (() => Math.random().toString(36).substring(2, 8))
  const port = injected.port || 7880

  if (!opts.host) {
    console.error('Usage: bench_cli.js --host <peer> [--legs a[,b,c]] [--loss <pct>] [--out <path>]')
    exit(1)
    return
  }

  if (opts.out) {
    resultsDir = opts.out
  }

  const legsList = opts.legs.split(',').map((l) => l.trim())
  const results = {}

  for (const leg of legsList) {
    if (leg === 'a') {
      const baseUrl = `http://${opts.host}:${port}`
      let transport = createHttpTailscaleTransport(baseUrl)

      if (opts.loss > 0) {
        transport = createLossyProxy(transport, {
          lossRate: opts.loss,
          reorderRate: 0,
          seed: 42
        })
      }

      console.log(`Running leg ${leg}...`)
      const legResult = await runLeg(`leg-${leg}`, transport, {
        numPings: 10,
        numStreams: 5,
        streamChunks: 10,
        now
      })
      results[leg] = formatResults(`leg-${leg}`, legResult)
    } else {
      results[leg] = {
        name: `leg-${leg}`,
        unavailable: 'not implemented — blocked on quic-stack/direct-leg-auth decision'
      }
    }
  }

  console.log('\n=== Benchmark Results ===')
  console.table(
    Object.entries(results).map(([leg, result]) => {
      if (result.unavailable) {
        return {
          leg,
          status: result.unavailable
        }
      }
      return {
        leg,
        pingMs: `${result.pings.mean}±${result.pings.stddev}`,
        streamMbps: `${result.streams.mean}±${result.streams.stddev}`,
        errors: result.errors.length,
        reorders: result.reorders
      }
    })
  )

  const timestamp = new Date(now()).toISOString().replace(/[:.]/g, '-')
  const suffix = typeof randomSuffix === 'function' ? randomSuffix() : randomSuffix
  const filename = path.join(resultsDir, `${timestamp}-${suffix}.json`)

  try {
    fs.mkdirSync(resultsDir, { recursive: true })
    fs.writeFileSync(filename, JSON.stringify(results, null, 2))
    console.log(`\nResults written to ${filename}`)
  } catch (err) {
    console.error(`Failed to write results: ${err.message}`)
    exit(1)
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runBenchmark().catch((err) => {
    console.error('Benchmark failed:', err.message)
    process.exit(1)
  })
}
