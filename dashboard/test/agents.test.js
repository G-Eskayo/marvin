import { describe, it, expect } from 'vitest'
import { describeSchedule, parseLaunchctlList, buildAgents } from '../electron/main/agents.js'

describe('describeSchedule', () => {
  it('reads interval, daily and always-on schedules', () => {
    expect(describeSchedule({ StartInterval: 900 })).toBe('every 15 min')
    expect(describeSchedule({ StartInterval: 3600 })).toBe('every hour')
    expect(describeSchedule({ StartCalendarInterval: { Hour: 8, Minute: 30 } })).toBe('daily at 08:30')
    expect(describeSchedule({ StartCalendarInterval: { Hour: 3 } })).toBe('daily at 03:00')
    expect(describeSchedule({ KeepAlive: true })).toBe('always on')
    expect(describeSchedule({ RunAtLoad: true })).toBe('at login')
  })
})

describe('parseLaunchctlList', () => {
  it('maps label to pid and last exit status', () => {
    const out = 'PID\tStatus\tLabel\n123\t0\tcom.marvin.dashboard-webhook\n-\t0\tcom.marvin.health-check\n-\t1\tcom.marvin.auto-fix\n'
    expect(parseLaunchctlList(out)).toEqual({
      'com.marvin.dashboard-webhook': { pid: 123, status: 0 },
      'com.marvin.health-check': { pid: null, status: 0 },
      'com.marvin.auto-fix': { pid: null, status: 1 }
    })
  })
})

const plist = (label, extra = {}) => ({ label, ...extra })
const job = (over = {}) => ({ job: 'health-check', label: 'Health check sweep', status: 'idle', current: null, last: { status: 'passed', finishedAt: '2026-10-05T12:00:00Z', durationS: 4, summary: 'ok', error: '' }, runs: [{ id: 'r' }], ...over })

describe('buildAgents', () => {
  it('lists run logs that belong to no launchd agent (jobs that run inside another) as their own entries', () => {
    const agents = buildAgents({
      plists: [plist('com.marvin.ticket-pipeline', { StartInterval: 3600 })],
      launchctl: {},
      jobs: [job({ job: 'ticket-pipeline', label: 'Ticket pipeline' }), job({ job: 'project-catalog', label: 'Project catalog' })]
    })
    const sub = agents.find((x) => x.id === 'project-catalog')
    expect(sub).toMatchObject({ kind: 'job', reporting: true, label: 'Project catalog', schedule: 'runs inside another agent' })
    expect(agents.filter((x) => x.id === 'ticket-pipeline')).toHaveLength(1)
  })

  it('joins launchd facts with the run log for agents that report', () => {
    const [a] = buildAgents({ plists: [plist('com.marvin.health-check', { StartInterval: 900 })], launchctl: { 'com.marvin.health-check': { pid: null, status: 0 } }, jobs: [job()] })
    expect(a).toMatchObject({ id: 'health-check', schedule: 'every 15 min', reporting: true, status: 'idle', running: false })
    expect(a.job.last.summary).toBe('ok')
  })

  it('shows a running process as running even if its run log says idle', () => {
    const [a] = buildAgents({ plists: [plist('com.marvin.health-check', { StartInterval: 900 })], launchctl: { 'com.marvin.health-check': { pid: 99, status: 0 } }, jobs: [job()] })
    expect(a.status).toBe('running')
  })

  it('an agent with no run log is not reporting: status comes from launchd alone', () => {
    const agents = buildAgents({
      plists: [plist('com.marvin.a', { StartInterval: 60 }), plist('com.marvin.b', { StartInterval: 60 })],
      launchctl: { 'com.marvin.a': { pid: null, status: 0 }, 'com.marvin.b': { pid: null, status: 78 } },
      jobs: []
    })
    expect(agents.find((x) => x.id === 'a')).toMatchObject({ reporting: false, status: 'idle' })
    expect(agents.find((x) => x.id === 'b')).toMatchObject({ reporting: false, status: 'failed' })
  })

  it('always-on services are running or stopped, never idle', () => {
    const agents = buildAgents({
      plists: [plist('com.marvin.dashboard-webhook', { KeepAlive: true }), plist('com.marvin.desktoplive', { KeepAlive: true })],
      launchctl: { 'com.marvin.dashboard-webhook': { pid: 5, status: 0 } },
      jobs: []
    })
    expect(agents.find((x) => x.id === 'dashboard-webhook')).toMatchObject({ kind: 'service', status: 'running' })
    expect(agents.find((x) => x.id === 'desktoplive')).toMatchObject({ kind: 'service', status: 'stopped' })
  })

  it('ranks problems first, then running, then the rest by name', () => {
    const agents = buildAgents({
      plists: ['z', 'b', 'a'].map((n) => plist(`com.marvin.${n}`, { StartInterval: 60 })),
      launchctl: { 'com.marvin.z': { pid: null, status: 1 }, 'com.marvin.b': { pid: 7, status: 0 }, 'com.marvin.a': { pid: null, status: 0 } },
      jobs: []
    })
    expect(agents.map((x) => x.id)).toEqual(['z', 'b', 'a'])
  })

  it('names a job after its launchd label even for the shared script', () => {
    const [a] = buildAgents({ plists: [plist('com.marvin.research-colony', { StartInterval: 60 })], launchctl: {}, jobs: [job({ job: 'research-colony', label: 'Research colony' })] })
    expect(a.label).toBe('Research colony')
  })
})
