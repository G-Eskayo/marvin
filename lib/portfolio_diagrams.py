#!/usr/bin/env python3
"""The house diagram kit for portfolio pages (ADR 0051).

The theme and three starter diagrams live in the portfolio repo's `templates/diagrams/` (setup: from nothing to ready;
run: one run start to finish; marvin: how MARVIN builds and keeps a project running). A page's diagram sources live in
`docs/diagrams/<slug>/`, and render into `deploy/longform/figures/<slug>/`, where the long-form page links them.

  portfolio_diagrams.py new <slug> [setup run marvin]   copy starters (never overwrites an edited source)
  portfolio_diagrams.py render <slug>                    render every .mmd for that page to SVG

Rendering uses Mermaid's CLI through npx with the Chrome already installed (no Puppeteer browser download).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
STARTERS = ("setup", "run", "marvin")
CHROME_CANDIDATES = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/Applications/Comet.app/Contents/MacOS/Comet"),
]
NPX = shutil.which("npx") or "/opt/homebrew/bin/npx"


class DiagramError(RuntimeError):
    pass


def _kit(project: Path) -> Path:
    return Path(project) / "templates" / "diagrams"


def new(project: Path, slug: str, kinds: list[str] | None = None) -> list[Path]:
    """Copy the chosen starters into docs/diagrams/<slug>/. A source that already exists is left alone."""
    target = Path(project) / "docs" / "diagrams" / slug
    target.mkdir(parents=True, exist_ok=True)
    made = []
    for kind in kinds or list(STARTERS):
        dest = target / f"{kind}.mmd"
        if not dest.exists():
            shutil.copyfile(_kit(project) / f"{kind}.mmd", dest)
        made.append(dest)
    return made


def find_chrome(candidates: list[Path] | None = None) -> Path | None:
    return next((Path(c) for c in (candidates or CHROME_CANDIDATES) if Path(c).exists()), None)


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300, **kw)


def render(project: Path, slug: str, runner=_run, chrome: Path | None = None) -> list[Path]:
    """Render every docs/diagrams/<slug>/*.mmd to deploy/longform/figures/<slug>/<name>.svg with the house theme."""
    project = Path(project)
    sources = sorted((project / "docs" / "diagrams" / slug).glob("*.mmd"))
    if not sources:
        raise DiagramError(f"no diagram sources in docs/diagrams/{slug}/ (start with: new {slug})")
    chrome = chrome or find_chrome()
    if chrome is None:
        raise DiagramError("no Chrome or Chromium found to render with")
    out_dir = project / "deploy" / "longform" / "figures" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        browser = Path(tmp) / "puppeteer.json"
        browser.write_text(json.dumps({"executablePath": str(chrome), "args": ["--no-sandbox"]}))
        out = []
        for src in sources:
            svg = out_dir / f"{src.stem}.svg"
            cmd = [NPX, "-y", "@mermaid-js/mermaid-cli@11", "-i", str(src), "-o", str(svg),
                   "-c", str(_kit(project) / "theme.json"), "-p", str(browser), "-b", "white"]
            r = runner(cmd, env={**__import__("os").environ, "PUPPETEER_SKIP_DOWNLOAD": "1"})
            if r.returncode != 0 or not svg.exists():
                raise DiagramError(f"{src.name} did not render: {(r.stderr or r.stdout).strip()[-400:]}")
            out.append(svg)
    return out


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in ("new", "render"):
        print(__doc__)
        sys.exit(2)
    slug = sys.argv[2]
    try:
        done = new(PROJECT, slug, sys.argv[3:] or None) if sys.argv[1] == "new" else render(PROJECT, slug)
    except DiagramError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    for p in done:
        print(p)


if __name__ == "__main__":
    main()
