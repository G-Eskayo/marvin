import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'
import { readGoals } from '../electron/main/profiles.js'
import { buildProgressRows, loopingTickets } from '../electron/main/project_progress.js'
import { arrowOf, statusLabel, shortGoal, clip, isActive } from '../src/lib/project_goals.js'
import { GoalHeader, ProjectsProgress } from '../src/components/ProjectGoals.jsx'

// Project goals (Gil, 2026-10-26): the goal, signals and status in each private profile, shown at the top of each
// board and as one row per project in Activity. Tests try to break it: bad, missing, huge and hostile profiles.

const withDir = (fn) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'goals-'))
  try {
    return fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}
const put = (dir, name, obj) => writeFileSync(path.join(dir, name), typeof obj === 'string' ? obj : JSON.stringify(obj))
const SEAL = {
  repo: 'G-Eskayo/clarity-captions',
  goal: 'Any hard-of-hearing person can rely on Seal Speak: iPhone first, then Android.',
  signals: [
    { name: 'testers and users', better: 'up' },
    { name: 'crash-free days', better: 'up' },
    { name: 'App Store rating', better: 'up' }
  ],
  goal_set: '2026-10-26 (Gil, in chat)'
}

describe('readGoals (the profiles loader, ADR 0071 instance dir)', () => {
  it('reads goal, signals and status from each profile', () =>
    withDir((dir) => {
      put(dir, 'clarity-captions.json', SEAL)
      put(dir, 'killer-sudoku.json', { repo: 'G-Eskayo/killer-sudoku', status: 'parked', goal: null, signals: [] })
      expect(readGoals(dir)).toEqual([
        { repo: 'G-Eskayo/clarity-captions', goal: SEAL.goal, signals: SEAL.signals, status: 'active' },
        { repo: 'G-Eskayo/killer-sudoku', goal: null, signals: [], status: 'parked' }
      ])
    }))

  it('a missing instance dir (public engine install) is no goals, not an error', () => {
    expect(readGoals(path.join(tmpdir(), 'no-such-instance-' + process.pid, 'config', 'projects'))).toEqual([])
  })

  it('one malformed profile does not hide the others', () =>
    withDir((dir) => {
      put(dir, 'bad.json', '{"repo": "o/bad", "goal": ')
      put(dir, 'arr.json', '[1,2,3]')
      put(dir, 'ok.json', { repo: 'o/ok', goal: 'Ship it' })
      expect(readGoals(dir).map((g) => g.repo)).toEqual(['o/ok'])
    }))

  it('wrong-shaped fields become safe values: no goal, no bad signals, unknown direction has no arrow', () =>
    withDir((dir) => {
      put(dir, 'a.json', {
        repo: 'o/a',
        goal: { html: '<b>x</b>' },
        signals: [{ name: 'good', better: 'down' }, { name: 'sideways', better: 'left' }, { better: 'up' }, 'text', null, { name: '   ' }, { name: 7 }],
        status: 42
      })
      put(dir, 'b.json', { repo: 'o/b', goal: '   ', signals: 'not a list' })
      put(dir, 'c.json', { repo: 'o/c' })
      expect(readGoals(dir)).toEqual([
        { repo: 'o/a', goal: null, signals: [{ name: 'good', better: 'down' }, { name: 'sideways', better: null }], status: 'active' },
        { repo: 'o/b', goal: null, signals: [], status: 'active' },
        { repo: 'o/c', goal: null, signals: [], status: 'active' }
      ])
    }))

  it('a huge goal or signal list is bounded, so one profile cannot flood the screen or the IPC message', () =>
    withDir((dir) => {
      const many = Array.from({ length: 500 }, (_, i) => ({ name: `s${i}`.repeat(50), better: 'up' }))
      put(dir, 'a.json', { repo: 'o/a', goal: 'x'.repeat(200_000), signals: many })
      const [g] = readGoals(dir)
      expect(g.goal.length).toBeLessThanOrEqual(1000)
      expect(g.signals.length).toBeLessThanOrEqual(12)
      for (const s of g.signals) expect(s.name.length).toBeLessThanOrEqual(80)
    }))

  it('keeps the status words Gil uses and treats a missing or unknown status as active', () =>
    withDir((dir) => {
      put(dir, 'a.json', { repo: 'o/a', status: 'done (handed off)' })
      put(dir, 'b.json', { repo: 'o/b', status: 'archived' })
      put(dir, 'c.json', { repo: 'o/c', status: 'paused?' })
      expect(readGoals(dir).map((g) => g.status)).toEqual(['done (handed off)', 'archived', 'active'])
    }))
})

describe('display rules', () => {
  it('arrows: up and down only', () => {
    expect(arrowOf('up')).toBe('↑')
    expect(arrowOf('down')).toBe('↓')
    expect(arrowOf('left')).toBe('')
    expect(arrowOf(undefined)).toBe('')
  })
  it('status labels: Parked / Done / Archived, and nothing for active', () => {
    expect(statusLabel('parked')).toBe('Parked')
    expect(statusLabel('done (handed off)')).toBe('Done')
    expect(statusLabel('archived')).toBe('Archived')
    expect(statusLabel('active')).toBe(null)
    expect(isActive({ status: 'active' })).toBe(true)
    expect(isActive({ status: 'parked' })).toBe(false)
  })
  it('the short goal is the first clause, truncated', () => {
    expect(shortGoal(SEAL.goal)).toBe('Any hard-of-hearing person can rely on…')
    expect(shortGoal('Lands interviews.')).toBe('Lands interviews')
    expect(shortGoal('Money on autopilot: Gil always knows')).toBe('Money on autopilot')
    expect(shortGoal(null)).toBe(null)
    expect(shortGoal('x'.repeat(5000)).length).toBeLessThanOrEqual(41)
  })
  it('clip leaves short text alone and cuts long text with an ellipsis', () => {
    expect(clip('abc', 5)).toBe('abc')
    expect(clip('abcdef', 5)).toBe('abcd…')
  })
})

describe('GoalHeader (top of each project board)', () => {
  it('shows the goal line and one chip per signal, each "—" with "not measured yet"', () => {
    const html = renderToStaticMarkup(<GoalHeader goal={{ ...SEAL, status: 'active' }} />)
    expect(html).toContain('Goal:')
    expect(html).toContain(SEAL.goal)
    expect(html).toContain('testers and users ↑')
    expect(html).toContain('crash-free days ↑')
    expect(html).toContain('App Store rating ↑')
    expect(html.match(/title="not measured yet"/g)).toHaveLength(3)
    expect(html.match(/—/g)).toHaveLength(3)
    expect(html).toContain('flex-wrap') // chips wrap at narrow width instead of overflowing
  })
  it('a project with no goal shows its status instead', () => {
    expect(renderToStaticMarkup(<GoalHeader goal={{ repo: 'o/a', goal: null, signals: [], status: 'parked' }} />)).toContain('Parked')
    expect(renderToStaticMarkup(<GoalHeader goal={{ repo: 'o/a', goal: null, signals: [], status: 'done (handed off)' }} />)).toContain('Done')
    const archived = renderToStaticMarkup(<GoalHeader goal={{ repo: 'o/a', goal: null, signals: [], status: 'archived' }} />)
    expect(archived).toContain('Archived')
    expect(archived).not.toContain('Goal:')
  })
  it('nothing at all for no profile, or an active project with no goal', () => {
    expect(renderToStaticMarkup(<GoalHeader goal={null} />)).toBe('')
    expect(renderToStaticMarkup(<GoalHeader goal={{ repo: 'o/a', goal: null, signals: [], status: 'active' }} />)).toBe('')
  })
  it('empty signals: the goal line alone, no empty chip row', () => {
    const html = renderToStaticMarkup(<GoalHeader goal={{ repo: 'o/a', goal: 'Ship it', signals: [], status: 'active' }} />)
    expect(html).toContain('Ship it')
    expect(html).not.toContain('not measured yet')
  })
  it('HTML or script in the goal or a signal renders as text, never as HTML', () => {
    const evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    const html = renderToStaticMarkup(<GoalHeader goal={{ repo: 'o/a', goal: evil, signals: [{ name: evil, better: 'up' }], status: 'active' }} />)
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;script&gt;')
  })
  it('an unknown direction shows the signal name with no arrow', () => {
    const html = renderToStaticMarkup(<GoalHeader goal={{ repo: 'o/a', goal: 'g', signals: [{ name: 'sideways', better: null }], status: 'active' }} />)
    expect(html).toContain('sideways')
    expect(html).not.toMatch(/sideways [↑↓]/)
  })
})

const NOW = Date.parse('2026-10-26T12:00:00Z')
const ago = (h) => new Date(NOW - h * 3600_000).toISOString()

describe('buildProgressRows (one row per project in Activity)', () => {
  const goals = [
    { repo: 'G-Eskayo/clarity-captions', goal: SEAL.goal, signals: SEAL.signals, status: 'active' },
    { repo: 'G-Eskayo/marvin', goal: 'Work gets done without Gil chasing it, cheaply.', signals: [], status: 'active' },
    { repo: 'G-Eskayo/killer-sudoku', goal: null, signals: [], status: 'parked' },
    { repo: 'G-Eskayo/slopecycle', goal: null, signals: [], status: 'done (handed off)' },
    { repo: 'G-Eskayo/no-board', goal: 'Has no board', signals: [], status: 'active' }
  ]
  const boards = [
    { repo: 'G-Eskayo/marvin', name: 'marvin' },
    { repo: 'G-Eskayo/clarity-captions', name: 'Seal Speak' },
    { repo: 'G-Eskayo/killer-sudoku', name: 'killer-sudoku' }
  ]

  it('active projects get rows in board order; parked and done collapse into the rest', () => {
    const { active, rest } = buildProgressRows({ goals, boards, now: NOW })
    expect(active.map((r) => r.name)).toEqual(['marvin', 'Seal Speak', 'no-board'])
    expect(rest.map((r) => r.repo)).toEqual(['G-Eskayo/killer-sudoku', 'G-Eskayo/slopecycle'])
    expect(active.find((r) => r.repo === 'G-Eskayo/no-board').hasBoard).toBe(false)
    expect(active.find((r) => r.repo === 'G-Eskayo/marvin').hasBoard).toBe(true)
  })

  it('moving counts only that repo\'s PRs merged in the last 7 days, once each', () => {
    const merged = [
      { url: 'https://github.com/G-Eskayo/clarity-captions/pull/1', at: ago(1) },
      { url: 'https://github.com/G-Eskayo/clarity-captions/pull/1', at: ago(1) }, // the same merge from two sources
      { url: 'https://github.com/G-Eskayo/clarity-captions/pull/2', at: ago(24 * 6) },
      { url: 'https://github.com/G-Eskayo/clarity-captions/pull/3', at: ago(24 * 8) }, // too old
      { url: 'https://github.com/G-Eskayo/clarity-captions/pull/4', at: 'not a date' },
      { url: 'https://github.com/G-Eskayo/clarity-captions-2/pull/5', at: ago(1) }, // a different repo with a prefix name
      { url: 'not a url', at: ago(1) },
      null
    ]
    const { active } = buildProgressRows({ goals, boards, merged, now: NOW })
    expect(active.find((r) => r.name === 'Seal Speak').mergedWeek).toBe(2)
    expect(active.find((r) => r.name === 'marvin').mergedWeek).toBe(0)
  })

  it('stuck counts held, needs-you and looping tickets of that repo only', () => {
    const issuesByRepo = {
      'G-Eskayo/marvin': [
        { number: 1, state: 'OPEN', labels: [{ name: 'hold' }] },
        { number: 2, state: 'CLOSED', labels: [{ name: 'hold' }] }, // closed: not stuck
        { number: 3, state: 'OPEN', labels: [] },
        { number: 4, state: 'CLOSED', labels: [] }
      ]
    }
    const plan = (h) => ({ stage: 'planning', status: 'started', timestamp: ago(h) })
    const stagesByRepo = {
      'G-Eskayo/marvin': { 3: [plan(1), plan(5), plan(20)], 4: [plan(1), plan(2), plan(3)] }, // 4 is closed
      'G-Eskayo/clarity-captions': { 9: [plan(1), plan(30), plan(40)] } // only one in 24 h
    }
    const overview = { 'G-Eskayo/marvin': { needsYou: 2 } }
    const { active } = buildProgressRows({ goals, boards, issuesByRepo, stagesByRepo, overview, now: NOW })
    expect(active.find((r) => r.name === 'marvin').stuck).toEqual({ held: 1, needsYou: 2, looping: 1, total: 4 })
    expect(active.find((r) => r.name === 'Seal Speak').stuck).toEqual({ held: 0, needsYou: 0, looping: 0, total: 0 })
  })

  it('no profiles (public engine install) means no rows, and missing inputs never throw', () => {
    expect(buildProgressRows({})).toEqual({ active: [], rest: [] })
    expect(buildProgressRows({ goals, boards: null, merged: null, issuesByRepo: null, stagesByRepo: null, overview: null, now: NOW }).active).toHaveLength(3)
  })

  it('loopingTickets: 3+ plans in 24 h, garbage events ignored', () => {
    const plan = (h) => ({ stage: 'planning', status: 'started', timestamp: ago(h) })
    expect(loopingTickets({ 1: [plan(1), plan(2), plan(3)], 2: [plan(1), plan(2), { stage: 'executing', status: 'started', timestamp: ago(1) }], 3: 'junk', 4: [null, {}, plan(1)] }, NOW)).toEqual([1])
  })
})

describe('ProjectsProgress (Activity ▸ Projects)', () => {
  const row = (over) => ({ repo: 'o/a', name: 'A', hasBoard: true, goal: 'Goal one: more', signals: [], status: 'active', mergedWeek: 0, stuck: { held: 0, needsYou: 0, looping: 0, total: 0 }, ...over })

  it('a row shows name, short goal with the full goal as its tooltip, and compact signals', () => {
    const html = renderToStaticMarkup(<ProjectsProgress active={[row({ name: 'Seal Speak', goal: SEAL.goal, signals: SEAL.signals })]} rest={[]} />)
    expect(html).toContain('Seal Speak')
    expect(html).toContain('Any hard-of-hearing person can rely on…')
    expect(html).toContain(`title="${SEAL.goal}"`)
    expect(html).toContain('testers and us… —')
    expect(html).toContain('crash-free days —')
  })

  it('moving shows the week\'s PR count; stuck wins and says how many; only held tickets say "held"', () => {
    const moving = renderToStaticMarkup(<ProjectsProgress active={[row({ mergedWeek: 3 })]} rest={[]} />)
    expect(moving).toContain('moving')
    expect(moving).toContain('3 PRs/wk')
    const stuck = renderToStaticMarkup(<ProjectsProgress active={[row({ mergedWeek: 5, stuck: { held: 0, needsYou: 1, looping: 0, total: 1 } })]} rest={[]} />)
    expect(stuck).toContain('stuck 1')
    expect(stuck).not.toContain('moving')
    const held = renderToStaticMarkup(<ProjectsProgress active={[row({ stuck: { held: 2, needsYou: 0, looping: 0, total: 2 } })]} rest={[]} />)
    expect(held).toContain('held')
    expect(held).not.toContain('stuck')
  })

  it('parked or done collapse into one line that names how many', () => {
    const html = renderToStaticMarkup(<ProjectsProgress active={[row()]} rest={[row({ repo: 'o/b', name: 'B', status: 'parked', goal: null }), row({ repo: 'o/c', name: 'C', status: 'done (handed off)', goal: null })]} />)
    expect(html).toContain('2 parked or done')
    expect(html).not.toContain('>B<') // collapsed until tapped
    const open = renderToStaticMarkup(<ProjectsProgress active={[]} rest={[row({ repo: 'o/b', name: 'B', status: 'parked', goal: null })]} initiallyExpanded />)
    expect(open).toContain('>B<')
    expect(open).toContain('Parked')
  })

  it('renders nothing with no projects, and hostile text stays text', () => {
    expect(renderToStaticMarkup(<ProjectsProgress active={[]} rest={[]} />)).toBe('')
    const evil = '<script>alert(1)</script>'
    const html = renderToStaticMarkup(<ProjectsProgress active={[row({ name: evil, goal: evil, signals: [{ name: evil, better: 'up' }] })]} rest={[]} />)
    expect(html).not.toContain('<script>')
  })

  it('narrow width: the grid columns can shrink (min-w-0, truncate) rather than overflow', () => {
    const html = renderToStaticMarkup(<ProjectsProgress active={[row({ goal: 'x'.repeat(5000) })]} rest={[]} />)
    expect(html).toContain('min-w-0')
    expect(html).toContain('truncate')
    expect(html).not.toMatch(/width:\s*\d{3,}px/)
  })
})
