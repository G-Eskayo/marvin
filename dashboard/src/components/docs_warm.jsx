import { createRoot } from 'react-dom/client'
import FileView from './FileView.jsx'
import { loadPdfjs } from './PdfView.jsx'

// Warm-up at idle after boot (#570 speed budget: the first open must not be the slow one). Loads pdf.js and its shared
// worker from the app bundle, and renders a small markdown file once off-screen so the markdown pipeline's code is
// compiled before the first real doc opens. Local code only: nothing is fetched, nothing is shown. Runs once.
// A one-page PDF (761 bytes, made by test/fixtures/make_pdf.js) drawn once off-screen: the first real PDF then skips
// pdf.js's cold first render (parser, font and canvas paths), which cost ~190-240 ms.
const WARM_PDF = 'JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFs0IDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL0ZvbnQgL1N1YnR5cGUgL1R5cGUxIC9CYXNlRm9udCAvSGVsdmV0aWNhIC9FbmNvZGluZyAvV2luQW5zaUVuY29kaW5nID4+CmVuZG9iago0IDAgb2JqCjw8IC9UeXBlIC9QYWdlIC9QYXJlbnQgMiAwIFIgL01lZGlhQm94IFswIDAgNjEyIDc5Ml0gL0NvbnRlbnRzIDUgMCBSIC9SZXNvdXJjZXMgPDwgL0ZvbnQgPDwgL0YxIDMgMCBSIC9IZWx2IDMgMCBSID4+ID4+ID4+CmVuZG9iago1IDAgb2JqCjw8IC9MZW5ndGggMTc3ID4+CnN0cmVhbQpCVCAvRjEgMjAgVGYgNzIgNzIwIFRkIDI4IFRMIChXYXJtKSAnICgpICcgKFBhZ2UgMSBvZiAxKSAnICgpICcgKEEgZml4dHVyZSBmb3IgdGhlIEZpbGVzIHRhYiBQREYgcmVuZGVyZXIgXCgjNDAyXCkuKSAnICgpICcgKHdhcm0gdXAgdGV4dCkgJyBFVCAwLjIgMC40IDAuOCByZyA3MiAxMDAgNDY4IDI0IHJlIGYKZW5kc3RyZWFtCmVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMDkgMDAwMDAgbiAKMDAwMDAwMDA1OCAwMDAwMCBuIAowMDAwMDAwMTE1IDAwMDAwIG4gCjAwMDAwMDAyMTIgMDAwMDAgbiAKMDAwMDAwMDM1MCAwMDAwMCBuIAp0cmFpbGVyCjw8IC9TaXplIDYgL1Jvb3QgMSAwIFIgPj4Kc3RhcnR4cmVmCjU3OAolJUVPRgo='
const SAMPLE = '# Warm\n\nA paragraph with **bold**, `code` and a [link](#x).\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```js\nconst x = 1\n```\n'
let warmed = false
export function warmDocs({ idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 0)) } = {}) {
  if (warmed) return
  warmed = true
  idle(() => {
    loadPdfjs()
      .then(async ({ pdfjs, sharedWorker }) => {
        const data = Uint8Array.from(atob(WARM_PDF), (c) => c.charCodeAt(0))
        const doc = await pdfjs.getDocument({ data, worker: sharedWorker, isEvalSupported: false }).promise
        const page = await doc.getPage(1)
        const viewport = page.getViewport({ scale: 1 })
        const canvas = document.createElement('canvas')
        canvas.width = Math.ceil(viewport.width)
        canvas.height = Math.ceil(viewport.height)
        await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise
        await doc.destroy()
      })
      .catch(() => {})
    try {
      const host = document.createElement('div')
      host.style.cssText = 'position:absolute;left:-10000px;top:0;width:800px;visibility:hidden'
      document.body.appendChild(host)
      const root = createRoot(host)
      root.render(<FileView file={{ kind: 'markdown', content: SAMPLE, name: 'warm.md', path: 'warm.md' }} />)
      requestAnimationFrame(() => requestAnimationFrame(() => {
        root.unmount()
        host.remove()
      }))
    } catch {
      // warming is best effort
    }
  })
}
