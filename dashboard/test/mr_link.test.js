import { describe, it, expect } from 'vitest'
import { mrLinkTarget } from '../src/lib/mr_link.js'

describe('mrLinkTarget: routing MR Review links to Workshop', () => {
  it('key "pr" returns empty object (don\'t interfere with spread context)', () => {
    expect(mrLinkTarget('pr')).toEqual({})
  })
  it('key "project" returns empty object (don\'t overwrite repo in spread context)', () => {
    expect(mrLinkTarget('project')).toEqual({})
  })
  it('key "all" returns empty object (unfiltered Workshop)', () => {
    expect(mrLinkTarget('all')).toEqual({})
  })
  it('unknown keys return empty object', () => {
    expect(mrLinkTarget('unknown')).toEqual({})
  })
})
