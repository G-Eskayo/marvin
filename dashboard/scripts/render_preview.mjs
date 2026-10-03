// Builds the exact preview document the dashboard's Templates tab uses for an element, so a Python check can measure it.
// stdin: {"html": "...", "context": "page|grid|chrome", "width": 760|null, "wide": false}   stdout: the document (HTML)
import { createPortfolio } from '../electron/main/portfolio.js'
import { previewDocument } from '../src/lib/portfolio.js'

let input = ''
for await (const chunk of process.stdin) input += chunk
const { html, context = 'page', width = null, wide = false } = JSON.parse(input)
const portfolio = createPortfolio({ exec: async () => ({ stdout: '' }) })
process.stdout.write(previewDocument(html, await portfolio.previewHead(), { context, width, wide }))
