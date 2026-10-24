/* Vitals v4 prototypes: shared bits. Everything drawn comes from window.VITALS (data.js, written by build_data.py). */
(function () {
  const D = window.VITALS;
  const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const COL = { green: '#54ff8a', yellow: '#f0b32a', red: '#ff3b2f', grey: '#6b551f', amber: '#f0b32a', line: '#7a5a14', dim: '#6b551f', moon: '#cfd6e6', orange: '#ff6a1f' };
  const byId = Object.fromEntries(D.nodes.map(n => [n.id, n]));
  const mById = Object.fromEntries(D.machines.map(m => [m.id, m]));
  const hourMs = D.window.bucket_s * 1000;
  const endT = D.window.end;           // epoch s, end of current clock hour (minus 1s)
  const fmtT = s => { const d = new Date(s * 1000); return d.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }); };
  const fmtH = s => { const d = new Date(s * 1000); return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); };
  const nodeLabel = n => n ? (n.type === 'service' || n.type === 'caller-group' || n.type === 'launch-kind') && n.machine ? `${n.label} · ${(mById[n.machine] || {}).label || n.machine}` : n.label : '?';

  // dependents: edge.from depends on edge.to. A red node affects everything that (transitively) depends on it.
  const dependents = {};
  D.edges.forEach(e => { if (e.kind === 'runs-on') return; (dependents[e.to] = dependents[e.to] || []).push(e.from); });
  D.edges.forEach(e => { if (e.kind === 'runs-on') (dependents[e.to] = dependents[e.to] || []).push(e.from); });
  function downstream(id) {
    const seen = new Set([id]), q = [id];
    while (q.length) { const x = q.shift(); (dependents[x] || []).forEach(y => { if (!seen.has(y)) { seen.add(y); q.push(y); } }); }
    seen.delete(id); return seen;
  }

  // ── detail panel: plain numbers ─────────────────────────────────────────
  const panel = document.createElement('aside'); panel.id = 'panel'; panel.hidden = true;
  document.body.appendChild(panel);
  function esc(s) { return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }
  function rows(obj) {
    return Object.entries(obj || {}).map(([k, v]) => {
      if (v && typeof v === 'object' && !Array.isArray(v)) return `<tr><th colspan=2>${esc(k)}</th></tr>` + Object.entries(v).map(([a, b]) => `<tr><td class=k>&nbsp;&nbsp;${esc(a)}</td><td>${esc(b)}</td></tr>`).join('');
      return `<tr><td class=k>${esc(k)}</td><td>${esc(Array.isArray(v) ? v.join(', ') : v)}</td></tr>`;
    }).join('');
  }
  function show(title, sev, obj, extra) {
    panel.innerHTML = `<button class=x aria-label=Close>×</button><h2 class="sev-${sev || 'grey'}">${esc(title)}</h2>` +
      (extra || '') + `<table>${rows(obj)}</table>`;
    panel.hidden = false;
    panel.querySelector('.x').onclick = () => { panel.hidden = true; window.dispatchEvent(new Event('vitals:close')); };
  }
  function showNode(n, more) {
    const ins = D.edges.filter(e => e.to === n.id && e.kind !== 'runs-on').sort((a, b) => b.n24 - a.n24).slice(0, 8);
    const outs = D.edges.filter(e => e.from === n.id && e.kind !== 'runs-on').sort((a, b) => b.n24 - a.n24).slice(0, 8);
    const down = downstream(n.id);
    const obj = Object.assign({ type: n.type, machine: n.machine ? (mById[n.machine] || {}).label || n.machine : '—', health: n.health, 'events last 24h': n.load24 }, more || {}, n.numbers);
    if (outs.length) obj['depends on (24h traffic)'] = Object.fromEntries(outs.map(e => [nodeLabel(byId[e.to]) + ` [${e.kind}]`, e.n24]));
    if (ins.length) obj['used by (24h traffic)'] = Object.fromEntries(ins.map(e => [nodeLabel(byId[e.from]) + ` [${e.kind}]`, e.n24]));
    if (down.size) obj['affects if it fails'] = down.size + ' parts';
    const why = n.why && n.why.length ? `<ul class=why>${n.why.slice(0, 6).map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : '';
    show(nodeLabel(n), n.health, obj, why);
  }

  // ── one control: a time scrubber whose track is the real traffic ────────
  // series: array of numbers (one per bucket), marks: [{i, kind}], onChange(i)
  function scrubber(host, series, marks, startT, onChange, label, init) {
    host.innerHTML = `<div class=scrub><canvas></canvas><input type=range min=0 max=${series.length - 1} value=${init == null ? series.length - 1 : init} aria-label="${label}"><div class=st></div></div>`;
    const cv = host.querySelector('canvas'), inp = host.querySelector('input'), st = host.querySelector('.st');
    function draw() {
      const r = cv.getBoundingClientRect(), dpr = devicePixelRatio || 1; cv.width = r.width * dpr; cv.height = r.height * dpr;
      const c = cv.getContext('2d'); c.scale(dpr, dpr);
      const mx = Math.max(1, ...series), w = r.width / series.length;
      series.forEach((v, i) => { const h = (v / mx) * (r.height - 6) + (v ? 1 : 0); c.fillStyle = COL.line; c.fillRect(i * w, r.height - h, Math.max(1, w - .5), h); });
      marks.forEach(m => { c.fillStyle = m.kind === 'storm' ? COL.red : COL.orange; c.fillRect(m.i * w, 0, Math.max(2, w), m.kind === 'storm' ? 4 : 2); });
      const i = +inp.value; c.fillStyle = COL.amber; c.fillRect(i * w, 0, Math.max(2, w), r.height);
    }
    function upd() { const i = +inp.value; st.textContent = `${label}: ${fmtT(startT + i * D.window.bucket_s)} · ${series[i].toLocaleString()} events`; draw(); onChange(i); }
    inp.oninput = upd; addEventListener('resize', draw);
    setTimeout(upd, 0);
    return { set(i) { inp.value = i; upd(); }, get: () => +inp.value };
  }

  // ── tiny 3D: yaw/pitch camera driven by drag; reduced motion = no auto spin ─
  function camera(canvas, opts) {
    const cam = { yaw: opts.yaw || 0.5, pitch: opts.pitch || 0.35, dist: opts.dist || 900, spin: RM ? 0 : (opts.spin || 0.0006), dragging: false };
    let px, py, moved = 0;
    canvas.addEventListener('pointerdown', e => { cam.dragging = true; px = e.clientX; py = e.clientY; moved = 0; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener('pointermove', e => { if (!cam.dragging) return; const dx = e.clientX - px, dy = e.clientY - py; moved += Math.abs(dx) + Math.abs(dy); cam.yaw += dx * 0.006; cam.pitch = Math.max(-1.2, Math.min(1.2, cam.pitch + dy * 0.004)); px = e.clientX; py = e.clientY; });
    canvas.addEventListener('pointerup', e => { cam.dragging = false; if (moved < 6 && opts.onTap) opts.onTap(e.offsetX, e.offsetY); });
    cam.project = (x, y, z, W, H) => {
      const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
      let X = x * cy - z * sy, Z = x * sy + z * cy, Y = y * cp - Z * sp; Z = y * sp + Z * cp;
      const f = cam.dist / (cam.dist + Z), s = Math.min(W, H) / 900;
      return { x: W / 2 + X * f * s, y: H / 2 + Y * f * s, f, z: Z };
    };
    cam.tick = dt => { if (!cam.dragging) cam.yaw += cam.spin * dt; };
    return cam;
  }

  function fitCanvas(cv) { const r = cv.getBoundingClientRect(), dpr = devicePixelRatio || 1; if (cv.width !== Math.round(r.width * dpr)) { cv.width = r.width * dpr; cv.height = r.height * dpr; } const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); return { c, W: r.width, H: r.height }; }
  function glow(c, color, k) { c.shadowColor = color; c.shadowBlur = 10 * 0.6 * (k || 1); }  // --glow 0.6 (owner decision)
  const narrow = () => innerWidth < 900;

  // deep link for screenshots and sharing: #at=<local ISO hour, e.g. 2026-10-22T09>&sel=<node id>
  const hash = Object.fromEntries(location.hash.slice(1).split('&').filter(Boolean).map(kv => kv.split('=').map(decodeURIComponent)));
  const idxOf = (startT, n) => { if (!hash.at) return null; const t = new Date(hash.at + ':00').getTime() / 1000; const i = Math.floor((t - startT) / D.window.bucket_s); return Math.max(0, Math.min(n - 1, i)); };
  window.V4 = { hash, idxOf, D, RM, COL, byId, mById, downstream, show, showNode, scrubber, camera, fitCanvas, glow, narrow, nodeLabel, fmtT, fmtH, esc, endT, panel };
})();
