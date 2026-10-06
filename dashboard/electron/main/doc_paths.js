// Which files the Docs tab shows, and how they are grouped. Shared by the local reader (docs_local.js) and the GitHub
// fallback (docs.js) so a repo lists the same docs whether or not it is cloned on this machine.
//
// Every .md anywhere under docs/ (it used to be docs/adr/ only, which hid audits, guides and write-ups). A path with a
// hidden segment (docs/.cache/...) or a parent reference is never a doc.

export const DOC_MD = /^docs\/(?:[^/.][^/]*\/)*[^/.][^/]*\.md$/

export function isDocMarkdown(p) {
  return DOC_MD.test(String(p)) && !String(p).split('/').includes('..')
}

// [{ section: 'docs/adr/', items: [{ path, label }] }, ...]: one section per folder, docs/adr/ first (the decision
// records most people open), then the rest by folder name; files sorted by name inside each.
export function groupDocSections(paths) {
  const byDir = new Map()
  for (const p of [...new Set(paths)].filter(isDocMarkdown)) {
    const dir = p.slice(0, p.lastIndexOf('/') + 1)
    byDir.set(dir, [...(byDir.get(dir) || []), p])
  }
  const order = [...byDir.keys()].sort((a, b) => (a === 'docs/adr/' ? -1 : b === 'docs/adr/' ? 1 : a.localeCompare(b)))
  return order.map((dir) => ({
    section: dir,
    items: byDir.get(dir).sort((a, b) => a.localeCompare(b)).map((p) => ({ path: p, label: p.slice(dir.length) }))
  }))
}
