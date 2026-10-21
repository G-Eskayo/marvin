// Builds small real PDFs for tests and evidence (marvin#402): N text pages, and optionally
// - encrypt: a standard-security /Encrypt dictionary whose user password is not empty (pdf.js asks for a password)
// - emptyTree: a page tree with no pages
// - outline: bookmarks [{ title, page, children }]
// - links: on page 1, link annotations [{ text, page } | { text, uri } | { text, js }]
// - form: on page 1, an AcroForm text field, a checkbox and a dropdown
// - words: extra body text per page (for find-in-PDF)
export function makePdf({ pages = 1, encrypt = false, emptyTree = false, title = 'Test PDF', outline = null, links = null, form = false, words = '' } = {}) {
  const esc = (s) => String(s).replace(/[()\\]/g, (c) => `\\${c}`)
  const objs = []
  const reserve = () => { objs.push(null); return objs.length }
  const set = (id, body) => { objs[id - 1] = body }
  const add = (body) => { objs.push(body); return objs.length }
  const catalog = reserve()
  const pagesObj = reserve()
  const font = add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
  const pageIds = emptyTree ? [] : Array.from({ length: pages }, () => reserve())

  const annotsFor = (i) => {
    const ids = []
    if (i !== 0) return ids
    ;(links || []).forEach((l, k) => {
      const y = 440 - k * 40
      const rect = `/Rect [72 ${y - 6} 400 ${y + 22}]`
      let action
      if (l.page) action = `/Dest [${pageIds[l.page - 1]} 0 R /XYZ 0 792 null]`
      else if (l.uri) action = `/A << /S /URI /URI (${esc(l.uri)}) >>`
      else action = `/A << /S /JavaScript /JS (${esc(l.js)}) >>`
      ids.push(add(`<< /Type /Annot /Subtype /Link ${rect} /Border [0 0 0] ${action} >>`))
    })
    if (form) {
      const p = `/P ${pageIds[0]} 0 R /F 4`
      const box = (on) => add(`<< /Type /XObject /Subtype /Form /BBox [0 0 16 16] /Length ${on ? 30 : 1} >>\nstream\n${on ? '0 g 3 3 10 10 re f            ' : ' '}\nendstream`)
      const yes = box(true)
      const off = box(false)
      ids.push(add(`<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) /TU (Name) ${p} /Rect [200 300 460 324] /DA (/Helv 12 Tf 0 g) /V () /MK << /BG [1 1 1] /BC [0 0 0] >> >>`))
      ids.push(add(`<< /Type /Annot /Subtype /Widget /FT /Btn /T (agree) /TU (I agree) ${p} /Rect [200 260 216 276] /V /Off /AS /Off /AP << /N << /Yes ${yes} 0 R /Off ${off} 0 R >> >> /MK << /BC [0 0 0] >> >>`))
      ids.push(add(`<< /Type /Annot /Subtype /Widget /FT /Ch /Ff 131072 /T (color) /TU (Colour) ${p} /Rect [200 220 360 244] /DA (/Helv 12 Tf 0 g) /Opt [(Red) (Green) (Blue)] /V (Green) /MK << /BG [1 1 1] /BC [0 0 0] >> >>`))
    }
    return ids
  }

  const formFieldIds = []
  pageIds.forEach((id, i) => {
    const lines = [title, '', `Page ${i + 1} of ${pages}`, '', 'A fixture for the Files tab PDF renderer (#402).']
    if (words) lines.push('', words)
    let text = `BT /F1 20 Tf 72 720 Td 28 TL ${lines.map((l) => `(${esc(l)}) '`).join(' ')} ET`
    if (i === 0 && links) text += ` BT /F1 16 Tf 0 0 0.8 rg ${links.map((l, k) => `1 0 0 1 76 ${440 - k * 40} Tm (${esc(l.text)}) Tj`).join(' ')} ET`
    if (i === 0 && form) text += ' BT /F1 14 Tf 0 g 1 0 0 1 72 306 Tm (Name) Tj 1 0 0 1 72 264 Tm (I agree) Tj 1 0 0 1 72 226 Tm (Colour) Tj ET'
    text += ` 0.2 0.4 0.8 rg 72 100 ${(468 * (i + 1)) / Math.max(1, pages)} 24 re f`
    const content = add(`<< /Length ${text.length} >>\nstream\n${text}\nendstream`)
    const annots = annotsFor(i)
    if (i === 0 && form) formFieldIds.push(...annots.slice(-3))
    set(id, `<< /Type /Page /Parent ${pagesObj} 0 R /MediaBox [0 0 612 792] /Contents ${content} 0 R /Resources << /Font << /F1 ${font} 0 R /Helv ${font} 0 R >> >>${annots.length ? ` /Annots [${annots.map((a) => `${a} 0 R`).join(' ')}]` : ''} >>`)
  })

  let outlinesRef = ''
  if (outline && outline.length && pageIds.length) {
    const root = reserve()
    const build = (items, parent) => {
      const ids = items.map(() => reserve())
      items.forEach((it, k) => {
        const kids = it.children?.length ? build(it.children, ids[k]) : null
        const parts = [`/Title (${esc(it.title)})`, `/Parent ${parent} 0 R`, `/Dest [${pageIds[it.page - 1]} 0 R /XYZ 0 792 null]`]
        if (k > 0) parts.push(`/Prev ${ids[k - 1]} 0 R`)
        if (k < ids.length - 1) parts.push(`/Next ${ids[k + 1]} 0 R`)
        if (kids) parts.push(`/First ${kids[0]} 0 R /Last ${kids[kids.length - 1]} 0 R /Count ${kids.length}`)
        set(ids[k], `<< ${parts.join(' ')} >>`)
      })
      return ids
    }
    const top = build(outline, root)
    set(root, `<< /Type /Outlines /First ${top[0]} 0 R /Last ${top[top.length - 1]} 0 R /Count ${top.length} >>`)
    outlinesRef = ` /Outlines ${root} 0 R /PageMode /UseOutlines`
  }
  const acro = form ? ` /AcroForm << /Fields [${formFieldIds.map((f) => `${f} 0 R`).join(' ')}] /DA (/Helv 12 Tf 0 g) /DR << /Font << /Helv ${font} 0 R >> >> >>` : ''
  set(catalog, `<< /Type /Catalog /Pages ${pagesObj} 0 R${outlinesRef}${acro} >>`)
  set(pagesObj, `<< /Type /Pages /Kids [${pageIds.map((k) => `${k} 0 R`).join(' ')}] /Count ${pageIds.length} >>`)
  const enc = encrypt ? add(`<< /Filter /Standard /V 1 /R 2 /O <${'ab'.repeat(32)}> /U <${'cd'.repeat(32)}> /P -4 >>`) : null
  let out = '%PDF-1.4\n'
  const offs = []
  objs.forEach((o, i) => { offs.push(Buffer.byteLength(out, 'latin1')); out += `${i + 1} 0 obj\n${o}\nendobj\n` })
  const xref = Buffer.byteLength(out, 'latin1')
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offs.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`
  out += `trailer\n<< /Size ${objs.length + 1} /Root ${catalog} 0 R${enc ? ` /Encrypt ${enc} 0 R /ID [<${'01'.repeat(16)}> <${'01'.repeat(16)}>]` : ''} >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}
