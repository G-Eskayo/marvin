// Opening a PDF with pdf.js for the Files tab's own PDF renderer (G-Eskayo/marvin#402; replaced Chromium's embedded
// viewer, which Gil found clashed with the dashboard). Pure apart from the pdf.js `getDocument` passed in, so the tests
// run the real pdf.js (legacy build) in Node against real broken, encrypted and huge files.
//
// Cost: opening reads the document's structure and ONLY page 1 (for the placeholder aspect ratio), so a 200-page PDF
// opens in O(1) page work; PdfView then renders a page only while it is near the viewport.

export const PDF_RENDER_MAX_PX = 4096 // longest side of a page rendered for the full-size viewer
export const PDF_RENDER_MAX_PIXELS = 16_000_000 // canvas area cap (Chromium refuses much larger canvases)

export async function openPdf(getDocument, data) {
  const no = (reason) => ({ ok: false, reason })
  if (!data || !data.length) return no('This PDF is empty.')
  let doc
  try {
    // A copy: pdf.js transfers (detaches) the buffer it is given. No eval, no fetching fonts or anything else.
    doc = await getDocument({ data: new Uint8Array(data), isEvalSupported: false, disableFontFace: false, stopAtErrors: false }).promise
  } catch (err) {
    return no(pdfErrorReason(err))
  }
  if (!doc.numPages) {
    doc.destroy?.()
    return no('This PDF has no pages.')
  }
  try {
    const first = await doc.getPage(1)
    const v = first.getViewport({ scale: 1 })
    return { ok: true, doc, numPages: doc.numPages, aspect: v.height / v.width, firstWidth: v.width }
  } catch (err) {
    doc.destroy?.()
    return no(pdfErrorReason(err))
  }
}

export function pdfErrorReason(err) {
  const name = err?.name || ''
  if (name === 'PasswordException') return 'This PDF is password-protected, so it can\'t be shown here. Open it in Preview to enter the password.'
  if (name === 'InvalidPDFException') return 'This PDF is damaged or not really a PDF, so it can\'t be shown.'
  return `This PDF couldn't be read (${err?.message || 'unknown error'}).`
}

// Scale that makes a page `cssWidth` CSS pixels wide, and the backing-store scale for a sharp canvas on this display,
// capped so a huge page can never ask for an impossible canvas.
export function pageScale(pageWidth, pageHeight, cssWidth, dpr = 1) {
  const w = Number(pageWidth) || 0
  const h = Number(pageHeight) || 0
  const cw = Number(cssWidth) || 0
  if (w <= 0 || h <= 0 || cw <= 0) return { css: 1, pixel: 1 }
  const css = cw / w
  let pixel = css * Math.max(1, Number(dpr) || 1)
  const maxByArea = Math.sqrt(PDF_RENDER_MAX_PIXELS / (w * h))
  const maxBySide = PDF_RENDER_MAX_PX / Math.max(w, h)
  pixel = Math.min(pixel, maxByArea, maxBySide)
  return { css, pixel }
}

// The scale for a page opened in the full-size viewer: as sharp as the caps allow (about 4096 px on the long side).
export function viewerScale(pageWidth, pageHeight) {
  const w = Number(pageWidth) || 0
  const h = Number(pageHeight) || 0
  if (w <= 0 || h <= 0) return 1
  return Math.min(PDF_RENDER_MAX_PX / Math.max(w, h), Math.sqrt(PDF_RENDER_MAX_PIXELS / (w * h)))
}

export const pageCountLabel = (n) => `${n} page${n === 1 ? '' : 's'}`
