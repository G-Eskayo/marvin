#!/usr/bin/env python3
"""Thematic motifs for the portfolio's generated hero images.

Each motif is a small diagram that *means* something about the project it stands for (a network graph for
MARVIN, a mancala board for the mancala project, an ATT&CK-style matrix for MITRE...). A motif is drawn
as bright structure on black into a float field in 0..1; portfolio_imagegen then gradient-maps it with the
palette taken from the project's existing image, so colour still comes from the existing art while the
subject comes from here.

Deterministic: every random choice comes from the RandomState the caller seeds from the project slug.
Which motif a slug gets is DEFAULT_MOTIFS, overridable per slug in portfolio/image-motifs.json.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OVERRIDES_PATH = Path(__file__).resolve().parents[1] / "portfolio" / "image-motifs.json"
REF_SIZE = (2200, 600)  # the hero banner the motifs are laid out for
SS = 2  # supersampling factor, for anti-aliased lines

DEFAULT_MOTIFS = {
    "marvin": "network",
    "marketplace-ml-agent": "network",
    "paper-dive": "citations",
    "distributed-llm-inference": "two-nodes",
    "regression-and-classification": "regression",
    "anomaly-detection": "outliers",
    "mancala": "mancala",
    "random-number": "histogram",
    "killer-sudoku": "sudoku",
    "mitre": "matrix",
    "bug-bounty": "crosshair",
    "resume-selector": "documents",
    "resume-tailor": "documents-tailored",
    "pipeline": "pipeline",
    "clarity-captions": "waveform",
    "algorithms": "tree",
    "helicopter-crutches": "rotor",
    "skineedipping": "storefront",
}


def motif_for(slug: str, overrides_path: Path = OVERRIDES_PATH) -> str | None:
    try:
        overrides = json.loads(Path(overrides_path).read_text())
        if isinstance(overrides, dict) and slug in overrides:
            return overrides[slug] or None
    except (OSError, ValueError):
        pass
    return DEFAULT_MOTIFS.get(slug)


# ── drawing helpers (all coordinates are in final-image pixels; scaled by SS inside) ──

class _Canvas:
    def __init__(self, size):
        self.w, self.h = size
        self.img = Image.new("L", (self.w * SS, self.h * SS), 0)
        self.d = ImageDraw.Draw(self.img)

    def _s(self, pts):
        return [(x * SS, y * SS) for x, y in pts]

    def line(self, pts, v=255, width=2):
        self.d.line(self._s(pts), fill=v, width=max(1, int(width * SS)), joint="curve")

    def dot(self, x, y, r, v=255, fill=True, width=2):
        box = [(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS]
        if fill:
            self.d.ellipse(box, fill=v)
        else:
            self.d.ellipse(box, outline=v, width=max(1, int(width * SS)))

    def rect(self, x0, y0, x1, y1, v=255, fill=False, width=2, radius=0):
        box = [x0 * SS, y0 * SS, x1 * SS, y1 * SS]
        if radius:
            self.d.rounded_rectangle(box, radius * SS, fill=v if fill else None, outline=None if fill else v, width=max(1, int(width * SS)))
        elif fill:
            self.d.rectangle(box, fill=v)
        else:
            self.d.rectangle(box, outline=v, width=max(1, int(width * SS)))

    def polygon(self, pts, v=255):
        self.d.polygon(self._s(pts), fill=v)

    def result(self) -> np.ndarray:
        small = self.img.resize((self.w, self.h), Image.LANCZOS)
        crisp = np.asarray(small, dtype=np.float32) / 255.0
        glow = np.asarray(small.filter(ImageFilter.GaussianBlur(7)), dtype=np.float32) / 255.0
        return np.clip(np.maximum(crisp, glow * 0.85), 0, 1)


def _graph(c, rng, n, hubs=0, spread=1.0, edge_v=110):
    """Random geometric-ish graph filling the banner. Returns the node positions."""
    pts = np.column_stack([rng.uniform(0.04, 0.96, n) * c.w, rng.uniform(0.1, 0.9, n) * c.h])
    for i in range(n):
        d = np.hypot(*(pts - pts[i]).T)
        for j in np.argsort(d)[1 : 3 + (i % 2)]:
            c.line([tuple(pts[i]), tuple(pts[j])], v=edge_v, width=1.6)
    return pts


# ── motifs ──────────────────────────────────────────────────────────────────

def _network(c, rng):
    pts = _graph(c, rng, 46)
    hub = rng.choice(len(pts), 5, replace=False)
    for i, p in enumerate(pts):
        c.dot(*p, r=16 if i in hub else rng.uniform(4, 8), v=255 if i in hub else 200)
        if i in hub:
            c.dot(*p, r=30, fill=False, v=140, width=2)


def _citations(c, rng):
    pts = _graph(c, rng, 38, edge_v=90)
    size = rng.uniform(5, 26, len(pts))
    for p, r in zip(pts, size):
        c.dot(*p, r=r, fill=False, v=210, width=2.5)
        c.dot(*p, r=max(2, r * 0.3), v=255)


def _two_nodes(c, rng):
    for cx, w in ((c.w * 0.2, 0.9), (c.w * 0.8, 1.1)):
        c.rect(cx - 150, c.h * 0.22, cx + 150, c.h * 0.78, v=230, width=3, radius=18)
        for k in range(4):
            y = c.h * 0.32 + k * c.h * 0.12
            c.rect(cx - 110, y, cx + 110 * (0.4 + 0.6 * rng.random()), y + 22, v=200, fill=True, radius=6)
    for k in range(5):  # packets travelling across the tunnel
        y = c.h * 0.5 + (k - 2) * 26
        c.line([(c.w * 0.2 + 170, y), (c.w * 0.8 - 170, y)], v=110, width=1.5)
        for t in rng.uniform(0.05, 0.95, 4):
            x = c.w * 0.2 + 170 + t * (c.w * 0.6 - 340)
            c.rect(x - 14, y - 7, x + 14, y + 7, v=255, fill=True, radius=3)


def _regression(c, rng):
    n = 90
    xs = rng.uniform(0.05, 0.95, n) * c.w
    cls = rng.random(n) < 0.5
    ys = c.h * (0.78 - 0.55 * xs / c.w) + np.where(cls, -1, 1) * rng.uniform(25, 110, n)
    for x, y, k in zip(xs, ys, cls):
        if k:
            c.dot(x, y, 9, v=255)
        else:
            c.rect(x - 8, y - 8, x + 8, y + 8, v=200, width=3)
    c.line([(c.w * 0.03, c.h * 0.8), (c.w * 0.97, c.h * 0.18)], v=255, width=4)
    c.line([(c.w * 0.03, c.h * 0.8 + 60), (c.w * 0.97, c.h * 0.18 + 60)], v=100, width=1.5)
    c.line([(c.w * 0.03, c.h * 0.8 - 60), (c.w * 0.97, c.h * 0.18 - 60)], v=100, width=1.5)


def _outliers(c, rng):
    n = 260
    cx, cy = c.w * 0.5, c.h * 0.52
    xs, ys = rng.normal(cx, c.w * 0.13, n), rng.normal(cy, c.h * 0.14, n)
    for x, y in zip(xs, ys):
        c.dot(x, y, rng.uniform(4, 8), v=215)
    for x, y in ((c.w * 0.1, c.h * 0.2), (c.w * 0.88, c.h * 0.8), (c.w * 0.82, c.h * 0.16), (c.w * 0.14, c.h * 0.82)):
        x, y = x + rng.uniform(-60, 60), y + rng.uniform(-30, 30)
        c.dot(x, y, 8, v=255)
        c.dot(x, y, 30, fill=False, v=255, width=3)
        c.line([(x, y), (cx, cy)], v=70, width=1.2)


def _mancala(c, rng):
    bx0, bx1, by0, by1 = c.w * 0.1, c.w * 0.9, c.h * 0.12, c.h * 0.88
    c.rect(bx0, by0, bx1, by1, v=230, width=4, radius=60)
    c.rect(bx0 + 24, c.h * 0.3, bx0 + 140, c.h * 0.7, v=200, width=3, radius=50)
    c.rect(bx1 - 140, c.h * 0.3, bx1 - 24, c.h * 0.7, v=200, width=3, radius=50)
    pw = (bx1 - bx0 - 360) / 6
    for row, cy in enumerate((c.h * 0.36, c.h * 0.64)):
        for i in range(6):
            cx = bx0 + 180 + pw * (i + 0.5)
            c.dot(cx, cy, pw * 0.36, v=210, fill=False, width=3)
            for _ in range(int(rng.randint(0, 6))):
                a, r = rng.uniform(0, 2 * math.pi), rng.uniform(0, pw * 0.2)
                c.dot(cx + r * math.cos(a), cy + r * math.sin(a), 9, v=255)
    for x in (bx0 + 82, bx1 - 82):
        for _ in range(int(rng.randint(3, 9))):
            c.dot(x + rng.uniform(-22, 22), c.h * 0.5 + rng.uniform(-90, 90), 9, v=255)


def _histogram(c, rng):
    bars = 28
    bw = c.w * 0.86 / bars
    for i in range(bars):  # a roughly uniform distribution with sampling noise
        hgt = c.h * (0.5 + rng.normal(0, 0.07))
        x0 = c.w * 0.07 + i * bw
        c.rect(x0 + 3, c.h * 0.86 - hgt, x0 + bw - 3, c.h * 0.86, v=215, fill=True)
    c.line([(c.w * 0.05, c.h * 0.86), (c.w * 0.95, c.h * 0.86)], v=255, width=3)
    c.line([(c.w * 0.05, c.h * 0.86 - c.h * 0.5), (c.w * 0.95, c.h * 0.86 - c.h * 0.5)], v=255, width=2)  # expected value
    for x, y in zip(rng.uniform(0.06, 0.94, 70) * c.w, rng.uniform(0.06, 0.2, 70) * c.h):
        c.dot(x, y, 3.5, v=180)


def _sudoku(c, rng):
    size = c.h * 0.8
    x0, y0 = rng.uniform(c.w * 0.12, c.w - size - c.w * 0.12), c.h * 0.1   # position varies with the seed, so a re-roll moves the grid
    cell = size / 9
    for i in range(10):
        thick = i % 3 == 0
        c.line([(x0 + i * cell, y0), (x0 + i * cell, y0 + size)], v=255 if thick else 90, width=4 if thick else 1.2)
        c.line([(x0, y0 + i * cell), (x0 + size, y0 + i * cell)], v=255 if thick else 90, width=4 if thick else 1.2)
    for _ in range(22):  # killer cages: a rectangle of 2-3 cells outlined inset
        gx, gy = int(rng.randint(0, 8)), int(rng.randint(0, 8))
        gw, gh = (2, 1) if rng.random() < 0.5 else (1, 2)
        c.rect(x0 + gx * cell + 7, y0 + gy * cell + 7, x0 + (gx + gw) * cell - 7, y0 + (gy + gh) * cell - 7, v=170, width=1.6)
    for _ in range(16):
        gx, gy = int(rng.randint(0, 9)), int(rng.randint(0, 9))
        c.dot(x0 + (gx + 0.5) * cell, y0 + (gy + 0.5) * cell, 7, v=255)
    for side in (0.12, 0.88):  # echo the grid's lines out to the margins
        for k in range(6):
            y = c.h * (0.15 + 0.14 * k)
            c.line([(c.w * (side - 0.07), y), (c.w * (side + 0.07), y)], v=70, width=1.5)


def _matrix(c, rng):
    cols = 14
    cw = c.w * 0.9 / cols
    for i in range(cols):
        x0 = c.w * 0.05 + i * cw
        c.rect(x0 + 3, c.h * 0.08, x0 + cw - 3, c.h * 0.2, v=255, fill=True)
        for j in range(int(rng.randint(3, 9))):
            y0 = c.h * 0.24 + j * 46
            hit = rng.random() < 0.18
            c.rect(x0 + 3, y0, x0 + cw - 3, y0 + 36, v=255 if hit else 120, fill=hit, width=2)


def _crosshair(c, rng):
    cx, cy = c.w * 0.5, c.h * 0.5
    for gx in range(0, c.w, 70):  # a target surface
        c.line([(gx, 0), (gx, c.h)], v=40, width=1)
    for gy in range(0, c.h, 70):
        c.line([(0, gy), (c.w, gy)], v=40, width=1)
    for r in (70, 150, 230):
        c.dot(cx, cy, r, fill=False, v=235, width=3)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        c.line([(cx + dx * 40, cy + dy * 40), (cx + dx * 290, cy + dy * 290)], v=255, width=3)
    c.dot(cx, cy, 8, v=255)
    for _ in range(9):  # findings pinned on the surface
        x, y = rng.uniform(0.05, 0.95) * c.w, rng.uniform(0.1, 0.9) * c.h
        c.dot(x, y, 6, v=210)
        c.dot(x, y, 16, fill=False, v=150, width=2)


def _documents(c, rng, tailored=False):
    n = 9
    pick = int(rng.randint(0, n))
    for i in range(n):
        x0 = c.w * 0.04 + i * c.w * 0.105
        y0 = c.h * (0.18 + 0.1 * math.sin(i * 1.3))
        hit = i == pick
        c.rect(x0, y0, x0 + 150, y0 + 330, v=255 if hit else 140, width=4 if hit else 2, radius=8)
        for k in range(9):
            lw = 110 * (0.45 + 0.55 * rng.random())
            lit = tailored and hit and k in (2, 3, 6)
            c.line([(x0 + 20, y0 + 40 + k * 31), (x0 + 20 + lw, y0 + 40 + k * 31)], v=255 if (hit and (not tailored or lit)) else 90, width=5 if lit else 3)
        if hit:
            c.dot(x0 + 150, y0, 22, v=255)
            c.line([(x0 + 140, y0), (x0 + 148, y0 + 9), (x0 + 164, y0 - 9)], v=0, width=4)


def _pipeline(c, rng):
    stages = 6
    sw = c.w * 0.1
    for i in range(stages):
        x0 = c.w * 0.07 + i * c.w * 0.153
        c.rect(x0, c.h * 0.32, x0 + sw, c.h * 0.68, v=240, width=3, radius=14)
        for k in range(3):
            y = c.h * 0.4 + k * c.h * 0.08
            c.line([(x0 + 18, y), (x0 + sw - 18 - 30 * rng.random(), y)], v=150, width=3)
        if i < stages - 1:
            ax = x0 + sw
            c.line([(ax + 10, c.h * 0.5), (ax + c.w * 0.153 - sw - 22, c.h * 0.5)], v=255, width=3)
            c.polygon([(ax + c.w * 0.153 - sw - 10, c.h * 0.5), (ax + c.w * 0.153 - sw - 30, c.h * 0.5 - 12), (ax + c.w * 0.153 - sw - 30, c.h * 0.5 + 12)])
    for x, y in zip(rng.uniform(0.03, 0.97, 60) * c.w, rng.uniform(0.44, 0.56, 60) * c.h):
        c.dot(x, y, 3, v=200)


def _waveform(c, rng):
    n = 220
    env = np.abs(np.sin(np.linspace(0, 6 * math.pi, n) + rng.uniform(0, 3))) ** 0.8 * (0.35 + 0.65 * rng.random(n))
    step = c.w * 0.92 / n
    for i, e in enumerate(env):
        x = c.w * 0.04 + i * step
        c.line([(x, c.h * 0.4 - e * c.h * 0.3), (x, c.h * 0.4 + e * c.h * 0.3)], v=255, width=step * 0.55)
    x = c.w * 0.1
    for _ in range(3):  # caption lines
        lines = [rng.uniform(0.14, 0.28) for _ in range(2)]
        for k, lw in enumerate(lines):
            c.rect(x, c.h * (0.78 + 0.09 * k), x + c.w * lw, c.h * (0.78 + 0.09 * k) + 26, v=235, fill=True, radius=8)
        x += c.w * 0.3


def _tree(c, rng):
    depth = 6
    path = [int(rng.randint(0, 2)) for _ in range(depth)]
    def node(level, idx, x, span, on_path):
        y = c.h * (0.1 + level * 0.13)
        if level < depth:
            for b in (0, 1):
                nx = x + (b - 0.5) * span
                child_on = on_path and path[level] == b
                c.line([(x, y), (nx, c.h * (0.1 + (level + 1) * 0.13))], v=255 if child_on else 90, width=4 if child_on else 1.5)
                node(level + 1, idx * 2 + b, nx, span / 2, child_on)
        c.dot(x, y, 13 if on_path else 8, v=255 if on_path else 170)
    node(0, 0, c.w * 0.5, c.w * 0.5, True)


def _rotor(c, rng):
    cx, cy = c.w * 0.5, c.h * 0.5
    R = c.h * 0.46
    for k in range(40):  # motion-blurred blade sweep
        a = k * 0.05
        c.line([(cx, cy), (cx + R * 3.2 * math.cos(a), cy + R * math.sin(a))], v=int(40 + 4 * k), width=2)
    c.dot(cx, cy, R, fill=False, v=120, width=1.5)
    for blade in range(4):
        a = blade * math.pi / 2 + 0.5
        c.polygon([(cx, cy), (cx + R * 3.1 * math.cos(a) - 12 * math.sin(a), cy + R * 0.95 * math.sin(a) + 12 * math.cos(a)),
                   (cx + R * 3.1 * math.cos(a) + 12 * math.sin(a), cy + R * 0.95 * math.sin(a) - 12 * math.cos(a))], v=235)
    c.dot(cx, cy, 24, v=255)
    for k in range(7):  # crutch: a support strut with cross bracing
        x = cx - 330 + k * 110
        c.line([(x, c.h * 0.9), (x + 55, c.h * 0.74)], v=255, width=4)
        c.line([(x + 55, c.h * 0.74), (x + 110, c.h * 0.9)], v=255, width=4)
    c.line([(cx - 330, c.h * 0.9), (cx + 330, c.h * 0.9)], v=255, width=5)


def _storefront(c, rng):
    cols, rows = 10, 2
    tw, th = c.w * 0.082, c.h * 0.36
    for r in range(rows):
        for i in range(cols):
            x0, y0 = c.w * 0.05 + i * c.w * 0.093, c.h * (0.1 + r * 0.45)
            c.rect(x0, y0, x0 + tw, y0 + th, v=210, width=3, radius=10)
            for s in range(int(rng.randint(3, 8))):  # the skin's diagonal stripes
                off = s * 26
                c.line([(x0 + 10 + off % (tw - 20), y0 + 12), (x0 + 10, y0 + 12 + off % (th - 60))], v=int(rng.randint(120, 255)), width=5)
            c.rect(x0 + 10, y0 + th - 34, x0 + tw - 10, y0 + th - 10, v=255, fill=True, radius=6)


_MOTIFS = {
    "network": _network, "citations": _citations, "two-nodes": _two_nodes, "regression": _regression,
    "outliers": _outliers, "mancala": _mancala, "histogram": _histogram, "sudoku": _sudoku,
    "matrix": _matrix, "crosshair": _crosshair, "documents": _documents,
    "documents-tailored": lambda c, rng: _documents(c, rng, tailored=True), "pipeline": _pipeline,
    "waveform": _waveform, "tree": _tree, "rotor": _rotor, "storefront": _storefront,
}
MOTIF_NAMES = tuple(_MOTIFS)


def draw(motif: str, size, rng: np.random.RandomState) -> np.ndarray:
    """The motif as a float32 field (h, w) in 0..1, bright structure on black."""
    if motif not in _MOTIFS:
        raise ValueError(f"unknown motif: {motif!r}")
    # Motifs are laid out in pixels for the real hero banner; other sizes (thumbnails, tests) are a resample.
    c = _Canvas(REF_SIZE)
    _MOTIFS[motif](c, rng)
    field = c.result()
    if tuple(size) == REF_SIZE:
        return field
    out = Image.fromarray((field * 255).astype(np.uint8)).resize(tuple(size), Image.LANCZOS)
    return np.asarray(out, dtype=np.float32) / 255.0
