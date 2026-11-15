// Redact sensitive information from text: home paths, IPs, hostnames, and doc paths
export function redactText(text, { registry } = {}) {
  if (text == null) return ''
  let result = String(text)

  // Redact home paths (macOS /Users/*, Linux /home/*, Windows C:\Users\*)
  result = result.replace(/\/Users\/[^/\s]+/gi, '~')
  result = result.replace(/\/home\/[^/\s]+/gi, '~')
  result = result.replace(/[Cc]:\\users\\[^\\]+/gi, '~')

  // Redact IPv6 addresses (before IPv4 to avoid partial matches)
  result = redactIPv6(result)

  // Redact IPv4 addresses and private IPs
  result = redactIPv4(result, registry)

  // Redact docs/plans and handoff filenames
  result = result.replace(/docs\/plans\/[a-zA-Z0-9_.-]+/g, '(docs/plans)')
  result = result.replace(/handoff-\d{4}-\d{2}-\d{2}(?:-\d{2}-\d{2})?(?:-[a-zA-Z0-9_-]+)?\.md/g, '(handoff)')

  return result
}

function redactIPv6(text) {
  // Match IPv6 patterns: fe80::1, 2001:db8::1, ::1, etc.
  return text.replace(/(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}/g, '***:***:***')
}

function redactIPv4(text, registry = {}) {
  // Split into tokens to check for false positives (duration patterns like 0:05:31)
  const durationPattern = /^\d{1,2}:\d{2}:\d{2}$/
  const ipv4Pattern = /(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/g
  let lastIndex = 0
  let result = ''

  for (const match of text.matchAll(ipv4Pattern)) {
    const [fullMatch, a, b, c, d] = match
    const octets = [parseInt(a), parseInt(b), parseInt(c), parseInt(d)]

    // Validate as real IPv4 (all octets 0-255)
    if (octets.some((n) => n > 255)) {
      // Not a valid IP, skip
      result += text.slice(lastIndex, match.index + fullMatch.length)
      lastIndex = match.index + fullMatch.length
      continue
    }

    // Check for duration false positive (like in "0:05:31" or "2:30:45")
    if (durationPattern.test(fullMatch)) {
      result += text.slice(lastIndex, match.index + fullMatch.length)
      lastIndex = match.index + fullMatch.length
      continue
    }

    // Check registry for hostname/IP mapping: if in registry, always mask to (device)
    let replacement = null
    if (registry && typeof registry === 'object' && registry[fullMatch]) {
      replacement = '(device)'
    } else if (isTailscaleIP(octets)) {
      // Check if this is a Tailscale IP (only Tailscale -> "(device)" without registry)
      replacement = '(device)'
    } else {
      // All other IPs get masked: first 2 octets visible, rest masked
      replacement = `${octets[0]}.${octets[1]}.***.***.***`
    }

    result += text.slice(lastIndex, match.index) + replacement
    lastIndex = match.index + fullMatch.length
  }

  result += text.slice(lastIndex)

  // Also handle registry hostnames directly
  if (registry && typeof registry === 'object') {
    for (const [key] of Object.entries(registry)) {
      if (!key.includes('.') && !key.match(/\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/)) {
        // This looks like a hostname, not an IP
        const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        result = result.replace(new RegExp(`\\b${escapedKey}\\b`, 'g'), '(device)')
      }
    }
  }

  return result
}

function isTailscaleIP(octets) {
  const [a, b] = octets
  // Only Tailscale (100.64-127.x) gets special treatment without registry
  return a === 100 && b >= 64 && b <= 127
}
