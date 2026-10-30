// One place for project names (marvin#848). A project's name is set once, in overrides.json's `name` (the owner's
// answer on #767: friendly names like MARVIN and Seal Speak); the catalog carries it after its next refresh, and this
// applies it at once so a rename shows without waiting for one. Every screen (MR Review, the boards, helper chips) asks
// nameOf, whichever spelling it holds: a catalog id, a repo, a helper tab's group, an alias. Python's twin is
// lib/project_catalog.py display_name; both read the same overrides.json, so the two always agree.
import { projectIdOf } from './projects.js'

const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()

export function withOverrides(projects, overrides) {
  const o = overrides && typeof overrides === 'object' ? overrides : {}
  return (Array.isArray(projects) ? projects : []).map((p) => {
    const own = o[p.id] && typeof o[p.id] === 'object' ? o[p.id] : {}
    const name = typeof own.name === 'string' && own.name.trim() ? own.name.trim() : p.name
    const aliases = [...new Set([...(p.aliases || []), ...(Array.isArray(own.aliases) ? own.aliases : [])])]
    return {
      ...p,
      name,
      ...(name !== p.name ? { catalogName: p.name } : {}),
      ...(own.status ? { status: own.status } : {}),
      ...(aliases.length ? { aliases } : {})
    }
  })
}

// Every spelling of a project, normalised (case, dashes, underscores and spaces all alike).
export function spellingsOf(p) {
  const repo = p.repo || ''
  return [p.name, p.id, p.catalogName, repo, repo.split('/').pop(), ...(p.aliases || [])].filter(Boolean).map(norm)
}

export function projectFor(term, projects) {
  const t = norm(term)
  if (!t) return null
  const list = Array.isArray(projects) ? projects : []
  return list.find((p) => spellingsOf(p).includes(t)) || list.find((p) => p.id === projectIdOf(term)) || null
}

export function nameOf(term, projects) {
  if (term == null || term === '') return ''
  return projectFor(term, projects)?.name || String(term)
}
