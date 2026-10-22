// Hold labels: tickets with these are paused waiting for a person.
// Mirrors lib/ticket_policy.py's HOLD_LABELS constant.

export const HOLD_LABELS = new Set(['pinned', 'hold', 'held']);

export function isHeld(labels) {
  if (!Array.isArray(labels)) {
    return false;
  }
  return labels.some((l) => {
    const name = typeof l === 'string' ? l : l.name;
    return HOLD_LABELS.has(name);
  });
}
