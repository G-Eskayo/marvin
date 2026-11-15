// Fade message helper: message auto-clears after MESSAGE_FADE_MS
export const MESSAGE_FADE_MS = 4000

// Returns a function that schedules a message to fade. Component must manage timeoutRef.
export function createFadingMessage() {
  return (setState, timeoutRef, newState) => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    setState(newState)
    if (newState?.message) {
      timeoutRef.current = setTimeout(() => {
        setState({ message: null, error: false })
      }, MESSAGE_FADE_MS)
    }
  }
}
