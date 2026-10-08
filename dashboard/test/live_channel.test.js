import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createLiveChannel } from '../mobile-backend/live_channel.js'

describe('createLiveChannel', () => {
  let channel
  let mockTriggerHub
  let mockRefreshServerFactory
  let fakeTriggerListeners

  beforeEach(() => {
    fakeTriggerListeners = []
    mockTriggerHub = {
      watchFiles: vi.fn(),
      close: vi.fn(),
      onTrigger: vi.fn((cb) => {
        fakeTriggerListeners.push(cb)
        return () => {
          fakeTriggerListeners.splice(fakeTriggerListeners.indexOf(cb), 1)
        }
      })
    }

    mockRefreshServerFactory = vi.fn(() => ({
      listen: vi.fn((port, host, cb) => {
        cb()
      }),
      close: vi.fn()
    }))
  })

  afterEach(() => {
    channel?.disconnect()
  })

  it('starts with zero listeners', async () => {
    channel = createLiveChannel({
      createTriggerHub: () => mockTriggerHub,
      createRefreshServer: mockRefreshServerFactory
    })
    expect(mockTriggerHub.watchFiles).not.toHaveBeenCalled()
    expect(mockRefreshServerFactory).not.toHaveBeenCalled()
  })

  it('connect() increments reference count and starts watchers on 0→1', async () => {
    channel = createLiveChannel({
      createTriggerHub: () => mockTriggerHub,
      createRefreshServer: mockRefreshServerFactory
    })

    const listener1 = vi.fn()
    channel.connect(listener1)

    expect(mockTriggerHub.watchFiles).toHaveBeenCalledTimes(2) // activity and agents
    expect(mockRefreshServerFactory).toHaveBeenCalledTimes(1)
  })

  it('does not restart watchers when a second client connects', async () => {
    channel = createLiveChannel({
      createTriggerHub: () => mockTriggerHub,
      createRefreshServer: mockRefreshServerFactory
    })

    const listener1 = vi.fn()
    const listener2 = vi.fn()

    channel.connect(listener1)
    const callsAfterFirst = mockTriggerHub.watchFiles.mock.calls.length
    expect(callsAfterFirst).toBe(2)

    channel.connect(listener2)
    expect(mockTriggerHub.watchFiles).toHaveBeenCalledTimes(callsAfterFirst) // no additional calls
  })

  it('disconnect() decrements reference count and stops watchers on 1→0', async () => {
    channel = createLiveChannel({
      createTriggerHub: () => mockTriggerHub,
      createRefreshServer: mockRefreshServerFactory
    })

    const listener = vi.fn()
    channel.connect(listener)

    expect(mockTriggerHub.close).not.toHaveBeenCalled()

    channel.disconnect()

    expect(mockTriggerHub.close).toHaveBeenCalledTimes(1)
  })

  it('keeps watchers running when one client disconnects but others remain', async () => {
    channel = createLiveChannel({
      createTriggerHub: () => mockTriggerHub,
      createRefreshServer: mockRefreshServerFactory
    })

    const listener1 = vi.fn()
    const listener2 = vi.fn()

    channel.connect(listener1)
    channel.connect(listener2)

    channel.disconnect()
    expect(mockTriggerHub.close).not.toHaveBeenCalled() // still one listener

    channel.disconnect()
    expect(mockTriggerHub.close).toHaveBeenCalledTimes(1) // now all gone
  })

  it('broadcasts trigger events to all connected listeners', async () => {
    channel = createLiveChannel({
      createTriggerHub: () => mockTriggerHub,
      createRefreshServer: mockRefreshServerFactory
    })

    const listener1 = vi.fn()
    const listener2 = vi.fn()

    channel.connect(listener1)
    channel.connect(listener2)

    // Simulate a trigger from the hub
    const triggerEvent = { topic: 'activity', source: 'file:state.json' }
    fakeTriggerListeners.forEach((cb) => cb(triggerEvent))

    expect(listener1).toHaveBeenCalledWith(triggerEvent)
    expect(listener2).toHaveBeenCalledWith(triggerEvent)
  })

  it('calls onRefresh when refresh server receives a ping', async () => {
    let capturedRefreshCallback
    const mockServer = {
      listen: vi.fn((port, host, cb) => cb()),
      close: vi.fn()
    }
    mockRefreshServerFactory = vi.fn((onRefresh) => {
      capturedRefreshCallback = onRefresh
      return mockServer
    })

    channel = createLiveChannel({
      createTriggerHub: () => mockTriggerHub,
      createRefreshServer: mockRefreshServerFactory
    })

    const listener = vi.fn()
    channel.connect(listener)

    // Simulate a refresh ping from the webhook
    const refreshPayload = { topics: ['activity'], source: 'github:test' }
    capturedRefreshCallback(refreshPayload)

    // The refresh should trigger emission with the payload
    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({
        topic: expect.stringMatching(/activity|agents/),
        source: 'ping'
      })
    )
  })

  it('reconnect restarts watchers cleanly', async () => {
    channel = createLiveChannel({
      createTriggerHub: () => mockTriggerHub,
      createRefreshServer: mockRefreshServerFactory
    })

    const listener = vi.fn()

    // First cycle
    channel.connect(listener)
    expect(mockTriggerHub.watchFiles).toHaveBeenCalledTimes(2)

    channel.disconnect()
    expect(mockTriggerHub.close).toHaveBeenCalledTimes(1)

    // Second cycle: reset the mock to start counting again
    mockTriggerHub.watchFiles.mockClear()
    mockTriggerHub.close.mockClear()

    // Reconnect
    channel.connect(listener)
    expect(mockTriggerHub.watchFiles).toHaveBeenCalledTimes(2)

    channel.disconnect()
    expect(mockTriggerHub.close).toHaveBeenCalledTimes(1)
  })
})
