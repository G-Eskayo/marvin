export const MESSAGE_FADE_MS = 4000

export function messageExpired(setAt, now) {
  if (!setAt) return false
  const setAtMs = typeof setAt === 'number' ? setAt : setAt.getTime()
  const nowMs = typeof now === 'number' ? now : now.getTime()
  const elapsed = nowMs - setAtMs
  return elapsed >= MESSAGE_FADE_MS
}
