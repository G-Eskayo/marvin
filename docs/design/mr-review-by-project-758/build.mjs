// Builds the prototype: reads the live PRs (snapshot.mjs) unless --no-snapshot, and bundles proto.js with the real
// dashboard modules into bundle.local.js. Then open index.html in Chrome. Both outputs are local-only (.gitignore).
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const HERE = dirname(fileURLToPath(import.meta.url))
const esbuild = join(HERE, '../../../dashboard/node_modules/.bin/esbuild')
if (!process.argv.includes('--no-snapshot')) execFileSync(process.execPath, [join(HERE, 'snapshot.mjs')], { stdio: 'inherit' })
execFileSync(esbuild, [join(HERE, 'proto.js'), '--bundle', '--format=iife', `--outfile=${join(HERE, 'bundle.local.js')}`, '--log-level=warning'], { stdio: 'inherit' })
console.log(`open ${join(HERE, 'index.html')}`)
