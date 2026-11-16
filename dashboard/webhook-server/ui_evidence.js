import { MergeFailure, refusal } from './failure.js'

// The owner's hard rule (marvin #374, 2026-10-09): anything that changes how an app looks must carry images, so he
// sees what he is approving. Several clarity-captions UI PRs merged with none (their profile said screenshots could
// not be captured, and the repo's PR rules let a PR just say so), and he found design changes on his phone that he
// had never seen. Shared by the merge path (refuses) and the review card (shows "Needs images").

// Paths that change what a person sees, in any project. A project adds its own with `evidence.ui_paths` in its
// profile (config/projects/<name>.json), e.g. every Swift file under Apps/ for an app whose views are not named *View.
// Logic, tests, docs and the Electron main process are deliberately not here: they don't change the look. That includes
// the dashboard's src/lib helpers (a screenshot-capture helper flagged #389 as a UI change); a .jsx/.css there still counts.
export const DEFAULT_UI_PATTERNS = [
  'dashboard/src/*',
  'dashboard/src/components/**',
  'dashboard/src/assets/**',
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

// Image targets on the page: markdown images and HTML <img> sources, in order.
export function imageUrls(body) {
  if (typeof body !== 'string') return []
  const out = []
  for (const m of body.matchAll(/!\[[^\]]*\]\(\s*<?([^)\s>]+)|<img\b[^>]*\bsrc\s*=\s*["']?([^"'\s>]+)/gi)) out.push(m[1] || m[2])
  return out
}

// marvin #733 (2026-10-27): a link by branch name keeps showing the old image after a retake (GitHub and the dashboard
// cache it), so the owner reviewed #171's old screenshots. An image is pinned when its URL names a full commit SHA, or
// it is a GitHub upload, which never changes.
const FULL_SHA = /(?:^|\/)([0-9a-f]{40})(?=\/)/
const GITHUB_UPLOAD = /^https:\/\/(?:github\.com\/user-attachments\/|[a-z-]*user-images\.githubusercontent\.com\/)/

export const unpinnedImages = (body) => imageUrls(body).filter((u) => !FULL_SHA.test(u) && !GITHUB_UPLOAD.test(u))

export const imageShas = (body) => [...new Set(imageUrls(body).map((u) => u.match(FULL_SHA)?.[1]).filter(Boolean))]

// Where each pinned image lives: owner/repo and the commit, from raw.githubusercontent.com/<o>/<r>/<sha>/... or
// github.com/<o>/<r>/blob/<sha>/.... MARVIN's images live in its private instance repo (ADR 0071), not the PR's repo,
// so their commit can't be compared inside the PR's repo (marvin #773).
export function imagePins(body) {
  const seen = new Map()
  for (const u of imageUrls(body)) {
    const m = /^https:\/\/(?:raw\.githubusercontent\.com\/([^/]+)\/([^/]+)\/|github\.com\/([^/]+)\/([^/]+)\/(?:blob|raw)\/)([0-9a-f]{40})\//.exec(u)
    if (!m) continue
    const repo = `${m[1] || m[3]}/${m[2] || m[4]}`
    seen.set(`${repo}@${m[5]}`, { repo, sha: m[5] })
  }
  return [...seen.values()]
}

const listed = (items) => items.slice(0, 3).join(', ') + (items.length > 3 ? ` and ${items.length - 3} more` : '')

// Refuses a UI-touching PR whose body has no image. Fails CLOSED when GitHub can't be asked: a refused Approve costs
// one more click once GitHub answers, while merging a UI change nobody has seen breaks the rule this exists for.
export async function assertUiEvidence(prUrl, exec, extraPatterns = []) {
  try {
    const profilesDir = process.env.MARVIN_INSTANCE_DIR ? `${process.env.MARVIN_INSTANCE_DIR}/config/projects` : ''
    const args = ['lib/pr_images.py', prUrl]
    if (profilesDir) args.push('--profiles-dir', profilesDir)
    const result = await exec('python3', args)
    const parsed = JSON.parse(result.stdout)
    if (!parsed.code) return // no problems
    const code = parsed.code
    const message = parsed.message || ''
    const hints = {
      NO_UI_EVIDENCE: 'Add screenshots of the changed screens to the PR description (simulator or running app, light and dark where both apply), then approve again. The PR was not sent back.',
      IMAGES_UNPINNED: 'Link each image by the full commit SHA it was taken at (raw.githubusercontent.com/<owner>/<repo>/<sha>/<path>), then approve again. The PR was not sent back.',
      IMAGES_STALE: 'Retake the changed screens at the latest commit and pin the links to it, then approve again. The PR was not sent back.',
      UI_EVIDENCE_UNCHECKED: 'Approve again in a moment. If it keeps failing, retake the screenshots at the PR\'s latest commit and pin them to it.'
    }
    throw new MergeFailure(refusal(code, 'request', message, hints[code] || 'Try again in a moment.'))
  } catch (error) {
    // CLI call failed, timed out, or returned non-JSON
    if (error instanceof MergeFailure) throw error
    const reason = String(error?.stderr || error?.message || error).split('\n')[0].slice(0, 200)
    throw new MergeFailure(refusal('UI_EVIDENCE_UNCHECKED', 'request',
      `couldn't check whether this PR changes how the app looks (${reason})`,
      'Approve again in a moment. UI changes must show images before they merge, so the merge waits until that can be checked.'))
  }
}
