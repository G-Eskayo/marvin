import { describe, it, expect, vi } from 'vitest'
import { mergeMutationSection, renderMutationSection, upsertMutationSection } from '../webhook-server/pr_body_section.js'

describe('mergeMutationSection: update PR body with mutation marker', () => {
  it('appends a new section when markers are not present', () => {
    const body = 'Existing PR description\n'
    const section = '## Mutation Score\n\n80% (4/5 mutants killed)\n'

    const result = mergeMutationSection(body, section)

    expect(result).toContain('Existing PR description')
    expect(result).toContain('Mutation Score')
    expect(result).toContain('<!-- marvin:mutation-check -->')
    expect(result).toContain('<!-- /marvin:mutation-check -->')
    expect(result.match(/<!-- marvin:mutation-check -->/g)).toHaveLength(1)
  })

  it('replaces an existing section in place', () => {
    const body = [
      'Existing PR description',
      '<!-- marvin:mutation-check -->',
      '## Mutation Score',
      '80% (4/5 mutants killed)',
      '<!-- /marvin:mutation-check -->',
      'More content after'
    ].join('\n')

    const newSection = '## Mutation Score\n\n90% (9/10 mutants killed)\n'
    const result = mergeMutationSection(body, newSection)

    expect(result).toContain('Existing PR description')
    expect(result).toContain('90%')
    expect(result).not.toContain('80%')
    expect(result).toContain('More content after')
    expect(result.match(/<!-- marvin:mutation-check -->/g)).toHaveLength(1)
  })

  it('preserves unrelated content outside the markers', () => {
    const body = [
      '## Overview',
      'Something important',
      '<!-- marvin:mutation-check -->',
      'Old mutation data',
      '<!-- /marvin:mutation-check -->',
      '',
      '## Testing',
      'Manual test steps...'
    ].join('\n')

    const newSection = 'New mutation data\n'
    const result = mergeMutationSection(body, newSection)

    expect(result).toContain('Overview')
    expect(result).toContain('Something important')
    expect(result).toContain('Testing')
    expect(result).toContain('Manual test steps')
    expect(result).not.toContain('Old mutation data')
  })

  it('is idempotent: merging the same section twice produces the same result', () => {
    const body = 'Initial\n'
    const section = 'Mutation: 75%\n'

    const first = mergeMutationSection(body, section)
    const second = mergeMutationSection(first, section)

    expect(first).toBe(second)
  })

  it('handles empty body', () => {
    const result = mergeMutationSection('', '## Score\n50%')
    expect(result).toContain('<!-- marvin:mutation-check -->')
    expect(result).toContain('## Score')
  })

  it('handles section with only whitespace before it', () => {
    const body = '   \n  \n'
    const section = 'Data'
    const result = mergeMutationSection(body, section)

    expect(result).toContain('Data')
    expect(result).toContain('<!-- marvin:mutation-check -->')
  })
})

describe('renderMutationSection: format mutation result for PR body', () => {
  it('renders a passing score with survivors listed', () => {
    const result = {
      status: 'ok',
      score: 0.8,
      mutants_total: 5,
      killed: 4,
      survived: [
        { file: 'lib/math.py', line: 10, operator: 'Lt->Gt', snippet: 'x > 0' }
      ],
      unmeasured: []
    }

    const md = renderMutationSection(result)

    expect(md).toContain('80%')
    expect(md).toContain('4 of 5 mutants killed')
    expect(md).toContain('Surviving Mutants')
    expect(md).toContain('lib/math.py')
    expect(md).toContain('Lt->Gt')
  })

  it('renders 100% score without survivors table', () => {
    const result = {
      status: 'ok',
      score: 1.0,
      mutants_total: 3,
      killed: 3,
      survived: [],
      unmeasured: []
    }

    const md = renderMutationSection(result)

    expect(md).toContain('100%')
    expect(md).toContain('3 of 3 mutants killed')
    expect(md).not.toContain('Surviving Mutants')
  })

  it('caps survivor listing at ~20 and notes the overflow', () => {
    const survivors = Array.from({ length: 25 }, (_, i) => ({
      file: `lib/file${i}.py`,
      line: 10 + i,
      operator: 'Eq->NotEq',
      snippet: `cond${i}`
    }))

    const result = {
      status: 'ok',
      score: 0.43,  // 19 / (19 + 25) = 0.43
      mutants_total: 50,
      killed: 19,
      survived: survivors,  // 25 survivors + 19 killed = 44 total scored
      unmeasured: []
    }

    const md = renderMutationSection(result)

    expect(md).toContain('43%')  // 19 / 44
    expect(md).toContain('19 of 44 mutants killed')
    expect(md).toContain('file0')
    expect(md).toContain('... and 5 more')  // 25 total but cap at 20, so 5 more
    expect(md).not.toContain('file24')  // Beyond the cap
  })

  it('notes unmeasured files', () => {
    const result = {
      status: 'ok',
      score: 0.5,
      mutants_total: 2,
      killed: 1,
      survived: [
        { file: 'lib/lonely.py', line: 5, operator: 'negate', snippet: 'if x' }
      ],
      unmeasured: [
        { file: 'lib/standalone.py', line: 1, operator: 'unknown', snippet: 'def f()' },
        { file: 'lib/other.py', line: 3, operator: 'unknown', snippet: 'def g()' }
      ]
    }

    const md = renderMutationSection(result)

    expect(md).toContain('50%')
    expect(md).toContain('2 file(s) have no test file and were unmeasured')
  })

  it('renders unknown status with reason', () => {
    const result = {
      status: 'unknown',
      score: null,
      mutants_total: 0,
      reason: 'npx not found for JavaScript mutations'
    }

    const md = renderMutationSection(result)

    expect(md).toContain('Could not measure')
    expect(md).toContain('npx not found')
    expect(md).not.toContain('100%')
  })

  it('renders null result as unavailable', () => {
    const md = renderMutationSection(null)

    expect(md).toContain('No mutation check result available')
  })

  it('renders zero mutable lines as clean', () => {
    const result = {
      status: 'ok',
      score: 1.0,
      mutants_total: 0,
      killed: 0,
      survived: [],
      unmeasured: []
    }

    const md = renderMutationSection(result)

    expect(md).toContain('No mutable lines')
    expect(md).toContain('configuration, docs, or test changes')
  })

  it('escapes pipe characters in snippet for markdown table', () => {
    const result = {
      status: 'ok',
      score: 0.5,
      mutants_total: 1,
      killed: 0,
      survived: [
        { file: 'lib/pipe.py', line: 5, operator: 'and', snippet: 'a || b | c' }
      ],
      unmeasured: []
    }

    const md = renderMutationSection(result)

    expect(md).toContain('a || b \\| c')  // Escaped for markdown
  })
})

describe('upsertMutationSection: update PR via gh CLI', () => {
  const PR = 'https://github.com/G-Eskayo/marvin/pull/123'

  it('fetches current body, merges the section, and updates the PR', async () => {
    const currentBody = 'Existing description\n'
    const newSection = 'Mutation: 80%\n'

    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: JSON.stringify({ body: currentBody }) })  // gh pr view
      .mockResolvedValueOnce({})  // gh pr edit

    await upsertMutationSection(PR, newSection, exec)

    expect(exec).toHaveBeenCalledTimes(2)

    // First call: fetch body
    expect(exec).toHaveBeenNthCalledWith(1, 'gh', ['pr', 'view', PR, '--json', 'body'])

    // Second call: update body
    const secondCall = exec.mock.calls[1]
    expect(secondCall[0]).toBe('gh')
    expect(secondCall[1][0]).toBe('pr')
    expect(secondCall[1][1]).toBe('edit')
    expect(secondCall[1][2]).toBe(PR)
    expect(secondCall[1][3]).toBe('--body')
    expect(secondCall[1][4]).toContain('Existing description')
    expect(secondCall[1][4]).toContain('Mutation: 80%')
  })

  it('skips update if the body does not change', async () => {
    const section = 'Mutation: 75%\n'
    const bodyWithSection = [
      'Description',
      '<!-- marvin:mutation-check -->',
      section.trim(),
      '<!-- /marvin:mutation-check -->'
    ].join('\n')

    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: JSON.stringify({ body: bodyWithSection }) })

    await upsertMutationSection(PR, section, exec)

    // Only one call (fetch), no second call (edit)
    expect(exec).toHaveBeenCalledTimes(1)
  })

  it('handles fetch errors gracefully', async () => {
    const exec = vi.fn()
      .mockRejectedValue(new Error('gh pr view failed'))

    // Should not throw
    await expect(upsertMutationSection(PR, 'section', exec)).resolves.toBeUndefined()
  })

  it('handles update errors gracefully', async () => {
    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: JSON.stringify({ body: 'old' }) })
      .mockRejectedValue(new Error('gh pr edit failed'))

    // Should not throw
    await expect(upsertMutationSection(PR, 'new', exec)).resolves.toBeUndefined()
  })

  it('handles malformed JSON response', async () => {
    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: 'not json' })

    // Should not throw
    await expect(upsertMutationSection(PR, 'section', exec)).resolves.toBeUndefined()
  })
})
