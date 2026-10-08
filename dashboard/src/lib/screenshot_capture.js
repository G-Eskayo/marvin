// Find the real content page from a browser window list.
// A fresh Electron window typically shows about:blank first, then loads
// the app. Return the first page with a non-empty URL that isn't devtools.

export function selectContentPage(pages) {
  return pages.find((p) => {
    const url = p.url?.() || ''
    return url && !url.startsWith('devtools://')
  }) || null
}
