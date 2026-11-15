import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ChatHelpersView, dismissKey, visibleHelpers } from '../src/components/ChatHelpers.jsx'
import { describeHelper } from '../webhook-server/chat_helpers.js'

const T0 = Date.parse('2026-10-22T15:00:00Z')
const iso = (ms) => new Date(ms).toISOString()

function helperDoc(id, { status = 'running', started = T0, finished = null, summary = '', error = '', links = [], transcript = '' } = {}) {
  return {
    job: `helper-${id}`,
    label: `Helper ${id}`,
    kind: 'helper',
    helper: { agent_id: id, agent_type: 'general-purpose', session: 'b41ed591', chat: 'fix the docs search', machine: 'macbook-pro', cwd: '/Users/gil', transcript, links },
    runs: [{ id: 'r1', status, started_at: iso(started), finished_at: finished ? iso(finished) : null, steps: [{ step: 'working', detail: '', at: iso(started) }], summary, error }]
  }
}

describe('ChatHelpersView with dismissal (Tests 11 & 13)', () => {
  const now = T0 + 8 * 60_000

  // Test 11: ChatHelpersView respects dismissed and passes onDismiss to AgentCard
  it('Only crashed helper has dismiss button; running/done/dismissed helpers do not', () => {
    // Create test data with different statuses
    const running = describeHelper(helperDoc('run', { started: T0 + 5 * 60_000 }), { now })
    const done = describeHelper(helperDoc('done', { status: 'passed', finished: T0 + 7 * 60_000, summary: 'Filed' }), { now })
    const crashed = describeHelper(helperDoc('crash', { status: 'failed', finished: T0 + 60_000, error: 'error' }), { now })

    // Manually set crashed helper's status to 'crashed' for testing
    const crashedWithStatus = { ...crashed, status: 'crashed' }

    const data = {
      helpers: [running, done, crashedWithStatus],
      unreachable: ['mac-mini-1']
    }

    const dismissed = { [dismissKey(data.helpers[1])]: true } // dismiss the 'done' helper
    const onDismiss = () => {}

    const html = renderToStaticMarkup(
      <ChatHelpersView
        data={data}
        now={now}
        dismissed={dismissed}
        onDismiss={onDismiss}
      />
    )

    // The dismissed helper should not be rendered at all
    expect(html).not.toContain('Helper done')

    // The running and crashed helpers should be rendered
    expect(html).toContain('Helper run')
    expect(html).toContain('Helper crash')

    // Count dismiss buttons — should have exactly one button with Dismiss text
    // (not just counting "Dismiss" word, which appears in title attribute too)
    const dismissButtonCount = (html.match(/>Dismiss</g) || []).length
    expect(dismissButtonCount).toBe(1)
    // Verify it's in the crashed card (rough check: Dismiss button appears after crash label)
    const crashIndex = html.indexOf('Helper crash')
    const dismissIndex = html.indexOf('>Dismiss<')
    expect(dismissIndex).toBeGreaterThan(crashIndex)
  })

  // Test 13: Rendering smoke test
  it('renders without errors with various states', () => {
    // No helpers
    expect(renderToStaticMarkup(<ChatHelpersView data={{ helpers: [] }} now={now} />)).toBe('')

    // No data
    expect(renderToStaticMarkup(<ChatHelpersView data={null} now={now} />)).toBe('')

    // With dismissed state
    const data = {
      helpers: [
        describeHelper(helperDoc('run', { started: T0 + 5 * 60_000 }), { now }),
        describeHelper(helperDoc('done', { status: 'passed', finished: T0 + 7 * 60_000, summary: 'ok' }), { now })
      ],
      unreachable: []
    }

    const dismissed = { 'macbook-pro:helper-run': true }
    const html = renderToStaticMarkup(
      <ChatHelpersView
        data={data}
        now={now}
        dismissed={dismissed}
      />
    )
    expect(html).toContain('data-testid="chat-helpers"')
    expect(html).not.toContain('Helper run')
    expect(html).toContain('Helper done')
  })
})

describe('visibleHelpers cap behavior (Test 7-8: all running kept)', () => {
  const now = T0 + 8 * 60_000

  it('keeps all running helpers even when total exceeds cap', () => {
    // Create 12 running helpers (exceeds default cap of 10)
    const runningHelpers = []
    for (let i = 0; i < 12; i++) {
      const helper = describeHelper(helperDoc(`run${i}`, { started: T0 + i * 60_000 }), { now })
      runningHelpers.push(helper)
    }

    // All should be visible (not capped)
    const visible = visibleHelpers(runningHelpers, {}, 10)
    expect(visible).toHaveLength(12)
    visible.forEach(h => {
      expect(h.status).toBe('running')
    })
  })

  it('fills remaining slots with other statuses after all running', () => {
    // 8 running, 3 crashed, 2 done
    const running = []
    for (let i = 0; i < 8; i++) {
      running.push(describeHelper(helperDoc(`run${i}`, { started: T0 + i * 60_000 }), { now }))
    }

    const crashed = []
    for (let i = 0; i < 3; i++) {
      const helper = describeHelper(helperDoc(`crash${i}`, { status: 'failed', finished: T0 + (8 + i) * 60_000 }), { now })
      crashed.push({ ...helper, status: 'crashed' })
    }

    const done = []
    for (let i = 0; i < 2; i++) {
      done.push(describeHelper(helperDoc(`done${i}`, { status: 'passed', finished: T0 + (11 + i) * 60_000 }), { now }))
    }

    const all = [...running, ...crashed, ...done]
    const visible = visibleHelpers(all, {}, 10)

    // Should have all 8 running + 2 crashed (filling the cap to 10)
    expect(visible).toHaveLength(10)
    expect(visible.slice(0, 8).every(h => h.status === 'running')).toBe(true)
    expect(visible.slice(8, 10).every(h => h.status === 'crashed')).toBe(true)
  })

  it('respects dismissed entries and still prioritizes running', () => {
    // 12 running, dismiss 2
    const helpers = []
    for (let i = 0; i < 12; i++) {
      helpers.push(describeHelper(helperDoc(`run${i}`, { started: T0 + i * 60_000 }), { now }))
    }

    const dismissed = {
      [dismissKey(helpers[0])]: true,
      [dismissKey(helpers[1])]: true
    }

    const visible = visibleHelpers(helpers, dismissed, 10)

    // Should have 10 running (12 - 2 dismissed)
    expect(visible).toHaveLength(10)
    visible.forEach(h => {
      expect(h.status).toBe('running')
    })
    // The dismissed ones should not be in the visible list
    expect(visible).not.toContainEqual(helpers[0])
    expect(visible).not.toContainEqual(helpers[1])
  })
})
