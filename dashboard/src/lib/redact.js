export function redactPrivate(text) {
  if (typeof text !== 'string') return text

  // Redact IPv6 addresses: must have hex digits (a-f) to distinguish from timestamps
  // Matches either :: form or full 8 groups, but requires hex letters to avoid matching "12:30:45" or "a :: b"
  text = text.replace(/\b(?:[0-9a-fA-F]{0,4}:)+[0-9a-fA-F]{0,4}\b/g, (match) => {
    // Only redact if: has hex letters (a-f) OR has :: (compressed form)
    // This prevents matching MAC addresses, timestamps, and natural language
    if (/[a-fA-F]/.test(match) || match.includes('::')) {
      return '[IPv6]'
    }
    return match
  })

  // Redact IPv4 addresses: patterns like 192.168.1.1
  text = text.replace(/\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b/g, '[IPv4]')

  // Redact /Users/<name> to ~
  text = text.replace(/\/Users\/[^/\s]+/g, '~')

  // Redact docs/plans/<slug>.md to docs/plans/…
  text = text.replace(/docs\/plans\/[^\s/]+\.md/g, 'docs/plans/…')

  return text
}
