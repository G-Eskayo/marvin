// Determines if a session should rotate based on length or topic shift
export function shouldRotate({
  sessionMessages,
  newMessageText,
  lengthThreshold,
  topicShiftFn
} = {}) {
  // Check length first
  if (sessionMessages.length >= lengthThreshold) {
    return {
      rotate: true,
      reason: `Reached message length threshold (${sessionMessages.length} >= ${lengthThreshold})`
    }
  }

  // Then check topic shift
  const topicResult = topicShiftFn()
  if (topicResult.shift) {
    return {
      rotate: true,
      reason: 'Detected topic shift'
    }
  }

  return {
    rotate: false,
    reason: null
  }
}

// Detects topic shift using word overlap heuristic
export function detectTopicShift(
  sessionMessages,
  newMessageText,
  { windowSize = 2, threshold = 0.3 } = {}
) {
  if (sessionMessages.length === 0) {
    return { shift: false, score: 1.0 }
  }

  // Get last windowSize messages
  const window = sessionMessages.slice(Math.max(0, sessionMessages.length - windowSize))
  const windowText = window.map(m => m.text).join(' ')

  // Extract words (lowercase, alphanumeric only)
  const extractWords = (text) => {
    return text
      .toLowerCase()
      .split(/\W+/)
      .filter(w => w.length > 0)
  }

  const windowWords = new Set(extractWords(windowText))
  const newWords = new Set(extractWords(newMessageText))

  // Calculate overlap: fraction of new message words that appear in window
  // This measures how related the new message is to the recent context
  const intersection = [...newWords].filter(w => windowWords.has(w))
  const score = newWords.size === 0 ? 1.0 : intersection.length / newWords.size

  return {
    shift: score < threshold,
    score
  }
}

// Naive summary generation by concatenating messages
export function summarize(sessionMessages, { maxLen = 500 } = {}) {
  if (sessionMessages.length === 0) {
    return ''
  }

  let summary = ''
  for (const msg of sessionMessages) {
    const line = `${msg.role}: ${msg.text}\n`
    if ((summary + line).length > maxLen) {
      summary += line.substring(0, maxLen - summary.length)
      break
    }
    summary += line
  }

  return summary.substring(0, maxLen)
}
