// Recovery when the stream to a merge machine drops (marvin#805): fetch /inflight and /merge-progress
// to check whether the merge is still running, and if so, follow it from its current state instead of
// concluding it interrupted.

// Thin fetch wrappers against a machine's /inflight and /merge-progress endpoints.
export function checkInflight(url, { fetchJson = null }) {
  return fetchJson ? fetchJson(url) : fetch(url).then((r) => (r.ok ? r.json() : null))
}

// checkProgress is an alias for checkInflight since the caller provides the URL with params already set
export const checkProgress = checkInflight

// After a stream drops, determine whether to follow the merge or conclude it interrupted.
// - Check whether /inflight still lists the PR (running on that machine), or check /merge-progress
// - If merge is running, poll /merge-progress until the final result (merged/reengaged)
// - If no longer running and no result in progress, conclude it's interrupted
export async function followAfterDrop({ url, machine, mergeOps, push, pollMs = 1000, maxRetries = 3, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), fetchJson }) {
  const baseUrl = machine.url.replace(/\/approve$/, '')
  const inflightUrl = `${baseUrl}/inflight?url=${encodeURIComponent(url)}`
  const progressUrl = `${baseUrl}/merge-progress?url=${encodeURIComponent(url)}`

  let isRunning = false
  for (let i = 0; i < maxRetries; i++) {
    try {
      const inflightBody = await checkInflight(inflightUrl, { fetchJson })
      // If inflight is null (fetch failed), continue retrying until maxRetries
      if (!inflightBody) {
        if (i < maxRetries - 1) {
          await sleep(pollMs)
          continue
        }
        return { followed: false, reason: `Could not reconnect: machine is unreachable` }
      }
      // inflight endpoint returns { inflight: {...} }
      const entry = inflightBody.inflight && typeof inflightBody.inflight === 'object' ? inflightBody.inflight[url] : null
      isRunning = !!entry

      // Check progress regardless of whether it's in inflight (may have just completed)
      const progressBody = await checkProgress(progressUrl, { fetchJson })
      if (!progressBody?.merge) {
        if (isRunning && i < maxRetries - 1) {
          await sleep(pollMs)
          continue
        }
        return { followed: false, reason: 'Could not fetch merge progress' }
      }

      const { progress: currentProgress, result: finalResult } = progressBody.merge
      // If there's a final result, return it
      if (finalResult) {
        return { followed: true, progress: currentProgress, result: finalResult }
      }

      // Still running; wait and poll again
      if (isRunning) {
        await sleep(pollMs)
        continue
      }

      // Not running and no result: merge was interrupted or machine restarted
      return { followed: false, reason: 'Merge is no longer running on the machine' }
    } catch (err) {
      if (i < maxRetries - 1) await sleep(pollMs)
      else return { followed: false, reason: `Could not reconnect: ${String(err.message).slice(0, 100)}` }
    }
  }
}
