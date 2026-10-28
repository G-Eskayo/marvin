import { describe, it, expect } from 'vitest'
import { streamLocalModel } from '../mobile-backend/local_model.js'

describe('local_model', () => {
  describe('streamLocalModel', () => {
    it('test 4: streams text from Ollama', async () => {
      // Mock fetch function that simulates Ollama streaming response
      const mockFetch = async (url, options) => {
        const chunks = [
          { response: 'Hello ' },
          { response: 'there ' },
          { response: 'world', done: true }
        ]

        return {
          ok: true,
          body: {
            getReader: () => {
              let index = 0
              return {
                async read() {
                  if (index >= chunks.length) {
                    return { done: true }
                  }
                  const chunk = chunks[index++]
                  const jsonLine = JSON.stringify(chunk) + '\n'
                  return {
                    done: false,
                    value: new TextEncoder().encode(jsonLine)
                  }
                },
                releaseLock: () => {}
              }
            }
          }
        }
      }

      const events = []
      for await (const event of streamLocalModel({
        prompt: 'test',
        model: 'llama2',
        baseUrl: 'http://localhost:11434',
        fetchFn: mockFetch
      })) {
        events.push(event)
      }

      expect(events.length).toBeGreaterThan(0)
      expect(events.some(e => e.type === 'text')).toBe(true)
      expect(events.some(e => e.type === 'result')).toBe(true)
    })

    it('handles API errors gracefully', async () => {
      const mockFetch = async () => ({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error'
      })

      const events = []
      for await (const event of streamLocalModel({
        prompt: 'test',
        model: 'llama2',
        fetchFn: mockFetch
      })) {
        events.push(event)
      }

      expect(events.some(e => e.type === 'error')).toBe(true)
    })

    it('handles network failures gracefully', async () => {
      const mockFetch = async () => {
        throw new Error('Network error')
      }

      const events = []
      for await (const event of streamLocalModel({
        prompt: 'test',
        model: 'llama2',
        fetchFn: mockFetch
      })) {
        events.push(event)
      }

      expect(events.some(e => e.type === 'error')).toBe(true)
    })

    it('uses default baseUrl when not provided', async () => {
      const mockFetch = async (url) => {
        expect(url).toContain('localhost:11434')
        return {
          ok: true,
          body: {
            getReader: () => ({
              async read() { return { done: true } },
              releaseLock: () => {}
            })
          }
        }
      }

      const events = []
      for await (const event of streamLocalModel({
        prompt: 'test',
        model: 'llama2',
        fetchFn: mockFetch
      })) {
        events.push(event)
      }
    })
  })
})
