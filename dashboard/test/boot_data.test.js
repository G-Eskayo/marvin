import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync, mkdirSync, utimesSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { buildBootData, createBootGate, STALE_MINUTES } from '../electron/main/boot_data.js'

// The boot's verdict banner says "ALL SYSTEMS NOMINAL" at every launch, so these tests try hard to make it lie:
// stale snapshots, an `overall: green` that still holds red checks, missing or corrupt files, unknown severities.
// Everything runs against a temp tree, never the real ~/.claude (see the 2026-10-09 logs wipe).

const NOW = new Date('2026-10-14T17:00:00Z')
const minutesAgo = (m) => new Date(NOW.getTime() - m * 60_000).toISOString()
const check = (id, severity, label = id, detail = '') => ({ id, label, severity, detail })

function tree({ health, memoryIndex = '- [A](a.md) — x\n- [B](b.md) — y\n', memoryFiles = ['a.md', 'b.md'], skills = ['tdd', 'diagnose'], handoffs = [] } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), 'boot-data-'))
  const p = {
    healthPath: path.join(root, 'logs', 'health-status.json'),
    memoryDir: path.join(root, 'memory'),
    skillsDir: path.join(root, 'skills'),
    handoffsDir: path.join(root, 'handoffs')
  }
  for (const d of [path.dirname(p.healthPath), p.memoryDir, p.skillsDir, p.handoffsDir]) mkdirSync(d, { recursive: true })
  if (health !== undefined) writeFileSync(p.healthPath, typeof health === 'string' ? health : JSON.stringify(health))
  if (memoryIndex !== null) writeFileSync(path.join(p.memoryDir, 'MEMORY.md'), '# Memory Index\n\n' + memoryIndex)
  for (const f of memoryFiles) writeFileSync(path.join(p.memoryDir, f), 'x')
  for (const s of skills) { mkdirSync(path.join(p.skillsDir, s)); writeFileSync(path.join(p.skillsDir, s, 'SKILL.md'), 'x') }
  handoffs.forEach(([name, mtime]) => {
    const f = path.join(p.handoffsDir, name); writeFileSync(f, 'x'); utimesSync(f, mtime, mtime)
  })
  return { ...p, now: NOW, done: () => rmSync(root, { recursive: true, force: true }) }
}

const GREEN = (extra = []) => ({
  generated_at: minutesAgo(5), overall: 'green',
  checks: [
    check('repo:sync:~/.claude@macbook-pro-1', 'green', '~/.claude sync -- macbook-pro-1'),
    check('repo:sync:~/.claude@mac-mini-1', 'green', '~/.claude sync -- mac-mini-1'),
    check('machine:mac-mini-1', 'green', 'Machine: mac-mini-1'),
    check('disk:space@mac-mini-1', 'green', 'Disk space -- mac-mini-1', '120 GiB free of 228 (52%)'),
    check('jobs:exit@mac-mini-1', 'green', 'Scheduled jobs -- mac-mini-1', 'all jobs exited cleanly'),
    check('main:green', 'green', 'Main is green', 'main @ abc1234: 2143 passed, 9 skipped in 331.58s (0:05:31)'),
    ...extra
  ]
})
const line = (data, chip) => data.lines.find((l) => l.chip === chip)

describe('the verdict: ALL SYSTEMS NOMINAL only when it is true', () => {
  it('is nominal when health says green, every check is green, and the snapshot is fresh', () => {
    const t = tree({ health: GREEN() })
    const d = buildBootData(t)
    expect(d.verdict).toEqual({ nominal: true, tone: 'nominal', text: 'ALL SYSTEMS NOMINAL' })
    t.done()
  })

  it('is NOT nominal when the snapshot is older than the stale limit, and says so with a STALE line', () => {
    const t = tree({ health: { ...GREEN(), generated_at: minutesAgo(STALE_MINUTES + 1) } })
    const d = buildBootData(t)
    expect(d.verdict.nominal).toBe(false)
    expect(d.verdict.text).not.toMatch(/NOMINAL/)
    expect(line(d, 'STALE').text).toMatch(new RegExp(`${STALE_MINUTES + 1} MIN OLD`))
    t.done()
  })

  it('is NOT nominal when overall claims green but a check inside is red (trust the worst check, not the summary)', () => {
    const t = tree({ health: GREEN([check('disk:space@macbook-pro-1', 'red', 'Disk space -- macbook-pro-1')]) })
    const d = buildBootData(t)
    expect(d.verdict).toMatchObject({ nominal: false, tone: 'issues', text: '1 CRITICAL · OPEN HEALTH' })
    t.done()
  })

  it('a warning alone also blocks nominal, and counts are pluralised correctly', () => {
    const one = tree({ health: { ...GREEN([check('x', 'yellow')]), overall: 'yellow' } })
    expect(buildBootData(one).verdict.text).toBe('1 WARNING · OPEN HEALTH')
    one.done()
    const many = tree({ health: { ...GREEN([check('a', 'red'), check('b', 'red'), check('c', 'yellow'), check('d', 'yellow')]), overall: 'red' } })
    expect(buildBootData(many).verdict.text).toBe('2 CRITICAL · 2 WARNINGS · OPEN HEALTH')
    many.done()
  })

  it('a missing health file is unknown, never green', () => {
    const t = tree({})
    const d = buildBootData(t)
    expect(d.verdict).toEqual({ nominal: false, tone: 'unknown', text: 'HEALTH UNKNOWN · OPEN HEALTH' })
    expect(d.feed).toEqual([])
    expect(line(d, 'SYNC').level).not.toBe('green')
    expect(line(d, 'LINK').level).not.toBe('green')
    t.done()
  })

  it('a corrupt or wrongly-shaped health file is unknown, never green, and never throws', () => {
    for (const bad of ['{not json', '[]', '{"overall":"green","checks":"lots"}', '{"overall":"green","checks":[null, 7, "x"]}']) {
      const t = tree({ health: bad })
      const d = buildBootData(t)
      expect(d.verdict.nominal).toBe(false)
      t.done()
    }
  })

  it('a check with an unknown or missing severity counts as a warning, not green', () => {
    const t = tree({ health: GREEN([{ id: 'weird', label: 'Weird', severity: 'purple' }, { id: 'none', label: 'None' }]) })
    const d = buildBootData(t)
    expect(d.verdict.nominal).toBe(false)
    expect(d.counts.yellow).toBe(2)
    expect(d.feed.filter((f) => f.level === 'yellow').map((f) => f.label)).toEqual(['Weird', 'None'])
    t.done()
  })
})

describe('the summary lines read real sources', () => {
  it('SYNC takes the worst of the memory-sync checks and names the reason', () => {
    const t = tree({ health: GREEN([check('repo:integrity:~/.claude', 'red', '~/.claude stash/conflict integrity')]) })
    const s = line(buildBootData(t), 'SYNC')
    expect(s.level).toBe('red')
    expect(s.text).toMatch(/STASH\/CONFLICT INTEGRITY/)
    t.done()
  })

  it('memories are the links in MEMORY.md; a broken link turns the line into a warning', () => {
    const ok = tree({ health: GREEN() })
    expect(line(buildBootData(ok), 'OK').text).toBe('2 MEMORIES CHARTED · 2 SKILLS WIRED')
    ok.done()
    const broken = tree({ health: GREEN(), memoryFiles: ['a.md'] })
    const b = line(buildBootData(broken), 'WARN')
    expect(b.level).toBe('yellow')
    expect(b.text).toMatch(/1 BROKEN LINK$/)
    broken.done()
  })

  it('skills are the skill folders with a SKILL.md, not slash-command files', () => {
    // 2026-10-22 the line said 36: it counted ~/.claude/commands (3 third-party commands, one dead link) for 33 skills.
    const t = tree({ health: GREEN(), skills: ['tdd', 'diagnose', 'variable-tracker'] })
    mkdirSync(path.join(t.skillsDir, 'empty-folder'))                                  // no SKILL.md: not a skill
    writeFileSync(path.join(t.skillsDir, 'conftest.py'), 'x')                           // a file, not a folder
    mkdirSync(path.join(t.skillsDir, 'renamed')); writeFileSync(path.join(t.skillsDir, 'renamed', 'skill.md'), 'x')
    mkdirSync(path.join(t.skillsDir, 'SKILL.md'))                                       // a folder named like the file
    expect(line(buildBootData(t), 'OK').text).toBe('2 MEMORIES CHARTED · 3 SKILLS WIRED')
    t.done()
  })

  it('a missing skills folder reads as 0 skills, never a crash', () => {
    const t = tree({ health: GREEN() })
    rmSync(t.skillsDir, { recursive: true, force: true })
    expect(line(buildBootData(t), 'OK').text).toBe('2 MEMORIES CHARTED · 0 SKILLS WIRED')
    t.done()
  })

  it('a missing memory index is a warning, not a zero-memories green', () => {
    const t = tree({ health: GREEN(), memoryIndex: null, memoryFiles: [] })
    const m = buildBootData(t).lines.find((l) => l.chip === 'OK' || l.chip === 'WARN')
    expect(m.level).toBe('yellow')
    expect(m.text).toMatch(/MEMORY INDEX MISSING/)
    t.done()
  })

  it('LINK shows the Mac Mini problem in plain words: disk percent, failed job count', () => {
    const disk = tree({ health: GREEN([]) })
    // replace the disk check with a red one
    const h = GREEN(); h.checks = h.checks.map((c) => c.id === 'disk:space@mac-mini-1' ? { ...c, severity: 'red', detail: '22 GiB free of 228 (10%); 30 pipeline worktrees use 8.2 GiB' } : c)
    writeFileSync(disk.healthPath, JSON.stringify(h))
    expect(line(buildBootData(disk), 'LINK')).toEqual({ chip: 'LINK', level: 'red', text: 'MAC-MINI · DISK 10% FREE', target: { tab: 'health', check: 'disk:space@mac-mini-1' } })
    disk.done()
    const jobs = tree({})
    const j = GREEN(); j.checks = j.checks.map((c) => c.id === 'jobs:exit@mac-mini-1' ? { ...c, severity: 'red', detail: 'last run failed: a (exit 1), b (exit 1), c (exit 78)' } : c)
    writeFileSync(jobs.healthPath, JSON.stringify(j))
    expect(line(buildBootData(jobs), 'LINK').text).toBe('MAC-MINI · 3 JOBS FAILED')
    jobs.done()
  })

  it('LINK is a warning, not green, when no Mac Mini check exists at all', () => {
    const t = tree({ health: { generated_at: minutesAgo(1), overall: 'green', checks: [check('main:green', 'green', 'Main', '5 passed')] } })
    expect(line(buildBootData(t), 'LINK').level).toBe('yellow')
    t.done()
  })

  it('PLOT names the newest handoff by modification time, with its topic', () => {
    const t = tree({ health: GREEN(), handoffs: [
      ['handoff-2026-10-14-memory-sync-alarms.md', new Date('2026-10-14T10:00:00Z')],
      ['handoff-2026-10-13-18-48.md', new Date('2026-10-14T12:00:00Z')]
    ] })
    expect(line(buildBootData(t), 'PLOT').text).toBe('HANDOFF · 2026-10-13')
    t.done()
  })

  it('TEST reads the real counts from main:green, and is a warning when that check is missing', () => {
    const t = tree({ health: GREEN() })
    expect(line(buildBootData(t), 'TEST')).toEqual({ chip: 'TEST', level: 'green', text: 'TESTS · 2143 PASSED · 9 SKIPPED', target: { tab: 'health', check: 'main:green' } })
    t.done()
    const u = tree({ health: { generated_at: minutesAgo(1), overall: 'green', checks: [] } })
    expect(line(buildBootData(u), 'TEST')).toMatchObject({ level: 'yellow', text: 'TESTS · UNKNOWN' })
    u.done()
  })

  it('the feed is every check in order, with label and level only', () => {
    const t = tree({ health: GREEN() })
    const d = buildBootData(t)
    expect(d.feed).toHaveLength(6)
    expect(Object.keys(d.feed[0]).sort()).toEqual(['label', 'level'])
    expect(d.counts).toEqual({ green: 6, yellow: 0, red: 0, total: 6 })
    t.done()
  })
})

describe('each summary line knows where its real thing lives (#433)', () => {
  it('SYNC, LINK and TEST point at the exact check behind them; STALE at Health; LOCK, OK and PLOT at nothing', () => {
    const h = GREEN([check('repo:integrity:~/.claude', 'red', 'stash integrity')])
    h.checks = h.checks.map((c) => c.id === 'disk:space@mac-mini-1' ? { ...c, severity: 'red', detail: '22 GiB free of 228 (10%)' } : c)
    const t = tree({ health: { ...h, generated_at: minutesAgo(STALE_MINUTES + 5) } })
    const d = buildBootData(t)
    expect(line(d, 'SYNC').target).toEqual({ tab: 'health', check: 'repo:integrity:~/.claude' })
    expect(line(d, 'LINK').target).toEqual({ tab: 'health', check: 'disk:space@mac-mini-1' })
    expect(line(d, 'TEST').target).toEqual({ tab: 'health', check: 'main:green' })
    expect(line(d, 'STALE').target).toEqual({ tab: 'health' })
    for (const chip of ['LOCK', 'OK', 'PLOT']) expect(line(d, chip).target ?? null).toBeNull()
    t.done()
  })

  it('a healthy line still points at its check (the first one), so you can look at it', () => {
    const t = tree({ health: GREEN() })
    const d = buildBootData(t)
    expect(line(d, 'SYNC').target).toEqual({ tab: 'health', check: 'repo:sync:~/.claude@macbook-pro-1' })
    expect(line(d, 'LINK').target).toEqual({ tab: 'health', check: 'machine:mac-mini-1' })
    t.done()
  })

  it('when the checks behind a line are missing, it points at Health, not at a check that does not exist', () => {
    const t = tree({})
    const d = buildBootData(t)
    expect(line(d, 'SYNC').target).toEqual({ tab: 'health' })
    expect(line(d, 'LINK').target).toEqual({ tab: 'health' })
    expect(line(d, 'TEST').target).toEqual({ tab: 'health' })
    t.done()
  })
})

describe('the boot plays once per app launch', () => {
  it('the first window load gets the boot; reloads after it do not', () => {
    const gate = createBootGate()
    expect(gate()).toBe(true)
    expect(gate()).toBe(false)
    expect(gate()).toBe(false)
  })
})
