// Builds small real PDFs for tests and evidence (marvin#402): N text pages, optionally a standard-security /Encrypt
// dictionary whose user password is not empty (pdf.js then asks for a password), or a page tree with no pages.
export function makePdf({ pages = 1, encrypt = false, emptyTree = false, title = 'Test PDF' } = {}) {
  const esc = (s) => s.replace(/[()\\]/g, (c) => `\\${c}`)
  const objs = []
  const add = (body) => { objs.push(body); return objs.length }
  const catalog = add('')
  const pagesObj = add('')
  const font = add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
  const kids = []
  if (!emptyTree) {
    for (let i = 1; i <= pages; i++) {
      const lines = [title, '', `Page ${i} of ${pages}`, '', 'A fixture for the Files tab PDF renderer (#402).']
      const text = `BT /F1 20 Tf 72 720 Td 28 TL ${lines.map((l) => `(${esc(l)}) '`).join(' ')} ET 0.2 0.4 0.8 rg 72 100 ${(468 * i) / pages} 24 re f`
      const content = add(`<< /Length ${text.length} >>\nstream\n${text}\nendstream`)
      kids.push(add(`<< /Type /Page /Parent ${pagesObj} 0 R /MediaBox [0 0 612 792] /Contents ${content} 0 R /Resources << /Font << /F1 ${font} 0 R >> >> >>`))
    }
  }
  objs[catalog - 1] = `<< /Type /Catalog /Pages ${pagesObj} 0 R >>`
  objs[pagesObj - 1] = `<< /Type /Pages /Kids [${kids.map((k) => `${k} 0 R`).join(' ')}] /Count ${kids.length} >>`
  const enc = encrypt ? add(`<< /Filter /Standard /V 1 /R 2 /O <${'ab'.repeat(32)}> /U <${'cd'.repeat(32)}> /P -4 >>`) : null
  let out = '%PDF-1.4\n'
  const offs = []
  objs.forEach((o, i) => { offs.push(Buffer.byteLength(out, 'latin1')); out += `${i + 1} 0 obj\n${o}\nendobj\n` })
  const xref = Buffer.byteLength(out, 'latin1')
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offs.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`
  out += `trailer\n<< /Size ${objs.length + 1} /Root ${catalog} 0 R${enc ? ` /Encrypt ${enc} 0 R /ID [<${'01'.repeat(16)}> <${'01'.repeat(16)}>]` : ''} >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}
