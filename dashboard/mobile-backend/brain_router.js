// Route voice queries to appropriate brain (fast or deep)
// Provisional: Option A, always deep (pending owner's decision)
export async function chooseBrain(text, opts = {}) {
  // TODO: Implement decision-based routing when owner provides direction
  // For now, always choose deep brain (Option A)

  return {
    type: 'deep',
    name: 'Deep Brain',
    model: 'claude-haiku-4-5-20251001'
  }
}
