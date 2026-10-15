const TERMINAL_STAGE_ORDER = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'versioning', 'rebuilding', 'done']

const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Planning',
  executing: 'Executing',
  verifying: 'Verifying',
  gate: 'Merge gate',
  mutation: 'Mutation',
  merging: 'Merging',
  versioning: 'Versioning',
  rebuilding: 'Rebuilding',
  done: 'Done'
}

export { TERMINAL_STAGE_ORDER, STAGE_LABEL }
