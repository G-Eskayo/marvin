// Must match lib/project_catalog.py's slug(): the catalog project id is the key Docs, Activity
// boards and MR Review all share, derived from the GitHub repo name.
export function projectIdOf(repo) {
  const name = String(repo || '').split('/').pop()
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}
