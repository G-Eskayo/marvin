// Convert text to a speakable form: strip markdown, remove URLs, enforce short-reply cap.
// Patterned after docs_text.js's plain() regex approach.

const SHORT_REPLY_CAP = 500

export function toSpeakable(text) {
  if (!text) return ''

  let result = text
    // Remove markdown links and images: ![alt](url) or [text](url)
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    // Remove standalone URLs (http/https)
    .replace(/https?:\/\/[^\s]+/g, '')
    // Remove markdown formatting: backticks, asterisks, underscores, hashes
    .replace(/[`*_#]/g, '')
    .trim()

  // Enforce short-reply length cap
  if (result.length > SHORT_REPLY_CAP) {
    result = result.substring(0, SHORT_REPLY_CAP - 3) + '...'
  }

  return result
}
