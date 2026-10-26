// Stateful accumulator for text that emits complete sentences
export function createSentenceStream() {
  let buffer = ''

  return {
    // Push delta text and return array of complete sentences
    push(deltaText) {
      if (!deltaText) return []

      buffer += deltaText
      const sentences = []

      // Match sentences ending with . ? or ! followed by space, or at buffer end
      // Use a simple regex approach: find all "words...punctuation" patterns
      const sentencePattern = /[.!?]\s+/g

      let lastIndex = 0
      let match

      while ((match = sentencePattern.exec(buffer)) !== null) {
        const endIndex = match.index + 1 // Position of the punctuation
        const sentence = buffer.substring(lastIndex, endIndex).trim()

        if (sentence) {
          sentences.push(sentence)
        }

        lastIndex = match.index + match[0].length // Move past the punctuation and space
      }

      // Keep the remaining text in buffer
      buffer = buffer.substring(lastIndex)

      return sentences
    },

    // Return trailing fragment and clear state
    flush() {
      const trimmed = buffer.trim()
      buffer = ''
      return trimmed || null
    }
  }
}
