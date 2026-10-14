// Small decisions the boot sequence's view makes (#431), kept pure so they can be tested without a DOM.

// Play only when the main process says this is the launch's first load, the person hasn't asked the OS to
// reduce motion, and the renderer can actually animate (Web Animations API).
export function shouldPlay({ show, reducedMotion, canAnimate }) {
  return Boolean(show) && !reducedMotion && Boolean(canAnimate)
}

// The verdict banner's look follows the verdict's tone; anything unexpected looks "unknown", never nominal.
export function bannerTone(verdict) {
  if (verdict?.nominal === true && verdict.tone === 'nominal') return 'nominal'
  return verdict?.tone === 'issues' ? 'issues' : 'unknown'
}

// Summary-line colours: real levels map to their colour; LOCK/PLOT-style lines use the accent; anything else
// is a warning colour, so an unexpected value never shows as green.
export function lineTone(level) {
  return { green: 'green', yellow: 'yellow', red: 'red', lock: 'lock' }[level] ?? 'yellow'
}

// Clickable items (#433). A line is clickable only when boot_data gave it a target on a tab the boot can open;
// anything else (LOCK, OK, PLOT, malformed targets) stays inert, so nothing glows that does nothing.
const BOOT_TABS = new Set(['health'])
export function lineTarget(line) {
  const t = line?.target
  if (!t || !BOOT_TABS.has(t.tab)) return null
  return typeof t.check === 'string' && t.check ? { tab: t.tab, check: t.check } : { tab: t.tab }
}

// The verdict banner leads to Health only when there's something to look at.
export function bannerTarget(verdict) {
  return bannerTone(verdict) === 'nominal' ? null : { tab: 'health' }
}

// Which check the Health tab should land on and flash, from a navigation request.
export function healthFocus(nav) {
  return nav?.tab === 'health' && typeof nav.check === 'string' && nav.check ? nav.check : null
}
