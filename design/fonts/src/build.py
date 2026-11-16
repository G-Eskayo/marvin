"""Builds MARVIN Term (marvin#1054) from the pixel source into design/fonts/.
  build.py        -> MarvinTerm-Beam.ttf      (proportional, for the dashboard)
  build.py mono   -> MarvinTermMono-Beam.ttf  (fixed 12-pixel cell, for WezTerm)
Beam is the chosen cut (2026-11-03): scan rows drawn as round-ended beam strokes, 60% of a row tall.
Run: ~/.agents/venv/bin/python design/fonts/src/build.py [mono] [--out DIR]"""
import sys, pathlib
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import importlib
ARGS = [a for a in sys.argv[1:]]
OUT = pathlib.Path(ARGS[ARGS.index('--out') + 1]) if '--out' in ARGS else HERE.parent
VER = next((a for a in ARGS if not a.startswith('--') and pathlib.Path(a) != OUT), '')
G = importlib.import_module('glyphs_' + VER if VER else 'glyphs').G
MONO = VER == 'mono'
CELL = 480       # mono cell: 12 px

P = 40            # one pixel, in font units
SB = 60           # side bearing each side (1.5 px): 3 px between letters
SPACE = 300       # word space (7.5 px)
DESC_CHARS = set('gjpqy,;Q_|()[]{}$@ýÿçÇ')

def check():
    bad = []
    for ch, (top, rows) in G.items():
        if len({len(r) for r in rows}) != 1:
            bad.append(f"{ch!r}: uneven row lengths {[len(r) for r in rows]}")
        bottom = top - len(rows) + 1
        if ch.isalnum() and ch not in DESC_CHARS and bottom != 0:
            bad.append(f"{ch!r}: bottom row {bottom}, expected 0")
        if ch in 'gjpqyýÿ' and bottom != -4:
            bad.append(f"{ch!r}: bottom row {bottom}, expected -4")
    return bad

def cells(ch):
    top, rows = G[ch]
    return {(c, top - i) for i, r in enumerate(rows) for c, v in enumerate(r) if v == '#'}

def trace(filled):
    """Union of pixel squares as closed contours, outer clockwise (TrueType), holes counter-clockwise."""
    edges = {}
    for (c, r) in filled:
        x0, y0, x1, y1 = c, r, c + 1, r + 1
        for a, b in (((x0, y1), (x1, y1)), ((x1, y1), (x1, y0)), ((x1, y0), (x0, y0)), ((x0, y0), (x0, y1))):
            if (b, a) in edges: del edges[(b, a)]
            else: edges[(a, b)] = True
    out = {}
    for a, b in edges: out.setdefault(a, []).append(b)
    loops = []
    while out:
        start = next(iter(out)); a = start; b = out[a].pop()
        if not out[a]: del out[a]
        loop = [a]
        while b != start:
            d = (b[0] - a[0], b[1] - a[1]); right = (d[1], -d[0]); left = (-d[1], d[0])
            opts = out[b]
            pick = next((n for pref in (right, d, left) for n in opts if (n[0] - b[0], n[1] - b[1]) == pref), opts[0])
            opts.remove(pick)
            if not opts: del out[b]
            loop.append(b); a, b = b, pick
        # drop collinear points
        pts = [p for i, p in enumerate(loop) if not ((loop[i - 1][0] == p[0] == loop[(i + 1) % len(loop)][0]) or (loop[i - 1][1] == p[1] == loop[(i + 1) % len(loop)][1]))]
        loops.append(pts)
    return loops

from math import cos, sin, radians

def _arc_pts(cx, cy, r, angles):
    """Off-curve points for a quadratic circle: each sits on the tangent lines, so the implied on-curve midpoints
    between neighbours land on the circle (8 segments per full turn)."""
    R = r / cos(radians(22.5))
    return [(round(cx + R * cos(radians(a))), round(cy + R * sin(radians(a)))) for a in angles]

def circle(pen, cx, cy, r):
    pts = _arc_pts(cx, cy, r, [112.5 - 45 * k for k in range(8)])   # clockwise
    pen.qCurveTo(*pts, None)
    pen.closePath()

def capsule(pen, x0, x1, y0, y1):
    """A horizontal stroke with round ends, clockwise. Short runs shrink to a circle."""
    r = (y1 - y0) / 2; cy = (y0 + y1) / 2
    lc, rc = x0 + r, x1 - r
    if rc <= lc:
        circle(pen, (x0 + x1) / 2, cy, r); return
    pen.moveTo((round(lc), round(y1)))
    pen.lineTo((round(rc), round(y1)))
    a, b, c_, d = _arc_pts(rc, cy, r, [67.5, 22.5, -22.5, -67.5])
    pen.qCurveTo(a, b, (round(rc + r), round(cy)))
    pen.qCurveTo(c_, d, (round(rc), round(y0)))
    pen.lineTo((round(lc), round(y0)))
    a, b, c_, d = _arc_pts(lc, cy, r, [-112.5, -157.5, 157.5, 112.5])
    pen.qCurveTo(a, b, (round(lc - r), round(cy)))
    pen.qCurveTo(c_, d, (round(lc), round(y1)))
    pen.closePath()

def runs_of(f):
    for r in sorted({r for _, r in f}):
        cs = sorted(c for c, rr in f if rr == r); s = p = cs[0]
        for c in cs[1:]:
            if c == p + 1: p = c; continue
            yield r, s, p; s = p = c
        yield r, s, p

def draw(ch, style):
    pen = TTGlyphPen(None)
    f = cells(ch)
    if not f: return pen.glyph(), 0, 0
    minc = min(c for c, _ in f); maxc = max(c for c, _ in f)
    ox = (round((CELL - (maxc - minc + 1) * P) / 2 / 20) * 20 if MONO else SB) - minc * P
    if style == 'solid':
        for loop in trace(f):
            pen.moveTo((loop[0][0] * P + ox, loop[0][1] * P))
            for x, y in loop[1:]: pen.lineTo((x * P + ox, y * P))
            pen.closePath()
    elif style == 'dots':  # every pixel a round beam spot, 82% of a pixel across, so neighbours nearly touch
        rad = P * .41
        for (c, r) in sorted(f):
            circle(pen, c * P + ox + P / 2, r * P + P / 2, rad)
    elif style == 'beam':  # scan rows drawn as beam strokes with round ends, 60% of a row tall
        h = P * .60
        for r, a, b in runs_of(f):
            capsule(pen, a * P + ox, (b + 1) * P + ox, (r + 1) * P - h, (r + 1) * P)
    else:  # scan: each pixel row lit for 60% of its height, so CRT scanlines show between rows
        h = int(P * .60)
        for r in sorted({r for _, r in f}):
            cs = sorted(c for c, rr in f if rr == r); runs = []; s = p = cs[0]
            for c in cs[1:]:
                if c == p + 1: p = c; continue
                runs.append((s, p)); s = p = c
            runs.append((s, p))
            for a, b in runs:
                x0, x1, y1 = a * P + ox, (b + 1) * P + ox, (r + 1) * P
                y0 = y1 - h
                for pt in ((x0, y0), (x0, y1), (x1, y1), (x1, y0)):
                    (pen.moveTo if pt == (x0, y0) else pen.lineTo)(pt)
                pen.closePath()
    adv = CELL if MONO else (maxc - minc + 1) * P + 2 * SB
    return pen.glyph(), adv, ox + minc * P

def build(style, path):
    names = {ch: (f"uni{ord(ch):04X}") for ch in G}
    order = ['.notdef', 'space'] + [names[c] for c in G]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(order)
    cmap = {32: 'space', 160: 'space'}; cmap.update({ord(c): names[c] for c in G})
    fb.setupCharacterMap(cmap)
    glyf, hmtx = {}, {}
    nd = TTGlyphPen(None)
    for pt in ((60, 0), (60, 560), (380, 560), (380, 0)): (nd.moveTo if pt == (60, 0) else nd.lineTo)(pt)
    nd.closePath(); glyf['.notdef'] = nd.glyph(); hmtx['.notdef'] = (CELL if MONO else 440, 60)
    glyf['space'] = TTGlyphPen(None).glyph(); hmtx['space'] = (CELL if MONO else SPACE, 0)
    for ch in G:
        gl, adv, lsb = draw(ch, style)
        glyf[names[ch]] = gl; hmtx[names[ch]] = (adv, lsb)
    fb.setupGlyf(glyf)
    fb.setupHorizontalMetrics(hmtx)
    fb.setupHorizontalHeader(ascent=800, descent=-240)
    sub = style.capitalize()
    fb.setupNameTable({'familyName': 'MARVIN Term Mono' if MONO else 'MARVIN Term', 'version': 'Version 0.3', 'styleName': sub, 'uniqueFontIdentifier': ('MARVINTermMono-' if MONO else 'MARVINTerm-') + sub,
                       'fullName': ('MARVIN Term Mono ' if MONO else 'MARVIN Term ') + sub, 'psName': ('MARVINTermMono-' if MONO else 'MARVINTerm-') + sub,
                       'licenseDescription': 'SIL Open Font License 1.1. Construction after VT323 (OFL); legibility rules after Atkinson Hyperlegible (OFL).'})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-240, sTypoLineGap=120, usWinAscent=840, usWinDescent=240, sxHeight=440, sCapHeight=560, achVendID='MRVN')
    fb.setupPost(isFixedPitch=1 if MONO else 0)
    fb.save(path)

if __name__ == '__main__':
    bad = check()
    if bad:
        print('\n'.join(bad)); sys.exit(1)
    OUT.mkdir(parents=True, exist_ok=True)
    name = 'MarvinTermMono-Beam.ttf' if MONO else 'MarvinTerm-Beam.ttf'
    build('beam', OUT / name)
    print('built', len(G), 'glyphs ->', OUT / name)
