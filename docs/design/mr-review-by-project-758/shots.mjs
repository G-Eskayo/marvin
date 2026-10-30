// Screenshots of every scene the PR shows, from headless Chrome with its own throwaway profile.
//   node docs/design/mr-review-by-project-758/shots.mjs   → shots/*.png (local only)
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
const HERE = dirname(fileURLToPath(import.meta.url))
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
export const SCENES = [
  ['01-by-project', 'view=project', 1100, 1500],
  ['02-all-today', 'view=all', 1100, 1500],
  ['03-all-new-order', 'view=all&sortall=1', 1100, 1500],
  ['04-everything-open', 'view=project&collapse=open', 1100, 1900],
  ['05-empty-shown', 'view=project&empty=show&closed=1', 1100, 1500],
  ['06-edge-cases', 'view=project&examples=1&collapse=big', 1100, 1900],
  ['07-big-group-open', 'view=project&examples=1&collapse=open', 1100, 3400],
  ['08-focus-one-project', 'view=project&tap=focus&focus=marvin', 1100, 1100],
  ['09-catalog-names', 'view=project&names=catalog', 1100, 1500],
  ['10-narrow', 'view=project&collapse=open', 860, 2100]
]
const only = process.argv.slice(2)
mkdirSync(join(HERE, 'shots'), { recursive: true })
const profile = mkdtempSync(join(tmpdir(), 'mr758-chrome-'))
try {
  for (const [name, hash, w, hgt] of SCENES) {
    if (only.length && !only.includes(name)) continue
    const url = `${pathToFileURL(join(HERE, 'index.html')).href}#${hash}`
    execFileSync(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--user-data-dir=${profile}`, '--force-device-scale-factor=2',
      `--window-size=${w},${hgt}`, `--screenshot=${join(HERE, 'shots', `${name}.png`)}`, url], { stdio: 'ignore', timeout: 60000 })
    console.log(name)
  }
} finally {
  rmSync(profile, { recursive: true, force: true })
}
