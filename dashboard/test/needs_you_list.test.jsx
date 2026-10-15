import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import NeedsYouList from '../src/components/NeedsYouList.jsx'

const mockOnOpenTicket = vi.fn()
const boards = [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }]

const row = (num, over = {}) => ({
  repo: 'G-Eskayo/marvin',
  number: num,
  title: `Ticket #${num}`,
  url: `https://github.com/G-Eskayo/marvin/issues/${num}`,
  kind: 'ready-for-human',
  unblocks: { count: 0, items: [] },
  ask: 'needs review',
  priority: null,
  ageDays: 5,
  project: { id: 'marvin', repo: 'G-Eskayo/marvin' },
  ...over
})

describe('NeedsYouList', () => {
  beforeEach(() => {
    global.window = global.window || {}
    global.window.api = {
      activity: {
        needsYou: vi.fn()
      },
      triggers: {
        on: vi.fn(() => () => {})
      }
    }
    global.window.localStorage = {
      getItem: () => null,
      setItem: () => {}
    }
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders loading state when no saved data', () => {
    const mockStorage = {
      getItem: () => null,
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )
    expect(html).toContain('Reading what needs you…')
  })

  it('renders empty state when saved data has empty rows array', () => {
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: { rows: [] }
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )
    expect(html).toContain('Nothing needs you')
  })

  it('handles saved envelope missing value.rows (Bug A regression)', () => {
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: {}
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )
    expect(html).toContain('Nothing needs you')
  })

  it('renders populated rows with pill, title, project, ask, unblocks when saved', () => {
    const rows = [
      row(1, {
        title: 'Design the feature',
        priority: 'p0',
        ask: 'review mockups',
        unblocks: { count: 3, items: [] }
      })
    ]
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: { rows }
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )

    expect(html).toContain('Design the feature')
    expect(html).toContain('#1')
    expect(html).toContain('review mockups')
    expect(html).toContain('unblocks 3')
    expect(html).toContain('MARVIN')
  })

  it('shows pill with P0 styling for p0 priority', () => {
    const rows = [row(1, { priority: 'p0' })]
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: { rows }
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )

    expect(html).toContain('needs you (P0)')
    expect(html).toContain('bg-red-950')
  })

  it('handles needs-info kind with "needs answer" text', () => {
    const rows = [row(1, { kind: 'needs-info', title: 'Missing information' })]
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: { rows }
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )

    expect(html).toContain('needs answer')
    expect(html).toContain('Missing information')
  })

  it('renders project name from boards when available', () => {
    const rows = [row(1, { title: 'Task', project: { id: 'clarity', repo: 'G-Eskayo/clarity' } })]
    const customBoards = [{ repo: 'G-Eskayo/clarity', name: 'Clarity Captions' }]
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: { rows }
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={customBoards} onOpenTicket={mockOnOpenTicket} />
    )

    expect(html).toContain('Clarity Captions')
  })

  it('degrades gracefully with malformed saved data', () => {
    const mockStorage = {
      getItem: () => '{ broken json }',
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )

    expect(html).toContain('Reading what needs you…')
  })

  it('renders sort buttons with saved empty data', () => {
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: { rows: [] }
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )

    expect(html).toContain('Most Unblocks')
    expect(html).toContain('Highest Priority')
    expect(html).toContain('Oldest First')
    expect(html).toContain('By Project')
  })

  it('shows pill with P1 styling for p1 priority', () => {
    const rows = [row(1, { priority: 'p1' })]
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: { rows }
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )

    expect(html).toContain('needs you (P1)')
    expect(html).toContain('bg-amber-950')
  })

  it('renders multiple rows with pagination info', () => {
    const rows = Array.from({ length: 11 }, (_, i) => row(i + 1))
    const mockStorage = {
      getItem: (key) => {
        if (key === 'needs-you.list') {
          return JSON.stringify({
            at: Date.now(),
            value: { rows }
          })
        }
        return null
      },
      setItem: () => {}
    }
    global.window.localStorage = mockStorage

    const html = renderToStaticMarkup(
      <NeedsYouList boards={boards} onOpenTicket={mockOnOpenTicket} />
    )

    expect(html).toContain('Page 1 of 3')
    expect(html).toContain('Next')
  })
})
