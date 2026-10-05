import path from 'path'

// "Files on this Mac" for the Docs tab: the same Spotlight search the `findit`
// command uses (~/.claude/organize/find_file.py, one implementation), with each
// hit attributed to the catalog project whose folder contains it.
const SEARCH_ROOTS = ['Documents', 'Desktop', 'Downloads', 'Developer']

function projectFor(filePath, catalog) {
  let best = null
  for (const p of catalog?.projects || []) {
    for (const lp of p.localPaths || []) {
      if ((filePath === lp || filePath.startsWith(lp + '/')) && (!best || lp.length > best.len)) {
        best = { len: lp.length, id: p.id, name: p.name }
      }
    }
  }
  return best ? { id: best.id, name: best.name } : null
}

export async function searchFiles(query, { run, catalog, home }) {
  if (!query || !query.trim()) return { name: [], content: [] }
  try {
    const found = JSON.parse(await run(query.trim()))
    const tag = (hits) => hits.map((h) => ({ ...h, project: projectFor(h.path, catalog) }))
    return { name: tag(found.name || []), content: tag(found.content || []) }
  } catch (err) {
    // Spotlight timing out or printing junk must not break doc search.
    return { name: [], content: [], error: String(err.message || err) }
  }
}

// Only files inside the folders the search covers can be revealed in Finder,
// so a compromised renderer can't use this to poke at ~/.ssh and friends.
export function isRevealable(filePath, home) {
  if (typeof filePath !== 'string' || !path.isAbsolute(filePath) || filePath.split('/').includes('..')) return false
  return SEARCH_ROOTS.some((r) => filePath.startsWith(path.join(home, r) + '/'))
}
