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

const _FIX = "Pin them with `pr-shots <images>` from the PR's worktree (it commits them and links each by full commit SHA)."
const _WHY = {
  "relative": "a repo path, which doesn't show in a PR",
  "blob": "a blob/...?raw=true link, a 404 for private repos",
  "branch": "linked by branch name or short SHA, so it shows whatever is newest"
}

function link_problem(url) {
  // Why this image link breaks or goes stale, or null when it's pinned
  if (!url.startsWith("http://") && !url.startsWith("https://")) return "relative"
  if (/^https:\/\/github\.com\/[^/]+\/[^/]+\/(blob|raw)\//.test(url) && url.includes("?raw=true")) return "blob"
  const raw = /^https:\/\/raw\.githubusercontent\.com\/[^/]+\/[^/]+\/([^/]+)\//.exec(url)
  if (raw && !/^[0-9a-f]{40}$/.test(raw[1])) return "branch"
  return null
}

// Verify UI evidence: a UI PR must show images. Takes the PR URL and an exec function (for GitHub API calls).
// exec(cmd, args) is a callable that runs `cmd` (e.g. 'gh') with the given args and returns { stdout, stderr }.
export async function assertUiEvidence(prUrl, exec, extraPatterns = []) {
  // Parse the PR URL to extract owner, repo, and number
  const parsed = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)$/.exec(prUrl)
  if (!parsed) {
    throw new MergeFailure(refusal('UI_EVIDENCE_UNCHECKED', 'request',
      `invalid PR URL: ${prUrl}`,
      'This is a dashboard error. Contact the owner.'))
  }

  const [, owner, repo, number] = parsed
  const pr_repo = `${owner}/${repo}`

  let pr, files, body, head_ref
  try {
    // Fetch PR facts
    const result = await exec('gh', ['pr', 'view', number, '--repo', pr_repo, '--json', 'files,body,headRefOid'])
    pr = JSON.parse(result.stdout)
    files = (pr.files || []).map(f => f.path)
    body = pr.body || ''
    head_ref = pr.headRefOid
  } catch (error) {
    throw new MergeFailure(refusal('UI_EVIDENCE_UNCHECKED', 'request',
      `couldn't fetch PR #${number}: ${String(error?.message || error).slice(0, 100)}`,
      'Approve again in a moment. UI changes must show images before they merge, so the merge waits until that can be checked.'))
  }

  // Check if this PR touches UI files
  const ui = uiFiles(files, extraPatterns)
  if (!ui.length) {
    return  // Not a UI change, no image check needed
  }

  // Check for images
  const urls = imageUrls(body)
  if (!urls.length) {
    throw new MergeFailure(refusal('NO_UI_EVIDENCE', 'request',
      `This PR changes how something looks (${listed(ui)}) but shows no images. ${_FIX}`,
      'Add screenshots of the changed screens to the PR description (simulator or running app, light and dark where both apply), then approve again. The PR was not sent back.'))
  }

  // Check for broken image links
  const bad = []
  for (const u of urls) {
    const p = link_problem(u)
    if (p) bad.push([u, p])
  }
  if (bad.length > 0) {
    const lines = bad.slice(0, 3).map(([u, p]) => `${u} is ${_WHY[p]}`).join('; ')
    throw new MergeFailure(refusal('IMAGES_UNPINNED', 'request',
      `Some images won't show or will go stale: ${lines}. ${_FIX}`,
      'Fix the image links (pin them to a commit SHA, not a branch), then approve again. The PR was not sent back.'))
  }

  // Check for staleness (images older than later UI changes)
  const pins = imagePins(body)
  const pr_files = new Set(files)
  for (const pin of pins) {
    if (pin.sha === head_ref) continue  // Pinned to head, always current

    try {
      let changed
      if (pin.repo === pr_repo) {
        // Same repo: use compare endpoint
        const compareResult = await exec('gh', ['api', `repos/${pr_repo}/compare/${pin.sha}...${head_ref}`])
        const compare = JSON.parse(compareResult.stdout)
        changed = (compare.files || []).map(f => f.filename)
      } else {
        // Cross-repo: compare by commit time
        const imgCommitRes = await exec('gh', ['api', `repos/${pin.repo}/commits/${pin.sha}`])
        const imgCommit = JSON.parse(imgCommitRes.stdout)
        const img_time = imgCommit.commit?.committer?.date
        if (!img_time) {
          throw new Error('could not get image commit time')
        }

        const prCommitsRes = await exec('gh', ['api', '--paginate', `repos/${pr_repo}/pulls/${number}/commits?per_page=100`])
        const prCommits = JSON.parse(prCommitsRes.stdout)
        if (!Array.isArray(prCommits)) throw new Error('invalid commits response')

        const matching = prCommits.filter(c =>
          c.commit?.committer?.date && c.commit.committer.date <= img_time)
        if (matching.length === 0) {
          // Images are older than entire PR
          changed = files
        } else {
          const last_sha = matching[matching.length - 1].sha
          if (last_sha === head_ref) {
            changed = []
          } else {
            const compareResult = await exec('gh', ['api', `repos/${pr_repo}/compare/${last_sha}...${head_ref}`])
            const compare = JSON.parse(compareResult.stdout)
            changed = (compare.files || []).map(f => f.filename)
          }
        }
      }

      // Only the PR's own files count toward staleness
      const newer_ui = uiFiles(changed.filter(f => pr_files.has(f)), extraPatterns)
        .filter(f => !/\.(png|jpe?g|gif|webp|mp4|mov)$/.test(f))
      if (newer_ui.length > 0) {
        throw new MergeFailure(refusal('IMAGES_STALE', 'request',
          `The images are older than later changes to how it looks (${listed(newer_ui)}). ${_FIX}`,
          'Retake the screenshots at the latest commit and re-pin them, then approve again. The PR was not sent back.'))
      }
    } catch (error) {
      if (error instanceof MergeFailure) throw error
      throw new MergeFailure(refusal('UI_EVIDENCE_UNCHECKED', 'request',
        `Couldn't check whether the images (pinned to ${pin.sha.slice(0, 7)} in ${pin.repo}) are current. Retake them and re-pin, then try again: ${_FIX}`,
        'Approve again in a moment. If it keeps failing, retake the screenshots and re-pin them.'))
    }
  }
}
