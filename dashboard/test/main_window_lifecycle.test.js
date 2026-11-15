import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'

// marvin#831 (PR #1029): the main window is set to null when closed, so later sends never hit a destroyed window.
// Code review found must-fix defects that this test would have caught. See github_feed.test.js and polling_guard.test.js
// pattern: static source-text assertions on the real electron/main/index.js (runs app.whenReady() at module load,
// cannot be imported/executed in tests). The 5 assertions below verify that NO defects match these patterns:
// 1. mainWindow.webContents?.send (guard on wrong link; should be mainWindow?.webContents.send)
// 2. mainWindow\n  .webContents.send (split across lines, guard missing)
// 3. const w = mainWindow; w.webContents.send(...) (aliased sends without inline guards)
// 4. unguarded mainWindow.show() / mainWindow.focus() (must use mainWindow?.show/focus or check before use)
// 5. Ensure the fix from PR #1029 is present: mainWindow set to null when window closes

describe('main window lifecycle: close does not leave stale references (#831)', () => {
  const src = readFileSync(new URL('../electron/main/index.js', import.meta.url), 'utf-8')
  const lines = src.split('\n')

  it('no mainWindow.webContents?.send (guard on wrong link) — all sends have guard on mainWindow', () => {
    // Pattern: mainWindow.webContents.send or mainWindow.webContents?.send are wrong.
    // The ? must be on mainWindow, not on webContents.
    // Rejects: mainWindow.webContents.send(...) (no guard) or mainWindow.webContents?.send(...) (guard on wrong link)
    // Allows: mainWindow?.webContents.send(...) (guard on mainWindow)
    const unguardedOrWrongGuard = /\bmainWindow\s*\.\s*webContents\s*\??\s*\.\s*send\s*\(/
    for (let i = 0; i < lines.length; i++) {
      if (unguardedOrWrongGuard.test(lines[i])) {
        expect(lines[i], `line ${i + 1}: send must use mainWindow?.webContents.send, not mainWindow.webContents.send or mainWindow.webContents?.send`).toBe('')
      }
    }
  })

  it('no split-across-lines mainWindow.webContents.send without guard on mainWindow', () => {
    // Pattern: mainWindow\n  .webContents.send where the continuation line lacks the guard
    for (let i = 0; i < lines.length; i++) {
      if (/^\s*\.\s*webContents\s*\.send\s*\(/.test(lines[i])) {
        // This is a continuation from previous line; check that previous line has mainWindow?
        const prevLine = lines[i - 1]
        expect(prevLine, `line ${i}: continuation .webContents.send must follow a guarded mainWindow?. check line ${i}`).toMatch(/mainWindow\?/)
      }
    }
  })

  it('no aliased mainWindow used for show/focus/send without inline guards', () => {
    // Pattern: const w = mainWindow; w.show() or w.focus() or w.webContents.send() without guard
    // Gather all alias assignments (const, let, or var — no semicolon required)
    const aliasRe = /(?:const|let|var)\s+(\w+)\s*=\s*mainWindow\b/
    const aliases = new Set()
    for (let i = 0; i < lines.length; i++) {
      const m = aliasRe.exec(lines[i])
      if (m) aliases.add(m[1])
    }
    // Check that aliased variables are never used for show/focus/webContents.send without guards
    for (let i = 0; i < lines.length; i++) {
      for (const alias of aliases) {
        // Pattern to match show/focus/webContents.send calls on the alias
        const useLine = lines[i]
        // Check if this line uses the alias for unsafe operations
        const showMatch = new RegExp(`\\b${alias}\\s*\\.\\s*show\\s*\\(`).test(useLine)
        const focusMatch = new RegExp(`\\b${alias}\\s*\\.\\s*focus\\s*\\(`).test(useLine)
        const sendMatch = new RegExp(`\\b${alias}\\s*\\.\\s*webContents\\s*\\.\\s*send\\s*\\(`).test(useLine)

        if (showMatch || focusMatch || sendMatch) {
          // Guard can be on same line or on preceding lines checking mainWindow
          const sameLineGuard = /if\s*\(/.test(useLine) || new RegExp(`\\b${alias}\\s*\\?`).test(useLine)
          let precedingGuard = false
          // Check up to 5 preceding lines for a mainWindow guard before the alias assignment
          for (let j = Math.max(0, i - 5); j < i; j++) {
            // Check for mainWindow guards: "if (!mainWindow", "if (mainWindow", "if (... isDestroyed"
            if (/if\s*\(.*!?mainWindow|if\s*\(.*isDestroyed/.test(lines[j])) {
              precedingGuard = true
              break
            }
          }
          expect(
            sameLineGuard || precedingGuard,
            `line ${i + 1}: alias '${alias}' for mainWindow used without guard (show/focus/send must be guarded or use optional chaining)`
          ).toBe(true)
        }
      }
    }
  })

  it('no unguarded mainWindow.show() or mainWindow.focus() calls', () => {
    // Find all show/focus calls
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      // Skip comments and strings
      if (/^\s*(\/\/|\/\*|\*|")/.test(line.trim())) continue
      // Unguarded mainWindow.show() is wrong
      if (/mainWindow\s*\.\s*show\s*\(/.test(line) && !line.includes('mainWindow?.show')) {
        expect(line, `line ${i + 1}: unguarded mainWindow.show()`).toMatch(/mainWindow\?\s*\.show/)
      }
      // Unguarded mainWindow.focus() is wrong
      if (/mainWindow\s*\.\s*focus\s*\(/.test(line) && !line.includes('mainWindow?.focus')) {
        expect(line, `line ${i + 1}: unguarded mainWindow.focus()`).toMatch(/mainWindow\?\s*\.focus/)
      }
    }
  })

  it('PR #1029 fix is present: mainWindow set to null when closed, so later sends never hit destroyed window', () => {
    // The fix captures the created window, attaches a closed listener that sets mainWindow to null, preventing
    // stale handlers from clobbering later recreations (macOS: the app keeps running with show windows open).
    expect(src).toContain('const created = mainWindow')
    expect(src).toContain("created.on('closed'")
    expect(src).toContain('if (mainWindow === created) mainWindow = null')
  })
})
