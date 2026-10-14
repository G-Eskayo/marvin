// The boot sequence's animation (#431): a direct port of the approved v7 prototype
// (docs/design/celestial-navigation/boot.html on #428). Everything uses the Web Animations API, so the whole
// sequence can be seeked frame by frame (that's how its recordings are made).
import { bannerTone, lineTone } from './boot_view.js'

// The mark: same geometry as the app icon (icon.html, 1024 grid). Moving a star here moves it in the boot.
const ICON = { pts: [[262, 772], [262, 262], [512, 560], [762, 262], [762, 772]], core: 2, star: 44, coreR: 68, orbit: 118, line: 26 }
const S = 0.34, C = [512, 560]
const P = ICON.pts.map(([x, y]) => [(x - C[0]) * S, (y - C[1]) * S - 70])

const K = 1.3       // overall pacing
const SLOW = 1.2    // everything except the M build runs a touch slower
const HOLD = 1800   // ms the finished frame holds before the dissolve
const COL = { green: '#54ff8a', amber: '#f0b32a', orange: '#ff6a1f', star: '#cfd6e6' }
const MC = { green: '#5ae88a', amber: '#e5ab36', orange: '#f4702e' } // the M: halfway between glow and flat
const NS = 'http://www.w3.org/2000/svg'

export function runBoot(root, data, { onDone = () => {}, onOpenHealth = () => {} } = {}) {
  const q = (id) => root.querySelector(`[data-b="${id}"]`)
  const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); p && p.appendChild(e); return e }
  const anims = []
  const A = (node, kf, o) => {
    const { m, ...rest } = o
    const a = node.animate(kf, { fill: 'both', easing: 'cubic-bezier(.2,.7,.2,1)', ...rest, delay: (o.delay || 0) * K, duration: o.duration * K * (m ? 1 : SLOW) })
    anims.push(a)
    return a
  }
  const at = (n, x, y) => { n.style.transformOrigin = `${x}px ${y}px`; n.style.transformBox = 'view-box' }
  const inout = (n, tIn, dIn, tOut, dOut) => {
    const tot = tOut + dOut - tIn
    A(n, [{ opacity: 0 }, { opacity: 1, offset: dIn / tot }, { opacity: 1, offset: (tOut - tIn) / tot }, { opacity: 0 }], { delay: tIn, duration: tot, easing: 'linear', m: 1 })
  }
  const glow = (n, delay) => A(n, [{ filter: 'brightness(2.4)', textShadow: '0 0 10px currentColor' }, { filter: 'brightness(1)', textShadow: '0 0 0 transparent' }], { delay, duration: 650, easing: 'ease-out' })
  const sweep = (n, delay) => A(n, [{ transform: 'translateY(0)' }, { transform: `translateY(${root.clientHeight + 400}px)` }], { delay, duration: 900, easing: 'cubic-bezier(.4,0,.6,1)' })
  const field = q('field'), mark = q('mark'), lock = q('lock')
  const [cx, cy] = P[ICON.core]

  // 1 · Power on: a line opens, the beam makes its first pass
  A(q('sky'), [{ transform: 'scaleY(.004) scaleX(.5)', filter: 'brightness(3)' }, { transform: 'scaleY(.004) scaleX(1)', filter: 'brightness(3)', offset: 0.45 }, { transform: 'none', filter: 'none' }], { duration: 420, easing: 'cubic-bezier(.7,0,.3,1)' })
  sweep(q('sw1'), 250)

  // 2 · Stars arrive one by one (the five M stars are among them, unmarked)
  let s = 29
  const r = () => (s = (s * 16807) % 2147483647) / 2147483647
  const sky = []
  for (let i = 0; i < 110; i++) {
    const x = (r() - 0.5) * 1280, y = (r() - 0.5) * 800
    if (P.some(([px, py]) => Math.hypot(px - x, py - y) < 36)) continue
    sky.push({ x, y, rad: 0.8 + r() * 1.5, op: 0.25 + r() * 0.55 })
  }
  const stars = P.map(([x, y]) => ({ x, y, rad: 2.4, op: 0.85, m: true }))
  const all = [...sky, ...stars].map((v) => [r(), v]).sort((a, b) => a[0] - b[0]).map((v) => v[1])
  all.forEach((st, i) => {
    const c = el('circle', { cx: st.x, cy: st.y, r: st.rad, fill: COL.star }, st.m ? mark : field)
    st.dot = c; at(c, st.x, st.y)
    A(c, [{ opacity: 0, transform: 'scale(2.6)' }, { opacity: st.op, transform: 'scale(1)' }], { delay: 350 + i * 11, duration: 260, m: 1 })
  })
  const T0 = 350 + all.length * 11 + 150

  // 3 · Lock on the origin, ignite
  const LKW = el('g', {}, lock), LK = el('g', {}, LKW); at(LK, cx, cy)
  const b = 28, L = 9
  ;[[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(([sx, sy]) => el('path', { d: `M${cx + sx * b} ${cy + sy * (b - L)} V${cy + sy * b} H${cx + sx * (b - L)}`, stroke: COL.orange, 'stroke-width': 2, fill: 'none' }, LK))
  el('text', { x: cx + b + 8, y: cy - b + 4, class: 'boot-lock-lbl' }, LK).textContent = 'ORIGIN'
  A(LK, [{ opacity: 0, transform: 'scale(3) rotate(45deg)' }, { opacity: 1, transform: 'none', offset: 0.75 }, { opacity: 1, transform: 'scale(1.1)', offset: 0.85 }, { opacity: 1, transform: 'none' }], { delay: T0, duration: 520, m: 1 })
  A(LKW, [{ opacity: 1 }, { opacity: 0 }], { delay: T0 + 1000, duration: 300, m: 1 })
  const core = el('circle', { cx, cy, r: ICON.coreR * S, fill: 'url(#boot-mcore)', filter: 'url(#boot-mc)' }, mark); at(core, cx, cy)
  A(core, [{ opacity: 0, transform: 'scale(.1)' }, { opacity: 1, transform: 'scale(2.1)', offset: 0.4 }, { opacity: 1, transform: 'none' }], { delay: T0 + 450, duration: 650, m: 1 })
  const orbit = el('circle', { cx, cy, r: ICON.orbit * S, fill: 'none', stroke: MC.orange, 'stroke-width': 5, 'stroke-dasharray': '1.5 10', 'stroke-linecap': 'round' }, mark); at(orbit, cx, cy)
  A(orbit, [{ opacity: 0, transform: 'rotate(-120deg) scale(.5)' }, { opacity: 0.9, transform: 'none' }], { delay: T0 + 650, duration: 800, m: 1 })

  // 4 · Lines grow out of the origin; stars ping as they're reached
  const branch = (a, m, c, delay) => {
    const p = el('path', { d: `M${P[a]} L${P[m]} L${P[c]}`, fill: 'none', stroke: MC.amber, 'stroke-width': ICON.line * S, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', filter: 'url(#boot-ml)' }, mark)
    mark.insertBefore(p, mark.firstChild)
    const len = p.getTotalLength(), l1 = Math.hypot(P[m][0] - P[a][0], P[m][1] - P[a][1])
    p.style.strokeDasharray = len
    A(p, [{ strokeDashoffset: len }, { strokeDashoffset: 0 }], { delay, duration: 900, easing: 'linear', m: 1 })
    return [delay + 900 * l1 / len, delay + 900]
  }
  const reach = (i, t) => {
    const st = stars[i]
    st.dot.setAttribute('filter', 'url(#boot-mn)')
    A(st.dot, [{ r: 2.4, fill: COL.star }, { r: ICON.star * S * 1.5, fill: MC.green, offset: 0.5 }, { r: ICON.star * S, fill: MC.green }], { delay: t, duration: 420, composite: 'replace', m: 1 })
    const ring = el('circle', { cx: st.x, cy: st.y, r: 6, fill: 'none', stroke: MC.green, 'stroke-width': 1.3 }, mark)
    A(ring, [{ r: 6, opacity: 0 }, { r: 6, opacity: 0.8, offset: 0.02 }, { r: 40, opacity: 0 }], { delay: t, duration: 700, easing: 'ease-out', m: 1 })
  }
  const [a1, a2] = branch(2, 1, 0, T0 + 750), [b1, b2] = branch(2, 3, 4, T0 + 750)
  reach(1, a1); reach(3, b1); reach(0, a2); reach(4, b2)

  // 5 · System check: every real health check scrolls past; the bar is real progress through them
  const feed = q('feed'), F = data.feed.length ? data.feed : [{ label: 'health status unavailable', level: 'yellow' }]
  const LH = 19, VIS = 7, C0 = 600, DT = Math.max(28, Math.min(60, 2600 / F.length)) * SLOW
  F.forEach((c, i) => {
    const d = document.createElement('div'); d.className = 'boot-fl ' + lineTone(c.level)
    const dot = document.createElement('i'); dot.className = lineTone(c.level)
    d.append(dot, String(c.label).toUpperCase()); feed.appendChild(d)
    A(d, [{ opacity: 0 }, { opacity: 1 }], { delay: C0 + i * DT, duration: 1, easing: 'linear', m: 1 }); glow(d, C0 + i * DT)
  })
  A(feed, [{ transform: `translateY(${VIS * LH}px)` }, { transform: `translateY(${-(F.length - VIS) * LH}px)` }], { delay: C0, duration: F.length * DT, easing: `steps(${F.length})`, m: 1 })
  const CHK_END = C0 + F.length * DT
  A(q('fill'), [{ width: '0%' }, { width: '100%' }], { delay: C0, duration: F.length * DT, easing: `steps(${F.length})`, m: 1 })
  const nTick = A(q('chkN'), [{ opacity: 1 }, { opacity: 1 }], { delay: C0, duration: F.length * DT, easing: 'linear', m: 1 })
  const drawCount = () => {
    const t = (nTick.currentTime ?? 0) - C0 * K
    const n = Math.max(0, Math.min(F.length, Math.floor(t / (DT * K)) + (t >= 0 ? 1 : 0)))
    q('chkN').textContent = String(n).padStart(3, '0') + '/' + String(F.length).padStart(3, '0')
    q('barP').textContent = String(Math.round(n / F.length * 100)).padStart(3, '0') + '%'
  }

  // 6 · Verified: beam pass, the feed settles into the summary, the bar becomes the verdict
  sweep(q('sw2'), CHK_END)
  inout(q('fw'), 0, 1, CHK_END + 80, 250)
  inout(q('hw'), C0 - 150, 200, CHK_END + 80, 250)
  data.lines.forEach((l, i) => {
    const d = document.createElement('div'); d.className = lineTone(l.level)
    const chip = document.createElement('b'); chip.textContent = l.chip
    d.append(chip, l.text); q('sum').appendChild(d)
    A(d, [{ opacity: 0, transform: 'translateX(-8px)' }, { opacity: 1, transform: 'none' }], { delay: CHK_END + 250 + i * 120 * SLOW, duration: 150, easing: 'steps(3)' })
    glow(d, CHK_END + 250 + i * 120 * SLOW)
  })
  const ban = q('banner')
  ban.classList.add(bannerTone(data.verdict))
  q('bannerT').textContent = data.verdict.text
  inout(q('bar'), C0 - 150, 200, CHK_END + 100, 200)
  A(ban, [{ opacity: 0, clipPath: 'inset(0 50% 0 50%)' }, { opacity: 1, clipPath: 'inset(0 0 0 0)' }], { delay: CHK_END + 150, duration: 380 })
  glow(q('bannerT'), CHK_END + 250)
  A(q('title'), [{ opacity: 0, filter: 'blur(6px)' }, { opacity: 1, filter: 'blur(0)' }], { delay: Math.max(a2, b2) + 200, duration: 420, easing: 'steps(6)' })

  // 7 · Hold, then dissolve into the dashboard underneath (same background, nothing flashes)
  const DONE = Math.max(CHK_END + (250 + data.lines.length * 120 + 300) * SLOW, Math.max(a2, b2) + 700)
  const END = DONE + HOLD / K
  const out = A(root, [{ opacity: 1 }, { opacity: 0 }], { delay: END, duration: 420, easing: 'ease-in-out', m: 1 })

  let raf = 0, finished = false
  const tick = () => { drawCount(); raf = requestAnimationFrame(tick) }
  tick()
  const finish = () => { if (finished) return; finished = true; cancelAnimationFrame(raf); onDone() }
  out.finished.then(finish).catch(() => {})
  const skip = () => anims.forEach((a) => { a.currentTime = Math.max(a.currentTime || 0, END * K) })
  const onKey = () => skip()
  const onClick = (e) => {
    if (ban.contains(e.target) && bannerTone(data.verdict) !== 'nominal') onOpenHealth()
    skip()
  }
  window.addEventListener('keydown', onKey)
  root.addEventListener('click', onClick)

  const total = (END + 440) * K
  const seek = (ms) => { anims.forEach((a) => { a.pause(); a.currentTime = ms }); drawCount() }
  return {
    total, seek, skip,
    cancel() {
      window.removeEventListener('keydown', onKey); root.removeEventListener('click', onClick)
      cancelAnimationFrame(raf); anims.forEach((a) => a.cancel())
    }
  }
}
