// MR Review's Open list must never look like "nothing to review" when GitHub couldn't be reached (marvin#422).
// On 2026-10-14 every gh call failed for ~9 minutes and the list showed 0; there were 13 open PRs.
const CAUSES = [
  [/error connecting|could not resolve|no such host|ENOTFOUND|ECONNREFUSED|ETIMEDOUT|network/i, 'no network, or GitHub unreachable'],
  [/rate limit|secondary rate|HTTP 403/i, 'GitHub rate limit'],
  [/auth|HTTP 401|credentials/i, 'GitHub sign-in expired'],
  [/cooling down/i, 'GitHub asked us to slow down']
]
export const plainCause = (msg) => (CAUSES.find(([re]) => re.test(msg || '')) || [null, String(msg || 'unknown error').split('\n')[0].slice(0, 120)])[1]

function ago(ms) {
  const m = Math.round(ms / 60_000)
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`
}

// marvin#954: on a pull-only node (mac-mini-2012) the list is read from the Mini's feed, not GitHub. `source` says how old
// it is: a quiet line while fresh, amber when the Mini stopped answering, red when there is nothing from it at all.
// Never "sign in": that machine holds no GitHub credential by design.
function miniBanner(source, errors) {
  if (source.state === 'fresh' && !errors.length) return { tone: 'info', text: source.text }
  if (source.state === 'fresh') {
    const names = errors.map((e) => String(e.repo).split('/').pop()).join(', ')
    return { tone: 'amber', text: `${source.text} Not in the Mini's feed yet: ${names}.` }
  }
  return { tone: source.state === 'missing' ? 'red' : 'amber', text: source.text }
}

export function prFetchBanner({ errors = [], projects = 0, lastGoodAt = null, source = null } = {}, now = Date.now()) {
  if (source?.from === 'mini') return miniBanner(source, errors)
  if (!errors.length) return null
  const causes = [...new Set(errors.map((e) => plainCause(e.message)))].join('; ')
  const all = projects > 0 && errors.length >= projects
  const shown = lastGoodAt ? `Showing the list from ${ago(now - lastGoodAt)}.` : 'No list to show yet; it will load once GitHub answers.'
  if (all) return { tone: 'red', text: `Couldn't reach GitHub for all ${projects} projects (${causes}). ${shown}` }
  const names = errors.map((e) => String(e.repo).split('/').pop()).join(', ')
  return { tone: 'amber', text: `Couldn't read ${errors.length} project${errors.length === 1 ? '' : 's'} (${names}: ${causes}). Their PRs may be missing or out of date.` }
}
