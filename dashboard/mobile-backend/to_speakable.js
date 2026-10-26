// Convert markdown-heavy text to plain speech-friendly text
// Strips: bold/italic/headers/lists/code blocks, converts links, removes bare URLs
export function toSpeakable(text) {
  if (!text) return ''

  let result = text

  // Strip markdown bold/italic: **text** and *text*
  result = result.replace(/\*\*(.+?)\*\*/g, '$1')
  result = result.replace(/\*(.+?)\*/g, '$1')

  // Strip markdown headers: # Header -> Header
  result = result.replace(/^#+\s+(.+?)$/gm, '$1')

  // Strip markdown lists: - Item -> Item
  result = result.replace(/^\s*[-*]\s+(.+?)$/gm, '$1')

  // Strip code fences: ```language\ncode\n``` -> code (remove fence and language identifier)
  result = result.replace(/```[\w]*\n([\s\S]*?)\n```/g, '$1')

  // Strip inline code backticks: `code` -> code
  result = result.replace(/`(.+?)`/g, '$1')

  // Convert markdown links: [text](url) -> text
  result = result.replace(/\[(.+?)\]\(.+?\)/g, '$1')

  // Strip bare URLs (http/https)
  result = result.replace(/https?:\/\/[^\s]+/g, '')

  // Collapse multiple spaces within lines
  result = result.replace(/ +/g, ' ')

  // Collapse multiple consecutive newlines (keep max 1 blank line = 2 newlines)
  result = result.replace(/\n\n\n+/g, '\n\n')

  // Trim leading/trailing whitespace
  result = result.trim()

  return result
}
