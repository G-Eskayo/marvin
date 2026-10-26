import { execFile } from 'child_process'
import { existsSync } from 'fs'
import { safeExternalUrl } from '../../src/lib/pdf_nav.js'
import { CHROME, CHROME_PATHS } from './dev_site_chrome.js'

// Links clicked in the dashboard (MR Review's "open on GitHub", ticket and doc links). Web links go to Google Chrome,
// where Gil is signed in to GitHub, so a PR opens ready to merge; the Mac's default browser may be another one with no
// sign-in. No Chrome, or Chrome fails: the default browser. Mail links: the mail app. Anything else (file:,
// javascript:, custom schemes) never opens. The URL reaches `open` as one argv entry after -a, so it can't add flags.
export function openLink(url, { run = execFile, appExists = () => CHROME_PATHS.some((p) => existsSync(p)), openExternal } = {}) {
  const safe = safeExternalUrl(url)
  if (!safe) return Promise.resolve({ ok: false, error: 'Only web and mail links open from the dashboard' })
  const fallback = () => openExternal(safe).then(() => ({ ok: true, via: 'default' }))
  if (safe.startsWith('mailto:') || !appExists()) return fallback()
  return new Promise((resolve) => {
    run('open', ['-a', CHROME, safe], { timeout: 15000 }, (err) => resolve(err ? fallback() : { ok: true, via: 'chrome' }))
  })
}

// target="_blank" and window.open: without this Electron opens a bare window of its own, with an empty cookie jar
// (never signed in) and the dashboard's preload. Every such link goes to the browser instead.
export function windowOpenHandler(open) {
  return ({ url }) => {
    try {
      Promise.resolve(open(url)).catch(() => {})
    } catch {}
    return { action: 'deny' }
  }
}
