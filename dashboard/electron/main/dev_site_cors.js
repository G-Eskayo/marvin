// The Portfolio tab previews real site markup in frames, and the page's web fonts (Roboto Slab, the card titles) live
// on the DEV site, which does not send CORS headers: a browser silently refuses cross-origin fonts, so previews fell
// back to Arial. Add the header to the dev site's responses inside this app only -- the site itself is unchanged.
export const DEV_SITE_PATTERN = 'http://localhost:8080/*'

export function withCors(responseHeaders = {}) {
  const headers = { ...responseHeaders }
  for (const k of Object.keys(headers)) if (k.toLowerCase() === 'access-control-allow-origin') delete headers[k]
  headers['Access-Control-Allow-Origin'] = ['*']
  // Never cache the dev site inside this app: a stylesheet edited on the dev site (the project card's, say) must show
  // in the previews at once, not after the HTTP cache decides it is stale.
  for (const k of Object.keys(headers)) if (['cache-control', 'expires', 'etag', 'last-modified'].includes(k.toLowerCase())) delete headers[k]
  headers['Cache-Control'] = ['no-store']
  return headers
}

export function installDevSiteCors(session) {
  session.webRequest.onHeadersReceived({ urls: [DEV_SITE_PATTERN] }, (details, callback) => {
    callback({ responseHeaders: withCors(details.responseHeaders) })
  })
}
