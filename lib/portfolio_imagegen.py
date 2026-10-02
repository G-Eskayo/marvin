#!/usr/bin/env python3
"""Deterministic generative hero images for portfolio projects.

Decided 2026-10-02 (Gil): unique art keyed to each project's slug -- same slug, same image --
in a palette inspired by the project's own image (the site's black-and-white look is a CSS effect, so colour is fine), at zero API cost. A project's existing images are
NEVER the key photo; they only INSPIRE the generator: their measured brightness, contrast and
tint steer its parameters (`inspiration_from`). No pixels are ever composited. Motivation:
6 of 17 projects shared one stock thumbnail (work001-01.jpg).

Uniqueness is enforced, not assumed: every image gets a 128-bit fingerprint (layout dHash + spectral texture hash) and a
new image that lands too close to an already-assigned one is re-rolled with a deterministic salt.
The registry (slug -> salt/hash) keeps assignments stable, so adding a project can never change
an existing project's image.

CLI:  portfolio_imagegen.py SLUG [--out PATH] [--inspire IMG ...]
"""
from __future__ import annotations
import colorsys
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_motifs  # noqa: E402

HERO_SIZE = (2200, 600)       # the site's wide panorama hero (existing hero photos are ~3.66:1)
MIN_DISTANCE = 24             # minimum Hamming distance (of 128 bits: layout + spectrum) between any two projects
STYLES = ("contours", "moire", "cubes", "halftone", "lines")
NEUTRAL_INSPIRATION = {"luminance": 0.45, "contrast": 0.5, "hue": None, "hues": [], "saturation": 0.0}
DEFAULT = object()    # "use this project's default motif" (None means: no motif, the abstract pattern)
IMAGES_DIR = Path.home() / ".claude" / "portfolio" / "images"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "portfolio" / "image-registry.json"


# ── perceptual hash ─────────────────────────────────────────────────────────

def dhash(img: Image.Image) -> int:
    g = np.asarray(img.convert("L").resize((9, 8), Image.LANCZOS), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def spectral_hash(img: Image.Image, rad: int = 8, ang: int = 8) -> int:
    """64 bits describing which spatial frequencies and orientations the image contains
    (radial x angular bands of the 2-D power spectrum, thresholded at their median). Unlike dHash it
    sees fine textures (a very fine weave averages to flat grey at dHash's 9x8 resolution) and it is
    phase-independent, which is what "looks alike" means for a texture."""
    g = np.asarray(img.convert("L").resize((512, 144), Image.LANCZOS), dtype=np.float32)
    g = (g - g.mean()) * np.outer(np.hanning(g.shape[0]), np.hanning(g.shape[1]))
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(g)))
    h, w = spectrum.shape
    yy, xx = np.mgrid[-h // 2:h // 2, -w // 2:w // 2]
    r = np.clip(np.sqrt((xx / (w / 2)) ** 2 + (yy / (h / 2)) ** 2), 0, 0.999)
    a = (np.arctan2(yy, xx) % np.pi) / np.pi                              # orientation modulo 180 degrees
    band = (np.minimum((np.log1p(r * 40) / np.log1p(40) * rad).astype(int), rad - 1) * ang
            + np.minimum((a * ang).astype(int), ang - 1))
    vec = np.array([np.log1p(spectrum[band == k].mean()) if (band == k).any() else 0.0 for k in range(rad * ang)])
    return int("".join("1" if b else "0" for b in vec > np.median(vec)), 2)


def fingerprint(img: Image.Image) -> int:
    """128 bits: layout (dHash) in the high half, texture/frequency (spectral) in the low half."""
    return (dhash(img) << 64) | spectral_hash(img)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ── inspiration (statistics only, never pixels) ─────────────────────────────

def inspiration_from(paths) -> dict:
    stats = []
    for p in paths:
        try:
            im = Image.open(p).convert("RGB").resize((64, 64))
        except (OSError, ValueError):
            continue
        a = np.asarray(im, dtype=np.float32) / 255.0
        luma = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
        flat = a.reshape(-1, 3)
        hsv = np.array([colorsys.rgb_to_hsv(*px) for px in flat[::7]])
        sat = float(hsv[:, 1].mean())
        weights = hsv[:, 1] + 1e-6
        hue = float(np.degrees(np.arctan2((np.sin(hsv[:, 0] * 2 * np.pi) * weights).sum(),
                                          (np.cos(hsv[:, 0] * 2 * np.pi) * weights).sum())) % 360)
        stats.append((float(luma.mean()), float(min(1.0, luma.std() / 0.5)), hue if sat > 0.05 else None, sat, _dominant_hues(hsv)))
    if not stats:
        return dict(NEUTRAL_INSPIRATION)
    hues = [s[2] for s in stats if s[2] is not None]
    palette = max(stats, key=lambda s: s[3])[4]          # the most colourful source image decides the palette
    return {"luminance": float(np.mean([s[0] for s in stats])), "contrast": float(np.mean([s[1] for s in stats])),
            "hue": float(np.mean(hues)) if hues else None, "hues": palette, "saturation": float(np.mean([s[3] for s in stats]))}


def _dominant_hues(hsv: np.ndarray) -> list[float]:
    """The two strongest hues (degrees) in an image, weighted by how saturated and bright each pixel is.
    The second is at least 50 degrees from the first, or the first shifted 40 degrees if there is none."""
    weights = hsv[:, 1] * hsv[:, 2]
    if weights.sum() < 1e-6 or hsv[:, 1].mean() < 0.06:
        return []
    bins = np.zeros(12)
    for h, w in zip(hsv[:, 0], weights):
        bins[int(h * 12) % 12] += w
    def refine(center_deg: float) -> float:
        """Weighted circular mean of the pixels within 30 degrees of a bin centre -- the true hue, not the bin's midpoint."""
        ang = hsv[:, 0] * 360.0
        gap = np.minimum(np.abs(ang - center_deg), 360 - np.abs(ang - center_deg))
        w = weights * (gap <= 30)
        if w.sum() < 1e-9:
            return center_deg
        rad = np.radians(ang)
        return float(np.degrees(np.arctan2((np.sin(rad) * w).sum(), (np.cos(rad) * w).sum())) % 360)

    first = int(bins.argmax())
    first_deg = refine((first + 0.5) * 30.0)
    far = [(bins[i], i) for i in range(12) if min(abs(i - first), 12 - abs(i - first)) >= 2 and bins[i] > 0.15 * bins[first]]
    second_deg = refine((max(far)[1] + 0.5) * 30.0) if far else (first_deg + 40.0) % 360
    return [float(first_deg), float(second_deg)]


# ── generation ──────────────────────────────────────────────────────────────

def _digest(slug: str, salt: int = 0) -> int:
    return int(hashlib.sha256(f"{slug}:{salt}".encode()).hexdigest()[:8], 16)


def style_for(slug: str) -> str:
    """Style depends on the slug only (not the salt), so re-rolling a collision keeps the look."""
    return STYLES[int(hashlib.sha256(slug.encode()).hexdigest()[:2], 16) % len(STYLES)]


def look_for(slug: str) -> str:
    return portfolio_motifs.motif_for(slug) or style_for(slug)


def _field(X, Y, rng, octaves=4):
    """Smooth pseudo-noise: a sum of randomly oriented sine waves."""
    f = np.zeros_like(X)
    for i in range(octaves):
        ang, freq, phase = rng.uniform(0, 2 * np.pi), rng.uniform(1.2, 3.2) * (1.6 ** i), rng.uniform(0, 2 * np.pi)
        f += np.sin(2 * np.pi * freq * (X * np.cos(ang) + Y * np.sin(ang)) + phase) / (1.3 ** i)
    return f


def _smooth(v, softness=0.12):
    return np.clip(v / softness * 0.5 + 0.5, 0.0, 1.0)


def _pattern(style, X, Y, rng):
    if style == "contours":
        v = np.sin(_field(X, Y, rng) * rng.uniform(2.5, 5.5))
        return _smooth(v, 0.35)
    if style == "moire":
        a1, a2 = rng.uniform(0, np.pi), rng.uniform(0, np.pi)
        f1, f2 = rng.uniform(14, 30), rng.uniform(14, 30)
        g1 = np.sin(2 * np.pi * f1 * (X * np.cos(a1) + Y * np.sin(a1)))
        g2 = np.sin(2 * np.pi * f2 * (X * np.cos(a2) + Y * np.sin(a2)))
        return _smooth(g1 * g2, 0.3)
    if style == "cubes":
        s = rng.uniform(5, 11)
        warp = 0.015 * _field(X, Y, rng, 2)
        u, v, w = (Y + warp) * s, ((X) * 0.866 - Y * 0.5) * s, (-(X) * 0.866 - Y * 0.5) * s
        shade = (np.floor(u) + np.floor(v) + np.floor(w)) % 3
        return np.choose(shade.astype(int), [0.08, 0.5, 0.92]).astype(np.float32)
    if style == "halftone":
        s = rng.uniform(22, 40)
        field = (_field(X, Y, rng, 3) + 2.0) / 4.0
        fx, fy = (X * s) % 1.0 - 0.5, (Y * s) % 1.0 - 0.5
        radius = np.clip(field, 0.05, 0.95) * 0.62
        return (np.sqrt(fx * fx + fy * fy) < radius).astype(np.float32)
    # lines
    f = rng.uniform(22, 48)
    warp = rng.uniform(0.04, 0.12) * _field(X, Y, rng, 3)
    return _smooth(np.sin(2 * np.pi * f * (Y + warp)), 0.45)


def render(slug: str, size=HERO_SIZE, inspiration: dict | None = None, salt: int = 0, motif: str | None = DEFAULT) -> Image.Image:
    insp = {**NEUTRAL_INSPIRATION, **(inspiration or {})}
    rng = np.random.RandomState(_digest(slug, salt))
    w, h = size
    X, Y = np.meshgrid(np.linspace(0, w / h, w, dtype=np.float32), np.linspace(0, 1, h, dtype=np.float32))
    v = _pattern(style_for(slug), X, Y, rng).astype(np.float32)
    if motif is DEFAULT:
        motif = portfolio_motifs.motif_for(slug)
    if motif:
        # the subject: a diagram of what the project is, over a quiet version of the abstract texture
        v = np.maximum(v * 0.2, portfolio_motifs.draw(motif, size, rng))
    v = np.clip((v - 0.5) * (0.6 + 0.8 * insp["contrast"]) + 0.5, 0, 1)
    v = v ** (0.5 + 2.0 * (1.0 - insp["luminance"]))                    # darker/brighter inspiration -> darker/brighter art
    v = np.clip(v + rng.normal(0, 0.018, v.shape).astype(np.float32), 0, 1)   # film grain
    dark, mid, light = _palette(slug, insp)
    t = v[..., None]
    rgb = np.where(t < 0.5, dark + (mid - dark) * (t * 2), mid + (light - mid) * ((t - 0.5) * 2))   # gradient map
    return Image.fromarray(np.clip(rgb * 255.0, 0, 255).astype(np.uint8), "RGB")


def _palette(slug: str, insp: dict):
    """(dark, mid, light) RGB in 0..1. Dark tones take the inspiring image's dominant hue, light tones its
    second hue. An image with no colour of its own (grey/black-and-white) gets a hue derived from the slug,
    so the result is still deterministic and projects do not all look alike."""
    hues = insp.get("hues") or []
    sat = max(0.55, min(0.95, insp.get("saturation", 0.0) * 1.2))
    if not hues or insp.get("saturation", 0.0) < 0.12:
        base = (_digest(slug, 7) % 360)
        hues, sat = [float(base), float((base + 45) % 360)], 0.6
    h1, h2 = hues[0] / 360.0, hues[1] / 360.0
    rgb = lambda h, s, val: np.array(colorsys.hsv_to_rgb(h, s, val), dtype=np.float32)
    return rgb(h1, min(1.0, sat * 0.9), 0.07), rgb(h1, sat, 0.5), rgb(h2, sat * 0.55, 0.97)


def thumbnail(img: Image.Image, width: int = 600) -> Image.Image:
    return img.resize((width, max(1, round(img.height * width / img.width))), Image.LANCZOS)


# ── registry: stable assignment + enforced uniqueness ───────────────────────

def _load(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def assign(slugs, registry_path: Path = REGISTRY_PATH, size=HERO_SIZE, max_salt: int = 8, inspirations: dict | None = None) -> dict:
    """Give every slug an image identity (salt + hash). Existing assignments are never changed;
    a new slug that lands too close to any assigned one is re-rolled with salt 1, 2, ... .
    If the cap is hit the last attempt is kept and flagged with a warning, never silently."""
    registry = _load(registry_path)
    for slug in slugs:
        if slug in registry:
            continue
        taken = [int(v["hash"], 16) for v in registry.values()]
        insp = (inspirations or {}).get(slug)
        for salt in range(max_salt + 1):
            h = fingerprint(render(slug, size, insp, salt))
            if all(hamming(h, t) >= MIN_DISTANCE for t in taken):
                registry[slug] = {"salt": salt, "hash": f"{h:032x}", "style": look_for(slug)}
                break
        else:
            registry[slug] = {"salt": max_salt, "hash": f"{h:032x}", "style": look_for(slug),
                              "warning": f"could not reach distance {MIN_DISTANCE} within {max_salt} re-rolls"}
    Path(registry_path).parent.mkdir(parents=True, exist_ok=True)
    Path(registry_path).write_text(json.dumps(registry, indent=2, sort_keys=True))
    return {s: registry[s] for s in slugs}


# ── variants: keep what was generated, choose what is used ──────────────────
# A variant is fully described by (motif, salt) for a slug, so it is reproducible and cheap to keep: the PNGs in
# images/<slug>/ are a cache of what was tried, and the registry says which one is IN USE.

def _label(motif: str | None) -> str:
    return motif or "pattern"


def variant_file(slug: str, motif: str | None, salt: int, images_dir: Path = IMAGES_DIR) -> Path:
    return Path(images_dir) / slug / f"{_label(motif)}-{int(salt)}.png"


def motif_choices() -> list[str]:
    return list(portfolio_motifs.MOTIF_NAMES) + ["pattern"]


def _motif_arg(value: str | None):
    """CLI/API value -> render() motif: None/'default' = the project's default, 'pattern' = no motif."""
    if value in (None, "", "default"):
        return DEFAULT
    if value == "pattern":
        return None
    if value not in portfolio_motifs.MOTIF_NAMES:
        raise ValueError(f"unknown motif: {value!r}")
    return value


def make_variant(slug: str, motif=DEFAULT, salt: int = 0, inspiration: dict | None = None, images_dir: Path = IMAGES_DIR, size=HERO_SIZE) -> dict:
    motif = portfolio_motifs.motif_for(slug) if motif is DEFAULT else motif
    img = render(slug, size, inspiration, salt, motif)
    f = variant_file(slug, motif, salt, images_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    img.save(f)
    return {"slug": slug, "motif": _label(motif), "salt": int(salt), "file": str(f), "hash": f"{fingerprint(img):032x}"}


def next_variant_salt(slug: str, motif, images_dir: Path = IMAGES_DIR) -> int:
    """The lowest salt for this motif that has not been generated yet."""
    motif = portfolio_motifs.motif_for(slug) if motif is DEFAULT else motif
    n = 0
    while variant_file(slug, motif, n, images_dir).exists():
        n += 1
    return n


def list_variants(slug: str, registry_path: Path = REGISTRY_PATH, images_dir: Path = IMAGES_DIR) -> dict:
    chosen = dict(_load(registry_path).get(slug, {}))
    look = chosen.get("look") or chosen.get("style")
    chosen["look"] = look if look in portfolio_motifs.MOTIF_NAMES else ("pattern" if look else None)
    out = []
    d = Path(images_dir) / slug
    for f in sorted(d.glob("*.png")) if d.is_dir() else []:
        m = re.match(r"^(.+)-(\d+)\.png$", f.name)
        if m:
            out.append({"motif": m.group(1), "salt": int(m.group(2)), "file": f.name,
                        "chosen": chosen.get("look") == m.group(1) and chosen.get("salt") == int(m.group(2))})
    return {"slug": slug, "variants": out, "chosen": {"motif": chosen.get("look"), "salt": chosen.get("salt")} if chosen else None,
            "default_motif": _label(portfolio_motifs.motif_for(slug))}


def choose_variant(slug: str, motif, salt: int, inspiration: dict | None = None, registry_path: Path = REGISTRY_PATH,
                   images_dir: Path = IMAGES_DIR, size=HERO_SIZE) -> dict:
    """Make (motif, salt) the image IN USE for the slug: records it in the registry and writes images/<slug>.png.
    The choice is the person's, so it overrides the uniqueness re-roll; a near-twin is reported, not refused."""
    motif = portfolio_motifs.motif_for(slug) if motif is DEFAULT else motif
    f = variant_file(slug, motif, salt, images_dir)
    if not f.exists():
        make_variant(slug, motif, salt, inspiration, images_dir, size)
    img = Image.open(f).convert("RGB")
    registry = _load(registry_path)
    h = fingerprint(img)
    others = {k: int(v["hash"], 16) for k, v in registry.items() if k != slug}
    nearest = min(((hamming(h, t), k) for k, t in others.items()), default=(None, None))
    registry[slug] = {"salt": int(salt), "hash": f"{h:032x}", "style": _label(motif), "look": _label(motif), "chosen": True}
    Path(registry_path).parent.mkdir(parents=True, exist_ok=True)
    Path(registry_path).write_text(json.dumps(registry, indent=2, sort_keys=True))
    Path(images_dir).mkdir(parents=True, exist_ok=True)
    img.save(Path(images_dir) / f"{slug}.png")
    out = {"slug": slug, "motif": _label(motif), "salt": int(salt)}
    if nearest[0] is not None and nearest[0] < MIN_DISTANCE:
        out["warning"] = f"looks very similar to {nearest[1]} (distance {nearest[0]}, wanted {MIN_DISTANCE}+)"
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--out", default=None)
    ap.add_argument("--inspire", nargs="*", default=[])
    ap.add_argument("--list", action="store_true", help="JSON: every generated variant of the slug and which is in use")
    ap.add_argument("--motifs", action="store_true", help="JSON: the motif names that can be chosen")
    ap.add_argument("--new", action="store_true", help="generate another variant (next unused salt for --motif)")
    ap.add_argument("--choose", action="store_true", help="use the variant given by --motif and --salt")
    ap.add_argument("--motif", default=None)
    ap.add_argument("--salt", type=int, default=0)
    args = ap.parse_args()
    if args.motifs:
        print(json.dumps(motif_choices()))
        return
    if not args.slug:
        ap.error("slug is required")
    insp = inspiration_from(args.inspire)
    if args.list:
        print(json.dumps(list_variants(args.slug)))
    elif args.new:
        motif = _motif_arg(args.motif)
        print(json.dumps(make_variant(args.slug, motif, next_variant_salt(args.slug, motif), insp)))
    elif args.choose:
        print(json.dumps(choose_variant(args.slug, _motif_arg(args.motif), args.salt, insp)))
    else:
        registry = _load(REGISTRY_PATH)
        if args.slug in registry and registry[args.slug].get("chosen"):
            e = registry[args.slug]   # a choice was made: reproduce exactly that
            motif = None if e["look"] == "pattern" else e["look"]
            salt = e["salt"]
        else:
            salt = assign([args.slug], inspirations={args.slug: insp})[args.slug]["salt"]
            motif = DEFAULT
        img = render(args.slug, HERO_SIZE, insp, salt, motif)
        kept = variant_file(args.slug, portfolio_motifs.motif_for(args.slug) if motif is DEFAULT else motif, salt)
        kept.parent.mkdir(parents=True, exist_ok=True)
        img.save(kept)                      # the image in use is always among the variants too
        out = Path(args.out or IMAGES_DIR / f"{args.slug}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        print(f"{args.slug}: look={look_for(args.slug)} salt={salt} inspiration={insp} -> {out}")


if __name__ == "__main__":
    main()
