import { describe, it, expect } from 'vitest'
import { notebookToMarkdown, isNotebookPath } from '../src/lib/ipynb.js'

const nb = (cells, extra = {}) =>
  JSON.stringify({ nbformat: 4, metadata: { kernelspec: { language: 'python' }, ...extra }, cells })

describe('isNotebookPath', () => {
  it('recognises notebooks by extension only', () => {
    expect(isNotebookPath('analysis.ipynb')).toBe(true)
    expect(isNotebookPath('docs/Notes.IPYNB')).toBe(true)
    expect(isNotebookPath('README.md')).toBe(false)
    expect(isNotebookPath(null)).toBe(false)
  })
})

describe('notebookToMarkdown', () => {
  it('passes markdown cells through and fences code cells with the notebook language', () => {
    const md = notebookToMarkdown(nb([
      { cell_type: 'markdown', source: ['# Title\n', 'Some *text*'] },
      { cell_type: 'code', source: 'x = 1\nprint(x)', outputs: [] }
    ]))
    expect(md).toContain('# Title\nSome *text*')
    expect(md).toContain('```python\nx = 1\nprint(x)\n```')
  })

  it('shows text outputs as fenced blocks, one per output', () => {
    const md = notebookToMarkdown(nb([
      { cell_type: 'code', source: 'print(1)', outputs: [{ output_type: 'stream', name: 'stdout', text: ['1\n'] }] }
    ]))
    expect(md).toContain('```text\n1\n```')
  })

  it('turns image outputs into inline data-URI images', () => {
    const png = 'iVBORw0KGgo=\n'
    const md = notebookToMarkdown(nb([
      { cell_type: 'code', source: 'plot()', outputs: [{ output_type: 'display_data', data: { 'image/png': png, 'text/plain': ['<Figure>'] } }] }
    ]))
    expect(md).toContain('![output](data:image/png;base64,iVBORw0KGgo=)')
    expect(md).not.toContain('<Figure>')
  })

  it('falls back to text/plain for tables (html is not rendered) and prefers it over html', () => {
    const md = notebookToMarkdown(nb([
      { cell_type: 'code', source: 'df', outputs: [{ output_type: 'execute_result', data: { 'text/html': '<table></table>', 'text/plain': ['   a  b\n0  1  2'] } }] }
    ]))
    expect(md).toContain('```text\n   a  b\n0  1  2\n```')
    expect(md).not.toContain('<table>')
  })

  it('strips ANSI colour codes from tracebacks and keeps the error name', () => {
    const md = notebookToMarkdown(nb([
      { cell_type: 'code', source: '1/0', outputs: [{ output_type: 'error', ename: 'ZeroDivisionError', evalue: 'division by zero', traceback: ['\u001b[0;31mZeroDivisionError\u001b[0m: division by zero'] }] }
    ]))
    expect(md).toContain('ZeroDivisionError: division by zero')
    expect(md).not.toContain('\u001b')
  })

  it('uses a longer fence when the content itself contains backticks', () => {
    const md = notebookToMarkdown(nb([{ cell_type: 'code', source: 'print("```")', outputs: [] }]))
    expect(md).toContain('````python')
  })

  it('truncates very long text outputs and says how much was cut', () => {
    const long = Array.from({ length: 300 }, (_, i) => `line ${i}`).join('\n')
    const md = notebookToMarkdown(nb([{ cell_type: 'code', source: 'x', outputs: [{ output_type: 'stream', name: 'stdout', text: long }] }]))
    expect(md).toContain('line 79')
    expect(md).not.toContain('line 200')
    expect(md).toMatch(/220 more lines/)
  })

  it('skips empty cells and widget outputs', () => {
    const md = notebookToMarkdown(nb([
      { cell_type: 'code', source: '', outputs: [] },
      { cell_type: 'code', source: 'w', outputs: [{ output_type: 'display_data', data: { 'application/vnd.jupyter.widget-view+json': {} } }] }
    ]))
    expect(md).not.toContain('```python\n\n```')
    expect(md).not.toContain('widget')
  })

  it('reports an unreadable file instead of throwing', () => {
    expect(notebookToMarkdown('not json')).toMatch(/could not be read/i)
    expect(notebookToMarkdown('{"cells": 5}')).toMatch(/could not be read/i)
  })

  it('can leave images out (for the search index)', () => {
    const md = notebookToMarkdown(nb([
      { cell_type: 'code', source: 'plot()', outputs: [{ output_type: 'display_data', data: { 'image/png': 'AAAA', 'text/plain': ['<Figure size 1x1>'] } }] }
    ]), { images: false })
    expect(md).not.toContain('data:image')
  })
})
