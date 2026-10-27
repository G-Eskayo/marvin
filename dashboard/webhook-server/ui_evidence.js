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

const listed = (items) => items.slice(0, 3).join(', ') + (items.length > 3 ? ` and ${items.length - 3} more` : '')

// Refuses a UI-touching PR whose body has no image. Fails CLOSED when GitHub can't be asked: a refused Approve costs
// one more click once GitHub answers, while merging a UI change nobody has seen breaks the rule this exists for.
export async function assertUiEvidence(prUrl, exec, extraPatterns = []) {
  let files, body, head
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'files,body,headRefOid'])
    const parsed = JSON.parse(stdout)
    files = (parsed.files || []).map((f) => f.path)
    body = parsed.body || ''
    head = parsed.headRefOid || ''
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
  if (!changed.length) return
  const unpinned = unpinnedImages(body)
  if (unpinned.length) {
    throw new MergeFailure(refusal('IMAGES_UNPINNED', 'request',
      `this PR's images aren't pinned to a commit (${listed(unpinned)}), so they may be old copies`,
      'Link each image by the full commit SHA it was taken at (raw.githubusercontent.com/<owner>/<repo>/<sha>/<path>), then approve again. The PR was not sent back.'))
  }
  // Pinned, but is any look-changing file newer than the images? One compare per distinct commit (usually one).
  const [owner, repo, , number] = new URL(prUrl).pathname.split('/').filter(Boolean)
  for (const sha of imageShas(body).filter((s) => s !== head).slice(0, 5)) {
    let since
    try {
      const { stdout } = await exec('gh', ['api', `repos/${owner}/${repo}/compare/${sha}...${head}`])
      since = (JSON.parse(stdout).files || []).map((f) => f.filename)
    } catch (error) {
      const reason = String(error?.stderr || error?.message || error).split('\n')[0].slice(0, 200)
      throw new MergeFailure(refusal('UI_EVIDENCE_UNCHECKED', 'request',
        `couldn't check whether the images (taken at ${sha.slice(0, 7)}) are current (${reason})`,
        'Retake the screenshots at the PR\'s latest commit and pin them to it, then approve again.'))
    }
    const newer = uiFiles(since, extraPatterns)
    if (newer.length) {
      throw new MergeFailure(refusal('IMAGES_STALE', 'request',
        `the images were taken at ${sha.slice(0, 7)}, and ${listed(newer)} changed after that, so they may not show what PR #${number} looks like now`,
        'Retake the changed screens at the latest commit and pin the links to it, then approve again. The PR was not sent back.'))
    }
  }
}
