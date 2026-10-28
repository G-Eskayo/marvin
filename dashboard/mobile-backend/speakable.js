// Convert markdown text to plain text suitable for text-to-speech
export function toSpeakable(text) {
  if (!text) return ''

  // Remove markdown links [text](url) -> text
  let result = text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')

  // Remove inline code markers `code` -> code
  result = result.replace(/`([^`]+)`/g, '$1')

  // Remove bold **text** -> text
  result = result.replace(/\*\*([^*]+)\*\*/g, '$1')

  // Remove italic *text* -> text or _text_ -> text
  result = result.replace(/[*_]([^*_]+)[*_]/g, '$1')

  // Remove headers (# text -> text)
  result = result.replace(/^#+\s+/gm, '')

  // Remove code fences (```...```)
  result = result.replace(/```[^`]*```/gs, '')

  // Clean up extra whitespace
  result = result.replace(/\s+/g, ' ').trim()

  return result
}

// Stream text as complete sentences
export function createSentenceStreamer() {
  let buffer = ''
  let isFinished = false

  return {
    // Add text to the buffer
    push(chunk) {
      if (isFinished) return []
      buffer += chunk
      return this.flush(false)
    },

    // Get complete sentences from buffer
    flush(final = false) {
      const sentences = []

      // Match sentence endings: period, question mark, exclamation
      // followed by whitespace (or end of string if final=true)
      const sentenceRegex = /([^.!?]*[.!?]+)(\s+|$)/g

      let match
      let lastIndex = 0

      while ((match = sentenceRegex.exec(buffer)) !== null) {
        const sentence = match[1].trim()
        if (sentence) {
          sentences.push(sentence)
        }
        lastIndex = match.index + match[0].length
      }

      // Update buffer with unmatched text
      buffer = buffer.substring(lastIndex)

      // If final, emit any remaining text as a sentence
      if (final && buffer.trim()) {
        sentences.push(buffer.trim())
        buffer = ''
      }

      return sentences
    },

    // Mark end of stream and get remaining text
    finish() {
      isFinished = true
      return this.flush(true)
    }
  }
}
