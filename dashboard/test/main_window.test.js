import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createMainWindowTracker } from '../electron/main/main_window.js'

describe('createMainWindowTracker', () => {
  let tracker
  let mockWindow
  let sentMessages
  let eventHandlers

  beforeEach(() => {
    tracker = createMainWindowTracker()
    sentMessages = []
    eventHandlers = {}
    mockWindow = {
      isDestroyed: vi.fn(() => false),
      on: vi.fn((event, handler) => {
        eventHandlers[event] = handler
      }),
      webContents: {
        send: vi.fn((channel, ...args) => {
          sentMessages.push({ channel, args })
        })
      }
    }
  })

  it('set() stores the window', () => {
    tracker.set(mockWindow)
    expect(tracker.get()).toBe(mockWindow)
  })

  it('get() returns the stored window', () => {
    tracker.set(mockWindow)
    const retrieved = tracker.get()
    expect(retrieved).toBe(mockWindow)
    expect(retrieved.webContents).toBeDefined()
  })

  it('get() returns null when window is closed', () => {
    tracker.set(mockWindow)
    expect(eventHandlers['closed']).toBeDefined()
    // Simulate the 'closed' event
    eventHandlers['closed']()
    expect(tracker.get()).toBeNull()
  })

  it('isAlive() returns true when window exists and is not destroyed', () => {
    tracker.set(mockWindow)
    expect(tracker.isAlive()).toBe(true)
  })

  it('isAlive() returns false when window is null', () => {
    expect(tracker.isAlive()).toBe(false)
  })

  it('isAlive() returns false when window is destroyed', () => {
    const destroyedWindow = {
      isDestroyed: () => true,
      on: vi.fn(),
      webContents: { send: () => {} }
    }
    tracker.set(destroyedWindow)
    expect(tracker.isAlive()).toBe(false)
  })

  it('send() sends a message when window is alive', () => {
    tracker.set(mockWindow)
    tracker.send('test:channel', 'arg1', 'arg2')
    expect(mockWindow.webContents.send).toHaveBeenCalledWith('test:channel', 'arg1', 'arg2')
  })

  it('send() does not send when window is destroyed', () => {
    const destroyedWindow = {
      isDestroyed: () => true,
      on: vi.fn(),
      webContents: {
        send: vi.fn()
      }
    }
    tracker.set(destroyedWindow)
    tracker.send('test:channel', 'arg1')
    expect(destroyedWindow.webContents.send).not.toHaveBeenCalled()
  })
})
