export const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Planning',
  executing: 'Executing',
  verifying: 'Verifying',
  gate: 'Merge gate',
  merging: 'Merging',
  mutation: 'Mutation',
  rebuilding: 'Rebuilding',
  done: 'Done'
}

export const CORE_STAGES = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging']

export const OPTIONAL_STAGES = ['mutation', 'rebuilding', 'done']
