import path from 'path'

// "Files on this Mac" for the Docs tab: the same Spotlight search the `findit`
// command uses (~/.claude/organize/find_file.py, one implementation), with each
// hit attributed to the catalog project whose folder contains it.
// Library/CloudStorage = Dropbox, Google Drive, OneDrive (Nourished sat unfound in Dropbox until 2026-10-07).
// Keep in step with ROOTS in find_file.py.
const SEARCH_ROOTS = ['Documents', 'Desktop', 'Downloads', 'Developer', 'Library/CloudStorage']
// The master map also links Claude's memory and handoffs (~/.claude) and MARVIN itself (~/.agents).
const LINK_ROOTS = [...SEARCH_ROOTS, '.claude', '.agents']
const OPEN_EXT = new Set(['md', 'txt', 'pdf', 'csv', 'json', 'docx', 'doc', 'xlsx', 'pptx', 'pages', 'numbers', 'key', 'png', 'jpg', 'jpeg', 'heic', 'gif'])

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

// A link in the master map may point inside LINK_ROOTS, but never at a hidden file or folder below the root
// (~/.claude/.gh-token, ~/.claude/.oauth-token), and never through "..".
export function isLinkable(filePath, home) {
  if (typeof filePath !== 'string' || !path.isAbsolute(filePath) || filePath.split('/').includes('..')) return false
  const root = LINK_ROOTS.map((r) => path.join(home, r)).find((r) => filePath === r || filePath.startsWith(r + '/'))
  if (!root) return false
  return !filePath.slice(root.length).split('/').some((seg) => seg.startsWith('.'))
}

// What clicking a map link does: folders and documents open; anything else (scripts, apps, .command files)
// is only shown in Finder, so a link can never run code.
export function linkAction(filePath, isDir) {
  const ext = path.extname(filePath).slice(1).toLowerCase()
  if (isDir) return ext === 'app' ? 'reveal' : 'open'
  return OPEN_EXT.has(ext) ? 'open' : 'reveal'
}
