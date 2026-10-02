#!/usr/bin/env python3
"""Inventory of what is ACTUALLY on the portfolio site (dev): every distinct button, every page.

Gil 2026-10-02: the Portfolio tab's component library must be "representative of what is actually
on the website" -- all the buttons across the site and the full page templates -- not a handful of
hand-written examples. This crawls the dev site in headless Playwright, records every button-like
element with its computed style, groups them into distinct VARIANTS (so "5 pages use this look, 13
use that one" is visible at a glance), screenshots each variant and each page, and captures each
page's raw markup (Fusion Builder shortcodes) through wp-cli. The Portfolio tab shows the result and
lets Gil promote a real variant into the canonical library.

Pure parts (signatures, grouping, classification, summary) are unit-tested; `collect` is the thin
browser layer. Read-only against the site.

CLI:  portfolio_inventory.py [--base http://localhost:8080] [--out-dir DIR]
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
MANIFEST_PATH = PROJECT / "deploy" / "other-projects" / "manifest.json"
OUT_DIR = Path.home() / ".claude" / "portfolio" / "inventory"
WPCLI_CONTAINER = "portfolio-website-updater-wpcli-1"
HUB_PAGES = ["/ai-projects/", "/cybersecurity-projects/", "/software-engineering/"]

STYLE_FIELDS = ["color", "backgroundColor", "borderTopWidth", "borderTopStyle", "borderTopColor", "borderRadius",
                "paddingTop", "paddingLeft", "fontSize", "fontWeight", "fontFamily", "textTransform", "display",
                "letterSpacing", "textDecorationLine"]


# ── pure: signatures, grouping, classification ──────────────────────────────

def button_signature(styles: dict) -> str:
    """One string capturing everything visible about how a button looks (not its text/href/page)."""
    return "|".join(str(styles.get(f, "")).strip() for f in STYLE_FIELDS)


def variant_id(kind: str, signature: str) -> str:
    return hashlib.sha256(f"{kind}:{signature}".encode()).hexdigest()[:10]


def group_buttons(records: list[dict]) -> list[dict]:
    """Collapse raw button records into distinct looks, most-used first."""
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(variant_id(r.get("kind", "button"), button_signature(r["styles"])), []).append(r)
    variants = []
    for vid, items in groups.items():
        texts, seen = [], set()
        for it in items:
            t = it.get("text", "")
            if t and t not in seen:
                seen.add(t)
                texts.append(t)
        classes = Counter(" ".join(sorted(it.get("cls", "").split())) for it in items).most_common(1)[0][0]
        variants.append({
            "id": vid, "kind": items[0].get("kind", "button"), "count": len(items),
            "pages": sorted({it["page"] for it in items}), "texts": texts[:6], "classes": classes,
            "regions": sorted({it.get("region", "content") for it in items}),
            "styles": items[0]["styles"], "example": items[0],
        })
    return sorted(variants, key=lambda v: (-v["count"], v["id"]))


def _norm(path: str) -> str:
    p = urlparse(path).path or "/"
    return p if p.endswith("/") else p + "/"


def classify_page(url: str, manifest_urls: list[str], hub_urls: list[str]) -> str:
    p = _norm(url)
    if p == "/":
        return "home"
    if p in {_norm(u) for u in manifest_urls}:
        return "project"
    if p in {_norm(u) for u in hub_urls}:
        return "hub"
    if p == "/all-projects/":
        return "all-projects"
    return "page"


def summarize(pages: list[dict], buttons: list[dict]) -> dict:
    by_type = Counter(p["type"] for p in pages)
    return {"pages": len(pages), "pages_by_type": dict(by_type),
            "button_variants": sum(1 for b in buttons if b["kind"] == "button"),
            "github_link_variants": sum(1 for b in buttons if b["kind"] == "github-link"),
            "button_instances": sum(b["count"] for b in buttons)}


# ── browser layer (thin: measures and screenshots, never judges) ────────────

_BUTTONS_JS = """(fields) => {
  const sel = 'a.btn, button, input[type=submit], input[type=button], [role=button], a[class*="button"], a[class*="btn"], .fusion-button, a[href*="github.com"]';
  const out = [];
  document.querySelectorAll(sel).forEach((el, i) => {
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || cs.display === 'none' || cs.visibility === 'hidden') return;
    el.setAttribute('data-inv', String(i));
    const href = el.getAttribute('href') || '';
    const styles = {}; fields.forEach(f => styles[f] = f === 'fontFamily' ? cs[f].split(',')[0].replace(/["']/g, '').trim() : cs[f]);
    out.push({idx: i, tag: el.tagName.toLowerCase(), text: (el.innerText || el.value || '').trim().slice(0, 60), cls: el.className.toString(), href: href,
              kind: /github\\.com/.test(href) ? 'github-link' : 'button',
              region: el.closest('footer') ? 'footer' : el.closest('header, nav') ? 'header' : 'content',
              html: el.outerHTML.slice(0, 700), styles});
  });
  return out;
}"""


_RENDERED_JS = """() => {
  const el = document.querySelector('#content .post-content') || document.querySelector('.post-content') || document.querySelector('#content') || document.querySelector('main') || document.body;
  const clone = el.cloneNode(true);
  clone.querySelectorAll('script, style, noscript').forEach(n => n.remove());
  clone.querySelectorAll('[data-inv]').forEach(n => n.removeAttribute('data-inv'));
  return clone.innerHTML.trim();
}"""


def _wpcli(args: list[str]) -> str | None:
    try:
        r = subprocess.run(["docker", "exec", WPCLI_CONTAINER, "wp", *args, "--path=/var/www/html"],
                           capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def collect(base: str = "http://localhost:8080", out_dir: Path = OUT_DIR, manifest_path: Path = MANIFEST_PATH) -> dict:
    from playwright.sync_api import sync_playwright
    from PIL import Image
    manifest_urls = [p["url"] for p in json.loads(Path(manifest_path).read_text())]
    (out_dir / "pages").mkdir(parents=True, exist_ok=True)
    (out_dir / "buttons").mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)

    listing = _wpcli(["post", "list", "--post_type=page", "--post_status=publish", "--fields=ID,post_name,post_title,post_parent", "--format=json"])
    wp_pages = json.loads(listing) if listing else []
    pages, records, seen_variants, seen_urls = [], [], set(), set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        # WordPress entries first (they carry the raw markup); "/" is only a fallback if the front page is not among them
        targets = [(None, p["post_title"], p) for p in wp_pages] + [("/", "Home", None)]
        for url, title, wp in targets:
            if wp is not None:
                page.goto(f"{base}/?page_id={wp['ID']}", wait_until="networkidle")
                url = urlparse(page.url).path       # WordPress redirects to the pretty permalink
            else:
                page.goto(base + url, wait_until="networkidle")
            slug = (url.strip("/").replace("/", "--") or "home")
            if url in seen_urls:                 # e.g. the front page is both "Home" and a WordPress page entry
                continue
            seen_urls.add(url)
            shot = out_dir / "pages" / f"{slug}.png"
            page.screenshot(path=str(shot), full_page=True)
            img = Image.open(shot); w, h = img.size
            img.resize((480, min(2400, max(1, round(h * 480 / w)))), Image.LANCZOS).save(shot)
            raw = _wpcli(["post", "get", str(wp["ID"]), "--field=post_content"]) if wp else None
            # What visitors actually get: the main content area's markup (the useful reference for legacy WP-Coder pages,
            # whose raw content is only a shortcode).
            rendered = page.evaluate(_RENDERED_JS)
            (out_dir / "rendered").mkdir(exist_ok=True)
            (out_dir / "rendered" / f"{slug}.html").write_text(rendered or "")
            if raw is not None:
                (out_dir / "raw" / f"{slug}.html").write_text(raw)
            pages.append({"slug": slug, "url": url, "title": title, "id": wp["ID"] if wp else None,
                          "type": classify_page(url, manifest_urls, HUB_PAGES) if url != "/" else "home",
                          "screenshot": f"pages/{slug}.png", "raw": f"raw/{slug}.html" if raw is not None else None,
                          "rendered": f"rendered/{slug}.html",
                          "raw_chars": len(raw) if raw else 0})
            for rec in page.evaluate(_BUTTONS_JS, STYLE_FIELDS):
                rec["page"] = url
                vid = variant_id(rec["kind"], button_signature(rec["styles"]))
                if vid not in seen_variants:
                    seen_variants.add(vid)
                    try:
                        page.locator(f'[data-inv="{rec["idx"]}"]').first.screenshot(path=str(out_dir / "buttons" / f"{vid}.png"))
                    except Exception:
                        pass
                records.append(rec)
        browser.close()

    buttons = group_buttons(records)
    for b in buttons:
        b["screenshot"] = f"buttons/{b['id']}.png" if (out_dir / "buttons" / f"{b['id']}.png").exists() else None
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "base": base, "pages": pages, "buttons": buttons,
              "summary": summarize(pages, buttons)}
    (out_dir / "inventory.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()
    r = collect(args.base, Path(args.out_dir))
    s = r["summary"]
    print(f"{s['pages']} pages {s['pages_by_type']} | {s['button_variants']} button looks, {s['github_link_variants']} github-link looks "
          f"across {s['button_instances']} instances -> {args.out_dir}")


if __name__ == "__main__":
    main()
