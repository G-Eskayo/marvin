#!/usr/bin/env python3
"""
render_map_images.py — the MARVIN page hero and its project card, cut from ONE picture of the website map, so they
always match (Gil, 2026-10-08) and show only what the public snapshot shows (anonymised machines, locked projects).

One frame of snapshot/index.html?embed=1 at 2200x1375 (the card's 8:5), on the page's dark background:
  card  the whole frame, scaled to 800x500        -> deploy/uploads/generated/marvin-map-600w.jpg
  hero  a 2200x600 band through the frame's middle -> deploy/longform/figures/marvin/marvin-map-hero.jpg

Writes into a portfolio checkout (default: the dev one); production gets them when Gil promotes the site, they are
outside the map folder ADR 0056 lets publish itself. Needs Playwright (the mac-mini has it).
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


def hero_box(frame: tuple[int, int] = FRAME, hero: tuple[int, int] = HERO) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the hero band: full width, centred vertically on the map's middle."""
    w, h = frame
    top = (h - hero[1]) // 2
    return (0, top, hero[0], top + hero[1])


async def _frame(snapshot: Path, out: Path) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": FRAME[0], "height": FRAME[1]})
        await page.goto((snapshot / "index.html").resolve().as_uri() + "?embed=1", wait_until="load")
        await page.add_style_tag(content=f"html.embed-mode, html.embed-mode body {{ background: {PAGE_BG}; }}")
        await page.wait_for_timeout(4000)  # intro settles, steady fit reached
        await page.screenshot(path=str(out))
        await browser.close()


def render(snapshot: Path, portfolio: Path, tmp: Path) -> list[Path]:
    from PIL import Image
    frame = tmp / "map-frame.png"
    asyncio.run(_frame(snapshot, frame))
    img = Image.open(frame).convert("RGB")
    card, hero = portfolio / CARD_PATH, portfolio / HERO_PATH
    card.parent.mkdir(parents=True, exist_ok=True)
    hero.parent.mkdir(parents=True, exist_ok=True)
    img.resize(CARD, Image.LANCZOS).save(card, quality=88)
    img.crop(hero_box()).save(hero, quality=88)
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
