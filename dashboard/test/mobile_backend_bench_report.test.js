import { describe, it, expect } from 'vitest'
import { renderStatusMarkdown } from '../mobile-backend/bench_report.js'

describe('bench_report', () => {
  it('renderStatusMarkdown formats leg results with all metrics', () => {
    const results = {
      a: {
        name: 'leg-a',
        pings: {
          count: 10,
          mean: 10.5,
          stddev: 2.1,
          min: 8,
          max: 18,
          p50: 10,
          p95: 15,
          p99: 18
        },
        streams: {
          count: 5,
          mean: 92.3,
          stddev: 8.7,
          min: 80,
          max: 105,
          p50: 92,
          p95: 100,
          p99: 105
        },
        errors: [],
        reorders: 0
      }
    }

    const markdown = renderStatusMarkdown(results)

    expect(markdown).toContain('### Leg A')
    expect(markdown).toContain('**Ping Metrics**')
    expect(markdown).toContain('10.5')
    expect(markdown).toContain('2.10')
    expect(markdown).toContain('**Stream Metrics (Throughput)**')
    expect(markdown).toContain('92.3')
    expect(markdown).toContain('**Reorders**')
    expect(markdown).toContain('0')
  })

  it('renderStatusMarkdown handles unavailable legs', () => {
    const results = {
      b: {
        name: 'leg-b',
        unavailable: 'blocked on quic-stack/direct-leg-auth decision'
      }
    }

    const markdown = renderStatusMarkdown(results)

    expect(markdown).toContain('### Leg B')
    expect(markdown).toContain('**Blocked:**')
    expect(markdown).toContain('quic-stack/direct-leg-auth')
  })

  it('renderStatusMarkdown includes errors when present', () => {
    const results = {
      a: {
        name: 'leg-a',
        pings: { count: 0, mean: 0, stddev: 0, min: 0, max: 0 },
        streams: { count: 0, mean: 0, stddev: 0, min: 0, max: 0 },
        errors: ['connection timeout', 'stream dropped'],
        reorders: 0
      }
    }

    const markdown = renderStatusMarkdown(results)

    expect(markdown).toContain('**Errors**')
    expect(markdown).toContain('connection timeout')
    expect(markdown).toContain('stream dropped')
  })

  it('renderStatusMarkdown formats throughput in Mbps', () => {
    const results = {
      a: {
        name: 'leg-a',
        pings: { count: 1, mean: 10, stddev: 0, min: 10, max: 10 },
        streams: { count: 1, mean: 85.5, stddev: 0, min: 85.5, max: 85.5 },
        errors: [],
        reorders: 0
      }
    }

    const markdown = renderStatusMarkdown(results)

    expect(markdown).toContain('Mbps')
    expect(markdown).toContain('85.5')
  })

  it('renderStatusMarkdown handles multiple legs', () => {
    const results = {
      a: {
        name: 'leg-a',
        pings: { count: 1, mean: 10, stddev: 0, min: 10, max: 10 },
        streams: { count: 1, mean: 90, stddev: 0, min: 90, max: 90 },
        errors: [],
        reorders: 0
      },
      b: {
        name: 'leg-b',
        unavailable: 'blocked'
      }
    }

    const markdown = renderStatusMarkdown(results)

    expect(markdown).toContain('### Leg A')
    expect(markdown).toContain('### Leg B')
  })

  it('renderStatusMarkdown renders percentiles when available', () => {
    const results = {
      a: {
        name: 'leg-a',
        pings: {
          count: 100,
          mean: 10,
          stddev: 2,
          min: 5,
          max: 20,
          p50: 9,
          p95: 15,
          p99: 19
        },
        streams: {
          count: 5,
          mean: 90,
          stddev: 5,
          min: 85,
          max: 95,
          p50: 89,
          p95: 94,
          p99: 95
        },
        errors: [],
        reorders: 0
      }
    }

    const markdown = renderStatusMarkdown(results)

    expect(markdown).toContain('**P50**')
    expect(markdown).toContain('**P95**')
    expect(markdown).toContain('**P99**')
  })
})
