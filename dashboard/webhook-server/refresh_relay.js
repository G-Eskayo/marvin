// Forwards a "something changed" ping from the webhook-server (always
// running on this machine via launchd, reachable at a fixed port
// regardless of whether the Electron app happens to be open) to the
// Electron app's own tiny local refresh port, so an already-open dashboard
// updates immediately instead of waiting on its own fallback poll.
//
// Best-effort by design: the Electron app may not be running on this
// machine at all (dispatch can happen on either machine, but the dashboard
// may only be open on one of them), or a ticket may be raising this PR
// from the other machine entirely -- either way, a failed forward here
// must never surface as an error to whoever POSTed /mr-ready.
export async function forwardRefreshPing(url, post) {
  try {
    await post(url, {})
  } catch {
    // Electron app isn't running locally, or not reachable yet -- expected,
    // not exceptional. The dashboard's own fallback poll still covers this.
  }
}
