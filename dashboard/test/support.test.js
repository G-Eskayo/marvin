import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, existsSync, readFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { supportRole, readSupportState, badgeCount, supportArgs, runSupport } from '../electron/main/support.js'

const REPO = 'helped-person/marvin-support'

describe('support role from the instance (ADR 0073)', () => {
  it('is off unless the instance says otherwise', () => {
    for (const config of [{}, null, { support: 'yes' }, { support: [] }, { support: { repo: 7 } }, { support: { repo: '../x' } }]) {
      expect(supportRole(config), JSON.stringify(config)).toEqual({ role: null, repos: [] })
    }
  })

  it('a helped install has its one repo; a helper watches several and drops bad entries', () => {
    expect(supportRole({ support: { repo: REPO, helper: 'someone' } })).toEqual({ role: 'helped', repos: [REPO], autoApply: false })
    expect(supportRole({ support: { repo: REPO, auto_apply: true } }).autoApply).toBe(true)
    expect(supportRole({ support: { repo: REPO, auto_apply: 'yes' } }).autoApply).toBe(false) // only a real true turns it on
    expect(supportRole({ support: { watch: [REPO, 'a/b', 'nope', 3] } })).toEqual({ role: 'helper', repos: [REPO, 'a/b'] })
  })
})

describe('the saved state the tab renders from', () => {
  const write = (data) => {
    const file = path.join(mkdtempSync(path.join(tmpdir(), 'support-')), 'state.json')
    writeFileSync(file, typeof data === 'string' ? data : JSON.stringify(data))
    return file
  }

  it('counts only open requests, and recounts rather than trusting the file', () => {
    const file = write({
      syncedAt: 'x',
      counts: { 'needs-you': 99 },
      requests: [
        { repo: REPO, number: 1, state: 'needs-you', open: true },
        { repo: REPO, number: 2, state: 'needs-you', open: false },
        { repo: REPO, number: 3, state: 'answered', open: true },
        { repo: REPO, number: 4, state: 'escalated-to-mars', open: true }
      ]
    })
    const s = readSupportState(file)
    expect(s.counts['needs-you']).toBe(1)
    expect(s.requests.map((r) => r.number)).toEqual([1, 2, 3])
    expect(badgeCount('helper', s)).toBe(1)
    expect(badgeCount('helped', s)).toBe(1)
    expect(badgeCount(null, s)).toBe(0)
  })

  it('a missing or broken file renders as nothing waiting, never a crash', () => {
    for (const file of ['/nonexistent/state.json', write('{half'), write('[1,2]')]) {
      const s = readSupportState(file)
      expect(s.requests).toEqual([])
      expect(badgeCount('helper', s)).toBe(0)
    }
  })
})

describe('support actions', () => {
  it('refuses a repo that is not this install’s, a bad number or an unknown action, without running anything', async () => {
    const cases = [
      ['reply', { repo: 'someone/else', number: 1, text: 'hi' }],
      ['resolve', { repo: REPO, number: '1; rm -rf ~' }],
      ['resolve', { repo: REPO, number: -2 }],
      ['delete-everything', { repo: REPO, number: 1 }]
    ]
    for (const [cmd, req] of cases) {
      let ran = false
      const result = await runSupport(cmd, req, { repos: [REPO], run: () => { ran = true } })
      expect(result.ok, cmd).toBe(false)
      expect(ran, cmd).toBe(false)
    }
  })

  it('refuses an empty request or reply', async () => {
    let ran = false
    const run = () => { ran = true }
    expect((await runSupport('file', { text: '   ' }, { run })).ok).toBe(false)
    expect((await runSupport('reply', { repo: REPO, number: 1, text: '' }, { repos: [REPO], run })).ok).toBe(false)
    expect(ran).toBe(false)
  })

  it('passes text through a private file that is gone afterwards, never on the command line', async () => {
    let seen
    const text = 'Dashboard is blank; `rm -rf ~` $(whoami)'
    const result = await runSupport('file', { text }, {
      run: (_py, args, _o, cb) => {
        const file = args[args.indexOf('--text-file') + 1]
        seen = { args, file, body: readFileSync(file, 'utf8') }
        cb(null, '{"ok": true, "number": 4}\n', '')
      }
    })
    expect(result).toEqual({ ok: true, number: 4 })
    expect(seen.body).toBe(text)
    expect(seen.args.join(' ')).not.toContain('rm -rf')
    expect(existsSync(seen.file)).toBe(false)
  })

  it('builds the reply call for a known repo, and reports a clear error when support.py says nothing', async () => {
    expect(supportArgs('resolve', { repo: REPO, number: '3' }, [REPO]).slice(1)).toEqual(['resolve', REPO, '3'])
    const bad = await runSupport('thread', { repo: REPO, number: 3 }, { repos: [REPO], run: (_p, _a, _o, cb) => cb(new Error('x'), '', 'Traceback') })
    expect(bad).toEqual({ ok: false, error: 'Traceback' })
  })
})

import { supportNotices } from '../electron/main/support.js'

describe('notices (ADR 0073 amendment)', () => {
  const S = (...requests) => ({ requests })
  const r = (number, state, open = true, title = `Request ${number}`) => ({ repo: REPO, number, state, open, title })

  it('the helped person hears when an answer arrives, once', () => {
    const before = S(r(1, 'helper-trying'))
    const after = S(r(1, 'answered'))
    expect(supportNotices(before, after, 'helped')).toEqual([{ repo: REPO, number: 1, title: 'MARVIN support: a reply is waiting', body: 'Request 1' }])
    expect(supportNotices(after, after, 'helped')).toEqual([])
  })

  it('the helper hears only about needs-you, not about what MARVIN handled', () => {
    const before = S(r(1, 'helper-trying'), r(2, 'helper-trying'))
    const after = S(r(1, 'needs-you'), r(2, 'answered'))
    expect(supportNotices(before, after, 'helper').map((n) => n.number)).toEqual([1])
  })

  it('nothing at startup, nothing for closed requests, nothing without a role', () => {
    expect(supportNotices(null, S(r(1, 'answered')), 'helped')).toEqual([])
    expect(supportNotices(S(), S(r(1, 'answered', false)), 'helped')).toEqual([])
    expect(supportNotices(S(), S(r(1, 'answered')), null)).toEqual([])
  })

  it('a new request already answered counts as new', () => {
    expect(supportNotices(S(), S(r(7, 'answered')), 'helped').map((n) => n.number)).toEqual([7])
  })

  it('the notice carries the title only, cut short', () => {
    const [n] = supportNotices(S(), S(r(1, 'answered', true, 'x'.repeat(500))), 'helped')
    expect(n.body.length).toBe(120)
  })
})

describe('reply with a check, and follow-ups', () => {
  it('passes a check with a reply, and refuses an overlong one', () => {
    expect(supportArgs('reply', { repo: REPO, number: 1, file: '/f', check: 'gh auth status' }, [REPO]).slice(1))
      .toEqual(['reply', REPO, '1', '--body-file', '/f', '--check', 'gh auth status'])
    expect(() => supportArgs('reply', { repo: REPO, number: 1, file: '/f', check: 'x'.repeat(301) }, [REPO])).toThrow()
  })

  it('a follow-up is text through a file, for this install’s own repo only', () => {
    expect(supportArgs('followup', { repo: REPO, number: 2, file: '/f' }, [REPO]).slice(1)).toEqual(['followup', REPO, '2', '--body-file', '/f'])
    expect(() => supportArgs('followup', { repo: 'x/y', number: 2, file: '/f' }, [REPO])).toThrow()
  })
})

describe('idea notices and filing', () => {
  const r = (number, state, open = true) => ({ repo: REPO, number, state, open, title: `Idea ${number}` })
  it('the helped person hears when an idea becomes a ticket and when it is built, never the helper', () => {
    expect(supportNotices({ requests: [r(1, 'idea-proposal')] }, { requests: [r(1, 'idea-ticket')] }, 'helped').map((n) => n.title))
      .toEqual(['MARVIN: your idea is now a ticket'])
    expect(supportNotices({ requests: [r(1, 'idea-ticket')] }, { requests: [r(1, 'idea-shipped', false)] }, 'helped').map((n) => n.title))
      .toEqual(['MARVIN: your idea was built'])
    expect(supportNotices({ requests: [] }, { requests: [r(1, 'idea-new')] }, 'helper')).toEqual([])
  })

  it('an idea is text through a file, and an empty one is refused', async () => {
    let ran = false
    expect((await runSupport('idea', { text: ' ' }, { run: () => { ran = true } })).ok).toBe(false)
    expect(ran).toBe(false)
    expect(supportArgs('idea', { file: '/f' }).slice(1)).toEqual(['idea', '--text-file', '/f'])
  })
})

describe('rewriting a reply for its reader', () => {
  it('adapt is text through a file, for this install’s own repo only', () => {
    expect(supportArgs('adapt', { repo: REPO, number: 3, file: '/f' }, [REPO]).slice(1)).toEqual(['adapt', REPO, '3', '--body-file', '/f'])
    expect(() => supportArgs('adapt', { repo: 'x/y', number: 3, file: '/f' }, [REPO])).toThrow()
  })
})

describe('headless on the helped Mac', () => {
  const r = (number, state, open = true) => ({ repo: REPO, number, state, open, title: `R ${number}` })
  it('the helped person hears when MARVIN fixed something for them', () => {
    expect(supportNotices({ requests: [r(1, 'answered')] }, { requests: [r(1, 'verified', false)] }, 'helped').map((n) => n.title))
      .toEqual(['MARVIN fixed it for you'])
  })
  it('the switch and "got it" are plain, checked calls', () => {
    expect(supportArgs('auto-apply', { on: true }).slice(1)).toEqual(['auto-apply', 'on'])
    expect(supportArgs('auto-apply', { on: 'yes' }).slice(1)).toEqual(['auto-apply', 'off'])
    expect(supportArgs('got-it', { repo: REPO, number: 2 }, [REPO]).slice(1)).toEqual(['got-it', REPO, '2'])
    expect(() => supportArgs('got-it', { repo: 'x/y', number: 2 }, [REPO])).toThrow()
  })
})
