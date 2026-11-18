// Resolve a relative href from a doc's path to an absolute doc path + optional anchor.
// Returns { type: 'doc', path, anchor } or null if the href is not a relative link or resolves outside the repo.
export function resolveDocLink(href, docPath) {
  if (!href || !docPath) return null

  // Anchor-only links are same-doc navigation
  if (href.startsWith('#')) {
    return { type: 'doc', path: docPath, anchor: href.slice(1) }
  }
  if (/^([a-z][a-z0-9+.-]*:|\/\/|data:)/i.test(href)) return null

  // Split the href into path and anchor
  const [pathPart, ...anchorParts] = href.split('#')
  const anchor = anchorParts.length > 0 ? anchorParts.join('#') : null

  if (!pathPart) return null // empty path is not a relative doc

  // Resolve the relative path: leading / means repo root, otherwise relative to docDir
  let parts
  if (pathPart.startsWith('/')) {
    parts = pathPart.split('/')
  } else {
    const docDir = docPath.includes('/') ? docPath.split('/').slice(0, -1).join('/') : ''
    parts = [...(docDir ? docDir.split('/') : []), ...pathPart.split('/')]
  }

  // Normalize .. and . and reject paths that try to escape the repo
  const normalized = []
  for (const part of parts) {
    if (part === '..') {
      if (normalized.length === 0) return null // tried to escape the root
      normalized.pop()
    } else if (part && part !== '.') {
      normalized.push(part)
    }
  }

  const resolvedPath = normalized.join('/')
  if (!resolvedPath) return null

  return { type: 'doc', anchor, path: resolvedPath }
}
