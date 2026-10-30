// Records the #757 mock-up: every scene in dark and light, at normal motion and with Reduce Motion, frame-exact.
// The page renders each frame as a pure function of t, so this seeks t frame by frame (no real-time capture, no
// dropped frames) and ffmpeg assembles the result: one 2x2 GIF + MP4 per scene (dark/light x normal/reduced).
// Round 2 has no alternatives to record: the owner picked one answer for each.
//
//   node docs/design/merge-animation-757/record.mjs [outDir] [scene ...]
//
// Needs Google Chrome and ffmpeg (both on the Mini). playwright-core comes from dashboard/node_modules.
import { createRequire } from 'module'
import { mkdtempSync, mkdirSync, rmSync, existsSync } from 'fs'
import { execFileSync } from 'child_process'
import { tmpdir } from 'os'
import path from 'path'
import { fileURLToPath, pathToFileURL } from 'url'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(here, '../../../dashboard/package.json'))
const { chromium } = require('playwright-core')

const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const FPS = 25
const W = 860
const H = 540
const out = path.resolve(process.argv[2] || path.join(here, 'media'))
const only = process.argv.slice(3)
const ALL = ['single', 'incoming', 'hold', 'refused', 'detail', 'arrive', 'split', 'queue', 'reverted', 'scrolled', 'away', 'swipe']
mkdirSync(out, { recursive: true })
const work = mkdtempSync(path.join(tmpdir(), 'merge-757-'))
const ff = (...args) => execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { stdio: 'inherit' })

const browser = await chromium.launch({ executablePath: CHROME, headless: true })
try {
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 })

  // One variant → an MP4 of its frames. Returns [file, seconds].
  async function take(name, o) {
    const q = new URLSearchParams({ record: '1', theme: 'dark', reduced: '0', ...o })
    await page.goto(pathToFileURL(path.join(here, 'index.html')).href + '?' + q)
    await page.waitForFunction(() => window.__proto?.ready)
    const total = await page.evaluate(() => window.__proto.total)
    const dir = path.join(work, name)
    mkdirSync(dir, { recursive: true })
    const frames = Math.ceil((total / 1000) * FPS) + 1
    const stage = await page.$('#stage')
    for (let i = 0; i < frames; i++) {
      await page.evaluate((t) => window.__proto.seek(t), Math.min(total, (i * 1000) / FPS))
      await stage.screenshot({ path: path.join(dir, `f${String(i).padStart(4, '0')}.png`) })
    }
    const mp4 = path.join(work, `${name}.mp4`)
    ff('-framerate', String(FPS), '-i', path.join(dir, 'f%04d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', mp4)
    return [mp4, frames / FPS]
  }

  function gif(src, dest, width) {
    const pal = path.join(work, 'palette.png')
    ff('-i', src, '-vf', `fps=${FPS},scale=${width}:-1:flags=lanczos,palettegen=stats_mode=diff`, pal)
    ff('-i', src, '-i', pal, '-lavfi', `fps=${FPS},scale=${width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`, dest)
  }

  for (const scene of only.length ? only : ALL) {
    const parts = []
    for (const theme of ['dark', 'light']) for (const reduced of ['0', '1']) parts.push(await take(`${scene}-${theme}-${reduced}`, { scene, theme, reduced }))
    const longest = Math.max(...parts.map(([, s]) => s))
    // 2x2: dark normal | dark reduced / light normal | light reduced. Shorter ones hold their last frame.
    const order = [parts[0], parts[1], parts[2], parts[3]]
    const inputs = order.flatMap(([f]) => ['-i', f])
    const pads = order.map((_, i) => `[${i}]tpad=stop_mode=clone:stop_duration=${longest}[p${i}]`).join(';')
    const grid = path.join(out, `${scene}.mp4`)
    ff(...inputs, '-filter_complex', `${pads};[p0][p1][p2][p3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0:fill=black[v]`, '-map', '[v]', '-t', String(longest),
      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', grid)
    gif(grid, path.join(out, `${scene}.gif`), 1200)
    console.log(`${scene}: ${longest.toFixed(1)} s`)
  }
} finally {
  await browser.close()
  if (existsSync(work)) rmSync(work, { recursive: true, force: true })
}
