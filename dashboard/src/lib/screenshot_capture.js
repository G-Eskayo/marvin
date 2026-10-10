// Find the real content page from a browser window list.
// A fresh Electron window typically shows about:blank first, then loads
// the app. Return the first page with a non-empty URL that isn't devtools.

// Env for the throwaway app copy capture_screenshot.mjs launches (G-Eskayo/marvin#384):
// an ephemeral refresh port so it can never collide with (or stand in for) Gil's
// installed dashboard on 7879, and the evidence-capture flag so its main process
// logs exceptions instead of popping a modal dialog.
export function captureLaunchEnv(baseEnv = {}) {
  const env = {}
  for (const [k, v] of Object.entries(baseEnv)) if (v !== undefined) env[k] = v
  env.MARVIN_DASHBOARD_REFRESH_PORT = '0'
  env.MARVIN_EVIDENCE_CAPTURE = '1'
  return env
}

export function selectContentPage(pages) {
  return pages.find((p) => {
    const url = p.url?.() || ''
    return url && !url.startsWith('devtools://')
  }) || null
}
