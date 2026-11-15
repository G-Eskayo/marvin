// Check if a PR is still in a given list (matched by URL)
export function stillInList(pr, list) {
  if (!pr || !list) return false
  return list.some((p) => p.url === pr.url)
}

// Recheck a PR's status in merged history when it vanishes from the open list
export function recheckVanished(url, historyDetail) {
  if (!url || !historyDetail) return Promise.resolve(null)
  return historyDetail(url)
    .then((result) => {
      if (!result) return null
      const closed = result.state === 'CLOSED' || result.state === 'MERGED'
      return closed ? result : null
    })
    .catch(() => null)
}

// Apply the recheck result to update the selected PR
export function applyRecheck(selected, asked, fresh) {
  if (!fresh || !selected) return selected
  if (asked !== null && asked !== undefined && selected !== asked) return selected
  return {
    ...selected,
    readOnly: true,
    state: fresh.state || selected.state,
    mergedAt: fresh.mergedAt || selected.mergedAt
  }
}
