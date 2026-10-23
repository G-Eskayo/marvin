import { writeFileSync, mkdirSync, existsSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { runLeg } from './bench_client.js'
import { createHttpTailscaleTransport } from './transports/http_tailscale.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const RESULTS_DIR = path.join(__dirname, '..', '..', 'dashboard', 'mobile-backend', 'bench-results')

function printUsage() {
  console.error(`Usage: node bench_cli.js --legs <a[,b,c]> --host <peer> [--out <path>]

Options:
  --legs <a[,b,c]>    Comma-separated list of legs to run (a=HTTP/Tailscale, b=QUIC/Tailscale, c=QUIC/Direct)
  --host <peer>       Peer to connect to (e.g., "gils-mac-mini")
  --out <path>        Output file path (default: bench-results/YYYY-MM-DD-HH-MM-SS.json)

Examples:
  node bench_cli.js --legs a --host gils-mac-mini
  node bench_cli.js --legs a,b --host gils-mac-mini --out ./results.json
`)
}

function parseArgs(args) {
  const opts = {}
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--legs' && i + 1 < args.length) {
      opts.legs = args[i + 1].split(',').map(l => l.trim())
      i++
    } else if (args[i] === '--host' && i + 1 < args.length) {
      opts.host = args[i + 1]
      i++
    } else if (args[i] === '--out' && i + 1 < args.length) {
      opts.out = args[i + 1]
      i++
    } else if (args[i] === '--help' || args[i] === '-h') {
      printUsage()
      process.exit(0)
    }
  }
  return opts
}

function validateArgs(opts) {
  if (!opts.legs || opts.legs.length === 0) {
    console.error('ERROR: --legs is required')
    printUsage()
    process.exit(1)
  }

  if (!opts.host) {
    console.error('ERROR: --host is required')
    printUsage()
    process.exit(1)
  }

  const validLegs = ['a', 'b', 'c']
  for (const leg of opts.legs) {
    if (!validLegs.includes(leg)) {
      console.error(`ERROR: Invalid leg '${leg}'. Must be one of: ${validLegs.join(', ')}`)
      process.exit(1)
    }
  }
}

function getOutputPath(outOpt) {
  if (outOpt) {
    return outOpt
  }

  if (!existsSync(RESULTS_DIR)) {
    mkdirSync(RESULTS_DIR, { recursive: true })
  }

  const now = new Date()
  const timestamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
    String(now.getHours()).padStart(2, '0'),
    String(now.getMinutes()).padStart(2, '0'),
    String(now.getSeconds()).padStart(2, '0')
  ].join('-')

  return path.join(RESULTS_DIR, `${timestamp}.json`)
}

function formatTable(results) {
  const headers = ['Leg', 'RTT (ms)', 'TTFB (ms)', 'Throughput (Mbps)', 'Loss (%)', 'Reorders', 'Status']
  const rows = []

  for (const result of results) {
    rows.push([
      result.name,
      result.rtt !== null ? result.rtt.toFixed(1) : 'N/A',
      result.ttfb !== null ? result.ttfb.toFixed(1) : 'N/A',
      result.throughputMbps !== null ? result.throughputMbps.toFixed(2) : 'N/A',
      result.lossPct.toFixed(1),
      result.reorderCount,
      result.unavailable ? `Unavailable: ${result.unavailable}` : 'OK'
    ])
  }

  const colWidths = headers.map((h, i) => {
    const maxRowWidth = Math.max(...rows.map(r => String(r[i]).length))
    return Math.max(h.length, maxRowWidth)
  })

  console.log('\n' + headers.map((h, i) => h.padEnd(colWidths[i])).join(' | '))
  console.log(colWidths.map(w => '-'.repeat(w)).join('-+-'))

  for (const row of rows) {
    console.log(row.map((cell, i) => String(cell).padEnd(colWidths[i])).join(' | '))
  }
  console.log('')
}

async function main() {
  const opts = parseArgs(process.argv.slice(2))
  validateArgs(opts)

  const results = []

  for (const leg of opts.legs) {
    let transport
    let legName = leg

    if (leg === 'a') {
      legName = 'HTTP/Tailscale'
      transport = createHttpTailscaleTransport(opts.host)
    } else if (leg === 'b') {
      legName = 'QUIC/Tailscale'
      console.log(`Skipping leg ${leg} (${legName}): not yet implemented (quic-stack decision pending)`)
      results.push({
        name: legName,
        rtt: null,
        ttfb: null,
        throughputMbps: null,
        lossPct: 0,
        reorderCount: 0,
        reconnects: 0,
        unavailable: 'Not implemented'
      })
      continue
    } else if (leg === 'c') {
      legName = 'QUIC/Direct'
      console.log(`Skipping leg ${leg} (${legName}): not yet implemented (direct-leg-auth decision pending)`)
      results.push({
        name: legName,
        rtt: null,
        ttfb: null,
        throughputMbps: null,
        lossPct: 0,
        reorderCount: 0,
        reconnects: 0,
        unavailable: 'Not implemented'
      })
      continue
    }

    console.log(`Running leg ${leg} (${legName}) against ${opts.host}...`)

    try {
      const result = await runLeg(legName, transport)
      results.push(result)
      console.log(`✓ ${legName}: RTT=${result.rtt}ms, TTFB=${result.ttfb}ms, Throughput=${result.throughputMbps?.toFixed(2)}Mbps`)
    } catch (err) {
      console.error(`✗ ${legName}: ${err.message}`)
      results.push({
        name: legName,
        rtt: null,
        ttfb: null,
        throughputMbps: null,
        lossPct: 0,
        reorderCount: 0,
        reconnects: 0,
        unavailable: err.message
      })
    }
  }

  formatTable(results)

  const outPath = getOutputPath(opts.out)
  writeFileSync(outPath, JSON.stringify({
    timestamp: new Date().toISOString(),
    host: opts.host,
    legs: opts.legs,
    results
  }, null, 2))

  console.log(`Results written to ${outPath}`)
}

main().catch(err => {
  console.error(`FATAL: ${err.message}`)
  process.exit(1)
})
