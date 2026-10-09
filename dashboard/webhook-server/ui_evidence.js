import { MergeFailure, refusal } from './failure.js'

// The owner's hard rule (marvin #374, 2026-10-09): anything that changes how an app looks must carry images, so he
// sees what he is approving. Several clarity-captions UI PRs merged with none (their profile said screenshots could
// not be captured, and the repo's PR rules let a PR just say so), and he found design changes on his phone that he
// had never seen. Shared by the merge path (refuses) and the review card (shows "Needs images").

// Paths that change what a person sees, in any project. A project adds its own with `evidence.ui_paths` in its
// profile (config/projects/<name>.json), e.g. every Swift file under Apps/ for an app whose views are not named *View.
// Logic, tests, docs and the Electron main process are deliberately not here: they don't change the look.
export const DEFAULT_UI_PATTERNS = [
  'dashboard/src/**',
  '**/*.xcassets/**',
  '**/*.xcstrings',
  '**/*.storyboard',
  '**/*.xib',
  '**/*View.swift',
  '**/Views/**/*.swift',
  '**/*.jsx',
  '**/*.tsx',
  '**/*.css',
  '**/*.html'
]

// "**/" matches zero or more folders, "**" anything, "*" anything but a slash; everything else is literal.
export function globToRegExp(glob) {
  let re = ''
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i]
    if (c === '*' && glob[i + 1] === '*') {
      if (glob[i + 2] === '/') { re += '(?:.*/)?'; i += 2 } else { re += '.*'; i += 1 }
    } else if (c === '*') {
      re += '[^/]*'
    } else {
      re += c.replace(/[.+?^${}()|[\]\\]/g, '\\$&')
    }
  }
  return new RegExp(`^${re}$`)
}

function patternsFor(extra) {
  const own = Array.isArray(extra) ? extra.filter((p) => typeof p === 'string' && p) : []
  return [...DEFAULT_UI_PATTERNS, ...own].map(globToRegExp)
}

export function uiFiles(files, extraPatterns = []) {
  if (!Array.isArray(files)) return []
  const res = patternsFor(extraPatterns)
  return files.filter((f) => typeof f === 'string' && f && res.some((r) => r.test(f)))
}

export const touchesUi = (files, extraPatterns = []) => uiFiles(files, extraPatterns).length > 0

// A markdown image with a target, or an HTML <img> with a src. A plain link to a .png is not an image on the page.
export function hasImage(body) {
  if (typeof body !== 'string') return false
  return /!\[[^\]]*\]\(\s*<?[^)\s>]+/.test(body) || /<img\b[^>]*\bsrc\s*=\s*["']?[^"'\s>]+/i.test(body)
}

// Refuses a UI-touching PR whose body has no image. Fails CLOSED when GitHub can't be asked: a refused Approve costs
// one more click once GitHub answers, while merging a UI change nobody has seen breaks the rule this exists for.
export async function assertUiEvidence(prUrl, exec, extraPatterns = []) {
  let files, body
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'files,body'])
    const parsed = JSON.parse(stdout)
    files = (parsed.files || []).map((f) => f.path)
    body = parsed.body || ''
  } catch (error) {
    const reason = String(error?.stderr || error?.message || error).split('\n')[0].slice(0, 200)
    throw new MergeFailure(refusal('UI_EVIDENCE_UNCHECKED', 'request',
      `couldn't check whether this PR changes how the app looks (${reason})`,
      'Approve again in a moment. UI changes must show images before they merge, so the merge waits until that can be checked.'))
  }
  const changed = uiFiles(files, extraPatterns)
  if (changed.length && !hasImage(body)) {
    const shown = changed.slice(0, 3).join(', ') + (changed.length > 3 ? ` and ${changed.length - 3} more` : '')
    throw new MergeFailure(refusal('NO_UI_EVIDENCE', 'request',
      `this PR changes how the app looks (${shown}) but shows no images`,
      'Add screenshots of the changed screens to the PR description (simulator or running app, light and dark where both apply), then approve again. The PR was not sent back.'))
  }
}
