#!/usr/bin/env python3
"""
render_map_images.py — the MARVIN page hero and its project card, cut from ONE picture of the website map, so they
always match (Gil, 2026-10-08) and show only what the public snapshot shows (anonymised machines, locked projects).

One frame of snapshot/index.html?embed=1 (2x pixels), on the page's dark background, cropped to where the nodes are:
  card  the nodes' box widened to 8:5, scaled to 800x500        -> deploy/uploads/generated/marvin-map-600w.jpg
  hero  a 2200:600 band of that same box, centred on MARVIN     -> deploy/longform/figures/marvin/marvin-map-hero.jpg

Writes into a portfolio checkout (default: the dev one); production gets them when Gil promotes the site, they are
outside the map folder ADR 0057 lets publish itself. Needs Playwright (the mac-mini has it).
    python render_map_images.py [--portfolio DIR] [--snapshot DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).parent
FRAME = (2200, 1375)
CARD = (800, 500)
HERO = (2200, 600)
CARD_PATH = "deploy/uploads/generated/marvin-map-600w.jpg"
HERO_PATH = "deploy/longform/figures/marvin/marvin-map-hero.jpg"
PAGE_BG = "radial-gradient(ellipse 90% 70% at 50% 45%, #131a24 0%, #0d1117 62%, #05070a 100%)"


SCALE = 2  # device pixels per CSS pixel: the hero is 2200 wide, so the box needs the pixels


def card_box(nodes: list[dict], frame=FRAME, pad: float = 0.06, ratio: float = CARD[0] / CARD[1]):
    """The nodes' bounding box (CSS px) plus padding, widened to `ratio`, kept inside the frame."""
    xs = [n["sx"] for n in nodes]; ys = [n["sy"] for n in nodes]
    l, r, t, b = min(xs), max(xs), min(ys), max(ys)
    w, h = (r - l) * (1 + 2 * pad), (b - t) * (1 + 2 * pad)
    if w / h < ratio:
        w = h * ratio
    else:
        h = w / ratio
    w, h = min(w, frame[0]), min(h, frame[1])
    cx, cy = (l + r) / 2, (t + b) / 2
    left = min(max(cx - w / 2, 0), frame[0] - w)
    top = min(max(cy - h / 2, 0), frame[1] - h)
    return (left, top, left + w, top + h)


def hero_box(card: tuple, centre_y: float, ratio: float = HERO[0] / HERO[1]):
    """A full-width band of the card box at the hero's ratio, centred on `centre_y` (MARVIN), kept inside the box."""
    l, t, r, b = card
    h = (r - l) / ratio
    top = min(max(centre_y - h / 2, t), b - h)
    return (l, top, r, top + h)


async def _frame(snapshot: Path, out: Path) -> list[dict]:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": FRAME[0], "height": FRAME[1]}, device_scale_factor=SCALE)
        await page.goto((snapshot / "index.html").resolve().as_uri() + "?embed=1", wait_until="load")
        await page.add_style_tag(content=f"html.embed-mode, html.embed-mode body {{ background: {PAGE_BG}; }}")
        await page.wait_for_timeout(4000)  # intro settles, steady fit reached
        await page.screenshot(path=str(out))
        nodes = await page.evaluate("window.__map.nodes()")
        await browser.close()
        return nodes


def render(snapshot: Path, portfolio: Path, tmp: Path) -> list[Path]:
    from PIL import Image
    frame = tmp / "map-frame.png"
    nodes = asyncio.run(_frame(snapshot, frame))
    img = Image.open(frame).convert("RGB")
    cbox = card_box(nodes)
    marvin = next((n for n in nodes if n["id"] == "MARVIN"), None)
    hbox = hero_box(cbox, marvin["sy"] if marvin else (cbox[1] + cbox[3]) / 2)
    px = lambda box: tuple(round(v * SCALE) for v in box)  # noqa: E731
    card, hero = portfolio / CARD_PATH, portfolio / HERO_PATH
    card.parent.mkdir(parents=True, exist_ok=True)
    hero.parent.mkdir(parents=True, exist_ok=True)
    img.crop(px(cbox)).resize(CARD, Image.LANCZOS).save(card, quality=88)
    img.crop(px(hbox)).resize(HERO, Image.LANCZOS).save(hero, quality=88)
    return [card, hero]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", type=Path, default=HERE / "snapshot")
    ap.add_argument("--portfolio", type=Path, default=Path.home() / "Documents" / "Projects" / "portfolio-website-updater")
    ap.add_argument("--tmp", type=Path, default=Path("/tmp"))
    args = ap.parse_args()
    if not (args.snapshot / "index.html").is_file():
        sys.exit(f"no snapshot at {args.snapshot}: run export_snapshot.py first")
    for p in render(args.snapshot, args.portfolio, args.tmp):
        print(p)


if __name__ == "__main__":
    main()
