import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AddonNotSetUp } from '../src/components/AddonNotSetUp'

describe('AddonNotSetUp', () => {
  it('renders portfolio add-on correctly (item 10)', () => {
    const onEnable = vi.fn()
    render(<AddonNotSetUp addon="portfolio" onEnable={onEnable} />)

    expect(screen.getByText('Portfolio')).toBeInTheDocument()
    expect(screen.getByText('Project portfolio and web updates')).toBeInTheDocument()
  })

  it('renders resume_tailor add-on correctly', () => {
    const onEnable = vi.fn()
    render(<AddonNotSetUp addon="resume_tailor" onEnable={onEnable} />)

    expect(screen.getByText('Resume Tailor')).toBeInTheDocument()
    expect(screen.getByText('Job application packages and resume tailoring')).toBeInTheDocument()
  })

  it('renders seal_ingest add-on correctly', () => {
    const onEnable = vi.fn()
    render(<AddonNotSetUp addon="seal_ingest" onEnable={onEnable} />)

    expect(screen.getByText('Seal Ingest')).toBeInTheDocument()
    expect(screen.getByText('Seal Speak beta feedback collection')).toBeInTheDocument()
  })

  it('shows enable button that calls onEnable with addon name', async () => {
    const onEnable = vi.fn()
    const user = userEvent.setup()
    render(<AddonNotSetUp addon="portfolio" onEnable={onEnable} />)

    const button = screen.getByRole('button', { name: /enable add-on/i })
    await user.click(button)

    expect(onEnable).toHaveBeenCalledWith('portfolio')
  })

  it('displays manual setup instructions', () => {
    const onEnable = vi.fn()
    render(<AddonNotSetUp addon="portfolio" onEnable={onEnable} />)

    expect(screen.getByText(/\.agents\/instance\/instance\.json/)).toBeInTheDocument()
    expect(screen.getByText(/features\.portfolio/)).toBeInTheDocument()
  })

  it('shows error for unknown addon', () => {
    const onEnable = vi.fn()
    render(<AddonNotSetUp addon="unknown" onEnable={onEnable} />)

    expect(screen.getByText(/Unknown add-on: unknown/)).toBeInTheDocument()
  })

  it('shared component used by gated wrapper (item 9)', () => {
    // AddonNotSetUp is a reusable component that wrappers like PortfolioHubGate use
    // to gate access to disabled add-ons. This test verifies it renders properly.
    expect(typeof AddonNotSetUp).toBe('function')

    const onEnable = vi.fn()
    render(<AddonNotSetUp addon="portfolio" onEnable={onEnable} />)

    expect(screen.getByText('Portfolio')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /enable add-on/i })).toBeInTheDocument()
  })
})
