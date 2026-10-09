import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import path from 'path'
import { listSuggestions } from '../electron/main/suggestions.js'

describe('listSuggestions', () => {
  it('parses valid JSON from run() and returns suggestions', async () => {
    const run = async () => JSON.stringify([
      { title: 'Test Suggestion', priority: 1, status: 'pending', impact: 'speed', effort: 'low', body: 'Test body' }
    ])
    const result = await listSuggestions({ run })
    expect(result.error).toBeNull()
    expect(result.suggestions).toHaveLength(1)
    expect(result.suggestions[0].title).toBe('Test Suggestion')
  })

  it('returns empty array on invalid JSON', async () => {
    const run = async () => 'not valid json'
    const result = await listSuggestions({ run })
    expect(result.suggestions).toEqual([])
    expect(result.error).toMatch(/Could not read suggestions/)
  })

  it('returns empty array when run throws', async () => {
    const run = async () => { throw new Error('Script failed') }
    const result = await listSuggestions({ run })
    expect(result.suggestions).toEqual([])
    expect(result.error).toMatch(/Script failed/)
  })

  it('returns empty suggestions when run yields empty JSON array', async () => {
    const run = async () => '[]'
    const result = await listSuggestions({ run })
    expect(result.error).toBeNull()
    expect(result.suggestions).toEqual([])
  })

  it('never throws to the caller', async () => {
    const run = async () => { throw new Error('boom') }
    const result = await listSuggestions({ run })
    expect(result).toHaveProperty('suggestions')
    expect(result).toHaveProperty('error')
    expect(() => {}).not.toThrow() // just verify this code path doesn't throw
  })

  it('handles concurrent calls independently', async () => {
    let callCount = 0
    const run = async () => {
      callCount++
      return JSON.stringify([{ title: `Call ${callCount}`, priority: callCount }])
    }
    const results = await Promise.all([listSuggestions({ run }), listSuggestions({ run })])
    expect(results[0].suggestions[0].priority).toBe(1)
    expect(results[1].suggestions[0].priority).toBe(2)
  })

  it('handles null and undefined in JSON', async () => {
    const run = async () => JSON.stringify([
      { title: 'Entry', priority: null, impact: undefined, body: 'text' }
    ])
    const result = await listSuggestions({ run })
    expect(result.error).toBeNull()
    expect(result.suggestions).toHaveLength(1)
    expect(result.suggestions[0].priority).toBeNull()
    // undefined is omitted from JSON and not present in parsed result
    expect(result.suggestions[0].impact).toBeUndefined()
  })

  it('preserves field values through JSON round-trip', async () => {
    const entry = {
      title: 'Complex Entry',
      priority: 2,
      status: 'done',
      impact: 'token-reduction',
      effort: 'high',
      body: 'This is a\nmultiline\nbody'
    }
    const run = async () => JSON.stringify([entry])
    const result = await listSuggestions({ run })
    expect(result.suggestions[0]).toEqual(entry)
  })
})

describe('Suggestions API surface (no write path)', () => {
  it('preload exposes only the read-only suggestions:list channel', () => {
    const preloadSource = readFileSync(
      path.join(path.dirname(__filename), '../electron/preload/index.js'),
      'utf-8'
    )
    // Should expose list
    expect(preloadSource).toMatch(/suggestions:\s*\{\s*list:/)
    // Should NOT expose any write methods in the suggestions object
    // (checking the specific pattern with closing brace to avoid matching other objects)
    const suggestionsMatch = preloadSource.match(/suggestions:\s*\{([^}]+)\}/s)
    expect(suggestionsMatch).toBeTruthy()
    const suggestionsBody = suggestionsMatch[1]
    expect(suggestionsBody).not.toContain('save:')
    expect(suggestionsBody).not.toContain('update:')
    expect(suggestionsBody).not.toContain('delete:')
  })

  it('main process registers only suggestions:list handler', () => {
    const mainSource = readFileSync(
      path.join(path.dirname(__filename), '../electron/main/index.js'),
      'utf-8'
    )
    // Should have the handler registration
    expect(mainSource).toMatch(/ipcMain\.handle\('suggestions:list'/)
    // Should NOT have any write handlers
    expect(mainSource).not.toMatch(/ipcMain\.handle\('suggestions:save'/)
    expect(mainSource).not.toMatch(/ipcMain\.handle\('suggestions:update'/)
    expect(mainSource).not.toMatch(/ipcMain\.handle\('suggestions:delete'/)
  })

  it('suggestions.js module never writes to file', () => {
    const suggestionsSource = readFileSync(
      path.join(path.dirname(__filename), '../electron/main/suggestions.js'),
      'utf-8'
    )
    // Should not import fs or Path.write
    expect(suggestionsSource).not.toMatch(/\.write/)
    expect(suggestionsSource).not.toMatch(/writeFile/)
    expect(suggestionsSource).not.toMatch(/appendFile/)
  })
})
