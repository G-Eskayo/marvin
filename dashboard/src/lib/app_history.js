// History navigation for the Workshop tab: keyboard shortcuts (Cmd/Ctrl+[, Cmd/Ctrl+]) trigger back/forward.
// Built on nav_history.js's back/forward primitives.
//
//   historyKeyAction(e)         -> 'back' | 'forward' | null (from keydown event)
//   applyHistoryKey(action, h)  -> updated history or null if edge

import { back, forward } from './nav_history.js'

export function historyKeyAction(e) {
  // Skip editable targets: Cmd/Ctrl+⌫ is "delete to line start" on macOS, so don't interfere with text input.
  if (e.target.isContentEditable || e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
    return null
  }
  // Cmd/Ctrl+[ = back, Cmd/Ctrl+] = forward (macOS browser convention)
  if ((e.metaKey || e.ctrlKey) && e.key === '[' && !e.shiftKey) return 'back'
  if ((e.metaKey || e.ctrlKey) && e.key === ']' && !e.shiftKey) return 'forward'
  return null
}

export function applyHistoryKey(action, history) {
  // history is a nav_history structure { entries, index }.
  // action is 'back' or 'forward'.
  // Returns { history, screen } or null if at edge.
  if (!history || !action) return null
  const result = action === 'back' ? back(history) : forward(history)
  return result.screen ? { history: result.history, screen: result.screen } : null
}
