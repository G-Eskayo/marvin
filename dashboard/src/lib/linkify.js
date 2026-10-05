// Turns ticket and ADR references in rendered markdown into clickable dash:// links (see relations.js).
// Pure and dependency-free so both the main process and the renderer can use it.
export function linkify(markdown, ctx) {
  // Split into protected spans (code, existing links, bare URLs) and plain text; only touch the latter.
  const protectedRe = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`|!?\[[^\]]*\]\([^)]*\)|https?:\/\/\S+)/g
  return String(markdown)
    .split(protectedRe)
    .map((part, i) => (i % 2 === 1 ? part : linkifyPlain(part, ctx)))
    .join('')
}

function linkifyPlain(text, ctx) {
  return text
    .replace(/\b([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d{1,6})(?![\w-])/g, (m, repo, n) => `[${m}](dash://ticket/${repo}/${n})`)
    .replace(/(?<![\w/&#[])#(\d{1,6})(?![\w-])/g, (m, n) => (ctx.repo ? `[${m}](dash://ticket/${ctx.repo}/${n})` : m))
    .replace(/\bADR[ -]?0*(\d{1,4})\b/gi, (m, n) => {
      const path = ctx.adrs?.[Number(n)]
      return path && ctx.project ? `[${m}](dash://doc/${ctx.project}/${path})` : m
    })
}
