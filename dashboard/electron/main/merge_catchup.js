// Catch up on an ongoing merge from a remote webhook (marvin#1223, marvin#1228). Used when
// a dashboard reconnects mid-merge or needs to sync with a merge on another machine.
// `mergeOps`, `fetchProgress`, and `push` are injected for testability.

// Fetch the progress for a single PR from its webhook.
async function fetchProgress(url, { fetch = global.fetch } = {}) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`GET ${url}: ${res.status}`)
  const data = await res.json()
  return data?.merge?.progress ?? data?.progress ?? null
}

// One PR: fetch its progress and fold it into mergeOps, then push the updated op.
export async function catchUpOne(prUrl, { webhookUrl, mergeOps, fetchProgress: fp = fetchProgress, push = () => {}, now = Date.now } = {}) {
  if (!webhookUrl) return null
  let progress
  try {
    const base = new URL(webhookUrl)
    base.pathname = '/merge-progress'
    base.search = `url=${encodeURIComponent(prUrl)}`
    progress = await fp(base.href)
  } catch {
    return null
  }
  if (!progress) return null
  const op = mergeOps?.adopt?.(prUrl, progress, now())
  if (op) {
    try { push(prUrl, op) } catch { /* push failure doesn't break catchup */ }
  }
  return op
}

// Multiple PRs: catch each one up in parallel.
export async function catchUpMerges(urls, { webhookUrl, mergeOps, fetchProgress: fp = fetchProgress, push = () => {} } = {}) {
  const caught = []
  for (const url of urls) {
    const op = await catchUpOne(url, { webhookUrl, mergeOps, fetchProgress: fp, push })
    if (op) caught.push(url)
  }
  return caught
}
