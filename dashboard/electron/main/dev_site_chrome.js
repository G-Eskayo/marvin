import { execFile } from 'child_process'
import { existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// The Portfolio tab's "Open dev site" button (marvin#377): takes Gil to the dev site in Google Chrome, reusing the
// tab he already has open instead of piling up new ones. Desktop only, same shape as marvin_session.js: the
// renderer asks over IPC, this does the work and answers { ok, action } or { ok: false, error }.
export const DEV_SITE_URL = 'http://localhost:8080'
const CHROME = 'Google Chrome'
const CHROME_PATHS = [
  path.join('/Applications', `${CHROME}.app`),
  path.join(homedir(), 'Applications', `${CHROME}.app`)
]

// Fixed script; the prefixes to look for arrive as argv, so nothing in a URL can change what runs. "is running" is
// checked before any tell block, because telling Chrome would launch it just to search an empty window list. A
// prefix only counts when the URL ends there or continues with / ? # (localhost:80801 is a different site).
export const FOCUS_SCRIPT = [
  'on run argv',
  `  if application "${CHROME}" is not running then return "notrunning"`,
  `  tell application "${CHROME}"`,
  '    repeat with w in windows',
  '      set i to 0',
  '      repeat with t in tabs of w',
  '        set i to i + 1',
  '        set u to (URL of t) as text',
  '        repeat with p in argv',
  '          set p to p as text',
  '          if u is p or u starts with (p & "/") or u starts with (p & "?") or u starts with (p & "#") then',
  '            set active tab index of w to i',
  '            try',
  '              if minimized of w then set minimized of w to false',
  '            end try',
  '            set index of w to 1',
  '            activate',
  '            return "focused"',
  '          end if',
  '        end repeat',
  '      end repeat',
  '    end repeat',
  '  end tell',
  '  return "notfound"',
  'end run'
].join('\n')

// The origins that count as "the dev site already open": localhost and 127.0.0.1 are the same server, so a tab on
// either is reused. Any other host is matched only on its own origin.
export function devSitePrefixes(url) {
  const u = new URL(url)
  const local = ['localhost', '127.0.0.1']
  if (!local.includes(u.hostname)) return [u.origin]
  const port = u.port ? `:${u.port}` : ''
  return local.map((h) => `${u.protocol}//${h}${port}`)
}

const NOT_INSTALLED = `Google Chrome isn't installed (looked in ${CHROME_PATHS.join(' and ')}). Install it, or open ${DEV_SITE_URL} yourself.`
const DENIED =
  'macOS stopped the dashboard from controlling Google Chrome. Allow it in System Settings → Privacy & Security → ' +
  'Automation (turn on Google Chrome under MARVIN Metrics), then press the button again.'

function failure(err, stderr) {
  const text = `${stderr || ''} ${err?.message || ''}`
  if (/-1743\b|Not authori[sz]ed to send Apple events/i.test(text)) return DENIED
  if (/-1728\b|-2740\b|-10814\b|Can.t get application|Unable to find application/i.test(text)) return NOT_INSTALLED
  return (String(stderr || '').trim() || err?.message || 'Chrome gave no answer').slice(0, 300)
}

export function openDevSite(url = DEV_SITE_URL, { run = execFile, appExists = () => CHROME_PATHS.some((p) => existsSync(p)) } = {}) {
  let prefixes
  try {
    if (typeof url !== 'string' || !/^https?:$/.test(new URL(url).protocol)) throw new Error()
    prefixes = devSitePrefixes(url)
  } catch {
    return Promise.resolve({ ok: false, error: `"${url}" isn't a web address` })
  }
  if (!appExists()) return Promise.resolve({ ok: false, error: NOT_INSTALLED })

  const scriptArgs = FOCUS_SCRIPT.split('\n').flatMap((line) => ['-e', line])
  return new Promise((resolve) => {
    run('osascript', [...scriptArgs, ...prefixes], { timeout: 15000 }, (err, stdout, stderr) => {
      if (err) return resolve({ ok: false, error: failure(err, stderr) })
      const answer = String(stdout).trim()
      if (answer === 'focused') return resolve({ ok: true, action: 'focused' })
      if (answer !== 'notfound' && answer !== 'notrunning') {
        return resolve({ ok: false, error: `Chrome gave an unexpected answer: ${JSON.stringify(answer.slice(0, 80))}` })
      }
      run('open', ['-a', CHROME, url], { timeout: 15000 }, (openErr, _out, openStderr) => {
        if (openErr) return resolve({ ok: false, error: failure(openErr, openStderr) })
        resolve({ ok: true, action: 'opened' })
      })
    })
  })
}
