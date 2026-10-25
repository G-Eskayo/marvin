export function renderStatusMarkdown(resultsJson) {
  const lines = []

  Object.entries(resultsJson).forEach(([legKey, result]) => {
    if (result.unavailable) {
      lines.push(`### Leg ${legKey.toUpperCase()} (${result.name})`)
      lines.push('')
      lines.push(`**Blocked:** ${result.unavailable}`)
      lines.push('')
      return
    }

    lines.push(`### Leg ${legKey.toUpperCase()} (${result.name})`)
    lines.push('')

    const pings = result.pings
    lines.push('**Ping Metrics**')
    lines.push('')
    lines.push(`- **Mean**: ${pings.mean.toFixed(1)} ms`)
    lines.push(`- **Stddev**: ${pings.stddev.toFixed(2)} ms`)
    lines.push(`- **Min**: ${pings.min} ms`)
    lines.push(`- **Max**: ${pings.max} ms`)
    if (pings.p50 !== undefined) {
      lines.push(`- **P50**: ${pings.p50} ms`)
    }
    if (pings.p95 !== undefined) {
      lines.push(`- **P95**: ${pings.p95} ms`)
    }
    if (pings.p99 !== undefined) {
      lines.push(`- **P99**: ${pings.p99} ms`)
    }
    lines.push('')

    const streams = result.streams
    lines.push('**Stream Metrics (Throughput)**')
    lines.push('')
    lines.push(`- **Mean**: ${streams.mean.toFixed(1)} Mbps`)
    lines.push(`- **Stddev**: ${streams.stddev.toFixed(2)} Mbps`)
    lines.push(`- **Min**: ${streams.min.toFixed(1)} Mbps`)
    lines.push(`- **Max**: ${streams.max.toFixed(1)} Mbps`)
    if (streams.p50 !== undefined) {
      lines.push(`- **P50**: ${streams.p50.toFixed(1)} Mbps`)
    }
    if (streams.p95 !== undefined) {
      lines.push(`- **P95**: ${streams.p95.toFixed(1)} Mbps`)
    }
    if (streams.p99 !== undefined) {
      lines.push(`- **P99**: ${streams.p99.toFixed(1)} Mbps`)
    }
    lines.push('')

    const reorders = result.reorders || 0
    lines.push(`**Reorders**: ${reorders}`)
    lines.push('')

    if (result.errors && result.errors.length > 0) {
      lines.push('**Errors**')
      lines.push('')
      result.errors.forEach((err) => {
        lines.push(`- ${err}`)
      })
      lines.push('')
    }
  })

  return lines.join('\n')
}
