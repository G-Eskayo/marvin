import { describe, it, expect } from 'vitest'
import { parseHumanTask, HUMAN_TASK_FIELDS } from '../src/lib/human_task.js'

const GOOD = `## What to build
Check it.

## Your task
**What I need from you:** the list of speech languages.
**Where:** your iPhone, Settings > Speech languages.
**How:**
1. Install the build.
2. Tap Copy.
**What to send back:** paste it as a reply here.

## Acceptance criteria
- [ ] done
`

describe('parseHumanTask', () => {
  it('reads the four fields of a Your task section', () => {
    const t = parseHumanTask(GOOD)
    expect(t.found).toBe(true)
    expect(t.missing).toEqual([])
    expect(t.fields['What I need from you']).toBe('the list of speech languages.')
    expect(t.fields.How).toContain('1. Install the build.')
    expect(t.fields.How).not.toContain('paste it')
    expect(t.fields['What to send back']).toBe('paste it as a reply here.')
  })

  it('names what is missing, and says so when there is no section at all', () => {
    expect(parseHumanTask('## What to build\nx').found).toBe(false)
    expect(parseHumanTask('## What to build\nx').missing).toEqual(HUMAN_TASK_FIELDS)
    expect(parseHumanTask(GOOD.replace('**Where:** your iPhone, Settings > Speech languages.\n', '')).missing).toEqual(['Where'])
    expect(parseHumanTask(null).found).toBe(false)
  })
})
