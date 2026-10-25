import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'
import { claimStatusLabel, formatClaimTimestamp, UnregisteredClaims } from '../src/components/PortfolioHub.jsx'

describe('claims ledger view components', () => {
  // Test 16: claimStatusLabel returns 'pass' or 'fail'
  it('claimStatusLabel returns the correct word for status badges', () => {
    expect(claimStatusLabel(true)).toBe('pass')
    expect(claimStatusLabel(false)).toBe('fail')
  })

  // Test 17: formatClaimTimestamp safely handles valid, invalid, and missing timestamps
  it('formatClaimTimestamp safely formats ISO timestamps', () => {
    const isoDate = '2026-10-10T02:30:00+00:00'
    const formatted = formatClaimTimestamp(isoDate)
    expect(formatted).not.toBe('(invalid)')
    expect(formatted).not.toBe('(missing)')
    expect(formatted).toBeTruthy()
  })

  it('formatClaimTimestamp returns (invalid) for unparsable timestamps', () => {
    expect(formatClaimTimestamp('not-a-date')).toBe('(invalid)')
    expect(formatClaimTimestamp(null)).toBe('(missing)')
    expect(formatClaimTimestamp(undefined)).toBe('(missing)')
  })

  // Test 18: UnregisteredClaims renders a list of unregistered ticket identifiers
  it('UnregisteredClaims renders items as a list with the unregistered id', () => {
    const items = ['marvin-97', 'marvin-456']
    const markup = renderToStaticMarkup(React.createElement(UnregisteredClaims, { items }))
    expect(markup).toContain('marvin-97')
    expect(markup).toContain('marvin-456')
    expect(markup).toContain('Unregistered claims')
  })

  it('UnregisteredClaims returns null for empty or missing items', () => {
    const markup1 = renderToStaticMarkup(React.createElement(UnregisteredClaims, { items: [] }))
    const markup2 = renderToStaticMarkup(React.createElement(UnregisteredClaims, { items: null }))
    expect(markup1).toBe('')
    expect(markup2).toBe('')
  })
})
