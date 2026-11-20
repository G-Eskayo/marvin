import { posix as pathPosix } from 'path'
// Evidence-capture mode (G-Eskayo/marvin#384). The MR pipeline's screenshot step
// (dashboard/scripts/capture_screenshot.mjs) launches a throwaway copy of this app
// with MARVIN_EVIDENCE_CAPTURE=1. That copy runs unattended next to Gil's real
// dashboard, so a main-process exception must land in a log, never in a modal
// "A JavaScript error occurred in the main process" dialog on his screen.
export function isEvidenceCapture(env) {
  return typeof env?.MARVIN_EVIDENCE_CAPTURE === 'string' && env.MARVIN_EVIDENCE_CAPTURE.trim() === '1'
}

function describe(err) {
  if (err instanceof Error) return err.stack || err.message
  return String(err)
}

export function installCaptureGuard(proc = process, log = console.error) {
  const safeLog = (line) => {
    try {
      log(line)
    } catch {
      // nothing left to tell; the point is not to raise
    }
  }
  proc.on('uncaughtException', (err) => safeLog(`[evidence capture] uncaught main-process exception: ${describe(err)}`))
  proc.on('unhandledRejection', (err) => safeLog(`[evidence capture] unhandled rejection in main process: ${describe(err)}`))
}

// A path a capture run may point the app at instead of Gil's own (marvin#873: the Vitals mock-up's captures read the
// worktree's generated map and the Mac mini's saved accounts sweep). Honoured only in evidence-capture mode and only as
// an absolute path, normalised; anything else is null and the app uses its usual path.
export function captureOverride(env, name) {
  if (!isEvidenceCapture(env)) return null
  const v = env?.[name]
  if (typeof v !== 'string' || !v.startsWith('/')) return null
  return pathPosix.normalize(v)
}
