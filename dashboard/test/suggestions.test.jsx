import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SuggestionsPage, { SuggestionRow, SuggestionDetail } from '../src/components/SuggestionsPage.jsx'

describe('SuggestionRow', () => {
  it('renders title and metadata (priority, status, impact, effort)', () => {
    const entry = {
      title: 'Test Suggestion',
      priority: 3,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: 'Body text'
    }
    const html = renderToStaticMarkup(
      <SuggestionRow entry={entry} isSelected={false} isResolved={false} onClick={() => {}} />
    )
    expect(html).toContain('Test Suggestion')
    expect(html).toContain('P3')
    expect(html).toContain('pending')
    expect(html).toContain('speed')
    expect(html).toContain('low')
  })

  it('renders pending row without muted class', () => {
    const entry = {
      title: 'Pending Entry',
      priority: 1,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(
      <SuggestionRow entry={entry} isSelected={false} isResolved={false} onClick={() => {}} />
    )
    expect(html).toContain('text-neutral-300')
    expect(html).not.toContain('text-neutral-600')
  })

  it('renders resolved row with muted class', () => {
    const entry = {
      title: 'Resolved Entry',
      priority: 1,
      status: 'resolved',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(
      <SuggestionRow entry={entry} isSelected={false} isResolved={true} onClick={() => {}} />
    )
    expect(html).toContain('text-neutral-600')
  })

  it('renders selected row with background highlight', () => {
    const entry = {
      title: 'Selected Entry',
      priority: 1,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(
      <SuggestionRow entry={entry} isSelected={true} isResolved={false} onClick={() => {}} />
    )
    expect(html).toContain('bg-neutral-800')
  })

  it('omits priority when null', () => {
    const entry = {
      title: 'No Priority',
      priority: null,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(
      <SuggestionRow entry={entry} isSelected={false} isResolved={false} onClick={() => {}} />
    )
    expect(html).not.toMatch(/P\d/)
    expect(html).toContain('No Priority')
  })

  it('omits impact when null', () => {
    const entry = {
      title: 'No Impact',
      priority: 1,
      status: 'pending',
      impact: null,
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(
      <SuggestionRow entry={entry} isSelected={false} isResolved={false} onClick={() => {}} />
    )
    expect(html).not.toContain('speed')
    expect(html).not.toContain('organization')
  })

  it('omits effort when null', () => {
    const entry = {
      title: 'No Effort',
      priority: 1,
      status: 'pending',
      impact: 'speed',
      effort: null,
      body: 'Body'
    }
    const html = renderToStaticMarkup(
      <SuggestionRow entry={entry} isSelected={false} isResolved={false} onClick={() => {}} />
    )
    // Check that effort values don't appear as separate span elements (but "medium" might be in class names)
    expect(html).not.toMatch(/<span[^>]*>low<\/span>/)
    expect(html).not.toMatch(/<span[^>]*>medium<\/span>/)
    expect(html).not.toMatch(/<span[^>]*>high<\/span>/)
  })

  it('formats impact labels (hyphen to space)', () => {
    const entry = {
      title: 'Token Reduction',
      priority: 1,
      status: 'pending',
      impact: 'token-reduction',
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(
      <SuggestionRow entry={entry} isSelected={false} isResolved={false} onClick={() => {}} />
    )
    expect(html).toContain('token reduction')
    expect(html).not.toContain('token-reduction')
  })

  it('applies status color based on status value', () => {
    const pending = {
      title: 'Pending',
      priority: 1,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }
    const resolved = {
      title: 'Resolved',
      priority: 1,
      status: 'resolved',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }

    const pendingHtml = renderToStaticMarkup(
      <SuggestionRow entry={pending} isSelected={false} isResolved={false} onClick={() => {}} />
    )
    const resolvedHtml = renderToStaticMarkup(
      <SuggestionRow entry={resolved} isSelected={false} isResolved={true} onClick={() => {}} />
    )

    expect(pendingHtml).toContain('text-white')
    expect(resolvedHtml).toContain('text-neutral-500')
  })
})

describe('SuggestionDetail', () => {
  it('renders title and metadata', () => {
    const entry = {
      title: 'Test Entry',
      priority: 2,
      status: 'pending',
      impact: 'speed',
      effort: 'medium',
      body: 'Body text'
    }
    const html = renderToStaticMarkup(<SuggestionDetail entry={entry} />)
    expect(html).toContain('Test Entry')
    expect(html).toContain('Priority: 2')
    expect(html).toContain('Status: pending')
    expect(html).toContain('Impact: speed')
    expect(html).toContain('Effort: medium')
  })

  it('formats impact labels (hyphen to space)', () => {
    const entry = {
      title: 'Test',
      priority: 1,
      status: 'pending',
      impact: 'token-reduction',
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(<SuggestionDetail entry={entry} />)
    expect(html).toContain('Impact: token reduction')
  })

  it('omits metadata fields when null', () => {
    const entry = {
      title: 'Minimal',
      priority: null,
      status: 'pending',
      impact: null,
      effort: null,
      body: 'Body'
    }
    const html = renderToStaticMarkup(<SuggestionDetail entry={entry} />)
    expect(html).toContain('Minimal')
    expect(html).not.toContain('Priority:')
    expect(html).not.toContain('Impact:')
    expect(html).not.toContain('Effort:')
  })

  it('shows resolved note for non-pending status', () => {
    const entry = {
      title: 'Done Entry',
      priority: 1,
      status: 'resolved',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(<SuggestionDetail entry={entry} />)
    expect(html).toContain('This suggestion has been resolved')
  })

  it('does not show resolved note for pending status', () => {
    const entry = {
      title: 'Pending Entry',
      priority: 1,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }
    const html = renderToStaticMarkup(<SuggestionDetail entry={entry} />)
    expect(html).not.toContain('This suggestion has been')
  })

  it('renders body text', () => {
    const entry = {
      title: 'Test',
      priority: 1,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: 'This is the body text content'
    }
    const html = renderToStaticMarkup(<SuggestionDetail entry={entry} />)
    expect(html).toContain('This is the body text content')
  })

  it('renders large body without truncation', () => {
    const largeBody = 'Start: ' + 'x'.repeat(5000) + ' :End'
    const entry = {
      title: 'Large Body',
      priority: 1,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: largeBody
    }
    const html = renderToStaticMarkup(<SuggestionDetail entry={entry} />)
    expect(html).toContain('Start:')
    expect(html).toContain(':End')
  })

  it('applies correct status color', () => {
    const pending = {
      title: 'P',
      priority: 1,
      status: 'pending',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }
    const resolved = {
      title: 'R',
      priority: 1,
      status: 'resolved',
      impact: 'speed',
      effort: 'low',
      body: 'Body'
    }

    const pendingHtml = renderToStaticMarkup(<SuggestionDetail entry={pending} />)
    const resolvedHtml = renderToStaticMarkup(<SuggestionDetail entry={resolved} />)

    // Pending should have the status in white
    expect(pendingHtml).toContain('text-white')
    // Resolved should have the status in neutral-500
    expect(resolvedHtml).toContain('text-neutral-500')
  })
})

describe('SuggestionsPage loading state', () => {
  it('renders loading state before IPC resolves', () => {
    // Note: useEffect doesn't run during SSR, so we only test the initial loading state
    const html = renderToStaticMarkup(<SuggestionsPage />)
    expect(html).toContain('Loading suggestions')
  })
})
