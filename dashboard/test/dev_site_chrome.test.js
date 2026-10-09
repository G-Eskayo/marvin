import { describe, it, expect } from 'vitest'
import { openDevSite, devSitePrefixes, FOCUS_SCRIPT, DEV_SITE_URL } from '../electron/main/dev_site_chrome.js'

// A fake execFile: answers each call from a queue of [err, stdout, stderr] and records what was asked.
function fakeRun(answers) {
  const calls = []
  const run = (cmd, args, opts, cb) => {
    calls.push({ cmd, args, opts })
    const [err, stdout = '', stderr = ''] = answers.shift() || [new Error('unexpected extra call'), '', '']
    cb(err, stdout, stderr)
  }
  return { run, calls }
}
const installed = () => true
const osaErr = (stderr, code = 1) => [Object.assign(new Error(`Command failed: osascript\n${stderr}`), { code }), '', stderr]

describe('Open dev site in Chrome (marvin#377)', () => {
  it('focuses the existing tab and does not open a new one', async () => {
    const { run, calls } = fakeRun([[null, 'focused\n', '']])
    const result = await openDevSite(DEV_SITE_URL, { run, appExists: installed })
    expect(result).toEqual({ ok: true, action: 'focused' })
    expect(calls).toHaveLength(1)
    expect(calls[0].cmd).toBe('osascript')
  })

  it('opens the site in Chrome when no tab has it', async () => {
    const { run, calls } = fakeRun([[null, 'notfound\n', ''], [null, '', '']])
    const result = await openDevSite(DEV_SITE_URL, { run, appExists: installed })
    expect(result).toEqual({ ok: true, action: 'opened' })
    expect(calls[1]).toMatchObject({ cmd: 'open', args: ['-a', 'Google Chrome', 'http://localhost:8080'] })
  })

  it('opens the site when Chrome is not running (and never launches it just to search)', async () => {
    const { run, calls } = fakeRun([[null, 'notrunning', ''], [null, '', '']])
    expect(await openDevSite(DEV_SITE_URL, { run, appExists: installed })).toEqual({ ok: true, action: 'opened' })
    expect(calls[1].cmd).toBe('open')
    // the search checks "is running" before any tell block, so osascript can't start Chrome itself
    expect(FOCUS_SCRIPT.indexOf('is running')).toBeLessThan(FOCUS_SCRIPT.indexOf('tell application'))
  })

  it('says plainly when Chrome is not installed, without running anything', async () => {
    const { run, calls } = fakeRun([])
    const result = await openDevSite(DEV_SITE_URL, { run, appExists: () => false })
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/Google Chrome isn't installed/)
    expect(calls).toHaveLength(0)
  })

  it('treats osascript or open failing to find the app as not installed too', async () => {
    const a = fakeRun([osaErr("execution error: Can't get application \"Google Chrome\". (-1728)")])
    expect((await openDevSite(DEV_SITE_URL, { run: a.run, appExists: installed })).error).toMatch(/isn't installed/)
    const b = fakeRun([[null, 'notfound', ''], [new Error('open failed'), '', 'Unable to find application named \'Google Chrome\'']])
    expect((await openDevSite(DEV_SITE_URL, { run: b.run, appExists: installed })).error).toMatch(/isn't installed/)
  })

  it('points Gil at the Automation setting when macOS denies control of Chrome (-1743)', async () => {
    const { run, calls } = fakeRun([osaErr('execution error: Not authorized to send Apple events to Google Chrome. (-1743)')])
    const result = await openDevSite(DEV_SITE_URL, { run, appExists: installed })
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/Privacy & Security → Automation/)
    expect(result.error).toMatch(/Google Chrome/)
    // denied means don't fall back to opening a duplicate tab
    expect(calls).toHaveLength(1)
  })

  it('refuses garbage from osascript instead of guessing (no duplicate tab)', async () => {
    for (const out of ['', 'maybe', '{"ok":true}', 'focused extra']) {
      const { run, calls } = fakeRun([[null, out, '']])
      const result = await openDevSite(DEV_SITE_URL, { run, appExists: installed })
      expect(result.ok).toBe(false)
      expect(result.error).toMatch(/unexpected answer/)
      expect(calls).toHaveLength(1)
    }
  })

  it('reports any other osascript failure with its message, trimmed', async () => {
    const { run } = fakeRun([osaErr('x'.repeat(1000))])
    const result = await openDevSite(DEV_SITE_URL, { run, appExists: installed })
    expect(result.ok).toBe(false)
    expect(result.error.length).toBeLessThan(400)
  })

  it('reports a failed open', async () => {
    const { run } = fakeRun([[null, 'notfound', ''], [new Error('boom'), '', 'LSOpenURLsWithRole() failed']])
    const result = await openDevSite(DEV_SITE_URL, { run, appExists: installed })
    expect(result).toEqual({ ok: false, error: expect.stringContaining('LSOpenURLsWithRole') })
  })

  it('passes the URL as an argument, never inside the script, so quotes cannot break or inject', async () => {
    const nasty = 'http://localhost:8080/?q=" & (do shell script "touch /tmp/pwned") & "\'end tell'
    const { run, calls } = fakeRun([[null, 'notfound', ''], [null, '', '']])
    const result = await openDevSite(nasty, { run, appExists: installed })
    expect(result.ok).toBe(true)
    const args = calls[0].args
    // every -e value is the fixed script, untouched by the URL
    const scriptLines = args.filter((_, i) => args[i - 1] === '-e')
    expect(scriptLines.join('\n')).toBe(FOCUS_SCRIPT)
    expect(scriptLines.join('\n')).not.toContain('pwned')
    // the URL's own prefixes are the trailing arguments, verbatim
    expect(args.slice(args.lastIndexOf('-e') + 2)).toEqual(devSitePrefixes(nasty))
    expect(calls[1].args).toEqual(['-a', 'Google Chrome', nasty])
  })

  it('refuses something that is not an http(s) URL without running anything', async () => {
    for (const bad of ['', 'file:///etc/passwd', 'javascript:alert(1)', '-a Safari', null, 42]) {
      const { run, calls } = fakeRun([])
      const result = await openDevSite(bad, { run, appExists: installed })
      expect(result.ok).toBe(false)
      expect(calls).toHaveLength(0)
    }
  })

  it('matches localhost and 127.0.0.1 on the same port, and only that origin', () => {
    expect(devSitePrefixes('http://localhost:8080')).toEqual(['http://localhost:8080', 'http://127.0.0.1:8080'])
    expect(devSitePrefixes('http://127.0.0.1:8080/wp-admin/')).toEqual(['http://localhost:8080', 'http://127.0.0.1:8080'])
    expect(devSitePrefixes('https://example.com/x')).toEqual(['https://example.com'])
  })

  it('the script only accepts a prefix followed by the end, /, ? or # (localhost:80801 is a different site)', () => {
    for (const sep of ['"/"', '"?"', '"#"']) expect(FOCUS_SCRIPT).toContain(sep)
    expect(FOCUS_SCRIPT).toMatch(/on run argv/)
  })

  it('times out rather than hanging the dashboard', async () => {
    const { run, calls } = fakeRun([[null, 'focused', '']])
    await openDevSite(DEV_SITE_URL, { run, appExists: installed })
    expect(calls[0].opts.timeout).toBeGreaterThan(0)
  })
})
