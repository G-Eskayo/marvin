// reviewTarget(key): determine navigation target for a review link.
// A bare-repo target (repo only, no PR) navigates to workshop with a project filter.
// A repo#number target opens the PR in the workshop.
export function reviewTarget(key) {
  if (!key) return null
  const str = String(key)
  const m = /^(.+)#(\d+)$/.exec(str)
  if (m) {
    // repo#number: open the PR
    return { item: { repo: m[1], pr: Number(m[2]) } }
  }
  // Bare repo: open workshop with project filter
  return { projectFilter: str }
}

// createOpenPrKey(navigate): creates a handler for opening a PR key (repo or repo#number).
// Used by App.jsx's openPrKey and testable independently.
export function createOpenPrKey(navigate) {
  return (prKey) => {
    const target = reviewTarget(prKey)
    if (!target) {
      navigate('workshop')
      return
    }
    if (target.projectFilter) {
      navigate('workshop', { projectFilter: target.projectFilter })
    } else {
      navigate('workshop', { item: target.item })
    }
  }
}
