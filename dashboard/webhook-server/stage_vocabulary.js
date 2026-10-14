// Shared vocabulary for stage names and labels across the codebase.
// Single source of truth: changes here propagate everywhere.

export const STAGE_ORDER = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'mutation', 'merging', 'versioning', 'rebuilding', 'done']

export const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Planning',
  executing: 'Executing',
  verifying: 'Verifying',
  gate: 'Gate',
  mutation: 'Mutate',
  merging: 'Merge',
  versioning: 'Version',
  rebuilding: 'Rebuild',
  done: 'Done'
}
