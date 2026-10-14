// Screenshot the built dashboard for PR evidence (marvin#421). Playwright's chromium.launch rejects Electron's app-dir
// argument ("Arguments can not specify page to be opened"), so every UI PR went without screenshots and the merge gate
// refused it (NO_UI_EVIDENCE). Instead: start Electron ourselves with a free remote-debugging port, attach with
// chromium.connectOverCDP, shoot the real app window, and always clean up (close CDP, SIGTERM, SIGKILL after 1.5 s).
// Never throws: returns { ok, path } or { ok: false, error } with a plain reason. Everything is injectable for tests.
import net from 'node:net'
import { selectContentPage } from './screenshot_capture.js'

export function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.unref()
    srv.once('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

export async function captureViaCdp({
  electronBin, appDir, env, outputPath, chromium, spawn,
  findPort = freePort, attachTimeoutMs = 30_000, windowTimeoutMs = 10_000, pollMs = 250, viewport = null
}) {
  let proc
  let port
  try {
    port = await findPort()
    proc = spawn(electronBin, [appDir, '--no-sandbox', `--remote-debugging-port=${port}`], { env, stdio: 'ignore' })
  } catch (err) {
    return { ok: false, error: `could not start Electron: ${err?.message || err}` }
  }
  let exited = null
  proc.on?.('exit', (code) => { exited = code ?? 'signal' })
  let browser = null
  try {
    const attachBy = Date.now() + attachTimeoutMs
    while (!browser) {
      if (exited !== null) return { ok: false, error: `Electron exited (code ${exited}) before the window opened` }
      try {
        browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`)
      } catch {
        if (exited !== null) return { ok: false, error: `Electron exited (code ${exited}) before the window opened` }
        if (Date.now() > attachBy) return { ok: false, error: `could not attach to Electron on port ${port} within ${Math.round(attachTimeoutMs / 1000)} s` }
        await sleep(pollMs)
      }
    }
    let page = null
    const windowBy = Date.now() + windowTimeoutMs
    while (!page) {
      const contexts = browser.contexts()
      page = contexts.length ? selectContentPage(contexts[0].pages()) : null
      if (page) break
      if (Date.now() > windowBy) return { ok: false, error: `no app window appeared within ${Math.round(windowTimeoutMs / 1000)} s` }
      await sleep(pollMs)
    }
    await page.waitForLoadState('domcontentloaded')
    if (viewport) await page.setViewportSize(viewport)
    await page.screenshot({ path: outputPath })
    return { ok: true, path: outputPath }
  } catch (err) {
    return { ok: false, error: err?.message || String(err) }
  } finally {
    if (browser) await browser.close().catch(() => {})
    if (proc && exited === null && proc.exitCode === null) {
      proc.kill('SIGTERM')
      const goneBy = Date.now() + 1500
      while (exited === null && proc.exitCode === null && Date.now() < goneBy) await sleep(Math.min(pollMs, 50))
      if (exited === null && proc.exitCode === null) proc.kill('SIGKILL')
    }
  }
}
