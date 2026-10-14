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
