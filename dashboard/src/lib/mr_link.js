// Route an MR Review link to a Workshop navigation target.
// key: 'pr' opens the item, 'project' opens Workshop filtered to that project, 'all' opens Workshop unfiltered.
export function mrLinkTarget(key) {
  if (key === 'pr') return {}
  if (key === 'project') return {}
  return {}
}
