// Labels that indicate a ticket is on hold, not to be dispatched or sent back
export const HOLD_LABELS = new Set(['pinned', 'hold', 'held']);

export function isHeld(labels) {
  return labels && labels.some(l => HOLD_LABELS.has(l?.name || l));
}
