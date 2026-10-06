#!/usr/bin/env python3
"""The house diagram kit for portfolio pages (ADR 0051).

Starter diagrams live in the portfolio repo's `templates/diagrams/` (setup: from nothing to ready; run: one run start to
finish; marvin: how MARVIN builds and keeps a project running). A page's diagram sources live in `docs/diagrams/<slug>/`
and render into `deploy/longform/figures/<slug>/`, where the long-form page links them.

Rendering reuses lib/render_diagrams.py: one house theme, an intrinsic size on every SVG (so it behaves as an <img>),
well-formed XML and no external references. Labels are SVG text, so keep them plain (line breaks with <br/>, no <b>).

  portfolio_diagrams.py new <slug> [setup run marvin]   copy starters (never overwrites an edited source)
  portfolio_diagrams.py render <slug>                    render every .mmd for that page to SVG
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROJECT = Path.home() / "Documents" / "Projects" / "portfolio-website-updater"
STARTERS = ("setup", "run", "marvin")


class DiagramError(RuntimeError):
    pass


def new(project: Path, slug: str, kinds: list[str] | None = None) -> list[Path]:
    """Copy the chosen starters into docs/diagrams/<slug>/. A source that already exists is left alone."""
    target = Path(project) / "docs" / "diagrams" / slug
    target.mkdir(parents=True, exist_ok=True)
    made = []
    for kind in kinds or list(STARTERS):
        dest = target / f"{kind}.mmd"
        if not dest.exists():
            shutil.copyfile(Path(project) / "templates" / "diagrams" / f"{kind}.mmd", dest)
        made.append(dest)
    return made


def _default_renderer(diagrams: dict[str, str], out_dir: Path) -> dict[str, Path]:
    import render_diagrams
    return render_diagrams.render(diagrams, out_dir)


def render(project: Path, slug: str, renderer=_default_renderer) -> list[Path]:
    """Render every docs/diagrams/<slug>/*.mmd to deploy/longform/figures/<slug>/<name>.svg."""
    project = Path(project)
    sources = sorted((project / "docs" / "diagrams" / slug).glob("*.mmd"))
    if not sources:
        raise DiagramError(f"no diagram sources in docs/diagrams/{slug}/ (start with: new {slug})")
    out_dir = project / "deploy" / "longform" / "figures" / slug
    try:
        written = renderer({s.stem: s.read_text() for s in sources}, out_dir)
    except RuntimeError as exc:
        raise DiagramError(str(exc)) from exc
    return [Path(p) for p in written.values()]


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
