#!/usr/bin/env python3
"""Colour contrast against MARVIN's accessibility rule (marvin#1062; Gil, 2026-11-03).

The rule: text meets WCAG 2.x AA (4.5:1, large text 3:1), UI marks such as state symbols 3:1, and MARVIN Term, a thin
pixel font that reads lower than the formula says, AAA (7:1). Colour is never the only signal (checked elsewhere:
shapes and words carry state).

A palette is a JSON file in config/palette/ listing colour pairs and the level each must meet:

    {"name": "...", "levels": {"text": 4.5, "large": 3.0, "ui": 3.0, "pixel": 7.0},
     "pairs": [{"what": "main text", "fg": "#f0b32a", "bg": "#05040A", "level": "pixel"},
               {"what": "focused glass over a white window", "fg": "#f0b32a", "bg": "#05040A",
                "opacity": 0.6, "backdrop": "#ffffff", "level": "text",
                "exception": "why this one may fail, and who decided"}]}

A pair with `opacity` is see-through: its background is composited over `backdrop` first. An exception needs a
written reason; one on a pair that passes is flagged as stale. A malformed pair fails the check, never skipped.

    contrast.py check config/palette/*.json     prints every pair; exits 1 on any failure
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
FUNC = re.compile(r"^rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*(?:,\s*([0-9.]+)\s*)?\)$")


def parse(color) -> tuple[float, float, float, float]:
    """(r, g, b, alpha) from #rgb, #rrggbb, rgb(...) or rgba(...)."""
    if not isinstance(color, str):
        raise ValueError(f"not a colour: {color!r}")
    c = color.strip()
    m = HEX.match(c)
    if m:
        h = m.group(1)
        h = "".join(ch * 2 for ch in h) if len(h) == 3 else h
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    m = FUNC.match(c)
    if m:
        r, g, b = (float(x) for x in m.groups()[:3])
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        if all(0 <= v <= 255 for v in (r, g, b)) and 0 <= a <= 1:
            return r, g, b, a
    raise ValueError(f"not a colour: {color!r}")


def _lin(v: float) -> float:
    v /= 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(color) -> float:
    r, g, b = (parse(color) if isinstance(color, str) else color)[:3]
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg, bg) -> float:
    """WCAG contrast ratio, 1 to 21; order doesn't matter."""
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def over(bg, opacity: float, backdrop) -> tuple[float, float, float]:
    """The colour a see-through background really shows: `bg` at `opacity` over `backdrop`."""
    if not isinstance(opacity, (int, float)) or isinstance(opacity, bool) or not 0 <= opacity <= 1:
        raise ValueError(f"opacity must be between 0 and 1, not {opacity!r}")
    top, under = parse(bg)[:3], parse(backdrop)[:3]
    return tuple(opacity * t + (1 - opacity) * u for t, u in zip(top, under))


def check(spec: dict) -> dict:
    """{"ok", "results": [...], "failures": [...], "exceptions": [...]} for one palette."""
    levels = spec.get("levels") or {}
    results, failures, exceptions, seen = [], [], [], {}
    for i, p in enumerate(spec.get("pairs") or []):
        what = p.get("what") if isinstance(p, dict) else None
        label = what or f"pair {i + 1}"
        try:
            if not isinstance(p, dict) or not what:
                raise ValueError("every pair needs a 'what'")
            if p.get("level") not in levels:
                raise ValueError(f"unknown level {p.get('level')!r}")
            need = float(levels[p["level"]])
            bg = over(p["bg"], p["opacity"], p.get("backdrop", "#ffffff")) if "opacity" in p else p["bg"]
            r = ratio(p["fg"], bg)
        except (KeyError, ValueError, TypeError) as exc:
            failures.append(f"{label}: can't be checked ({exc})")
            continue
        key = (str(p["fg"]).lower(), str(p["bg"]).lower(), p.get("opacity"), str(p.get("backdrop", "")).lower())
        if key in seen and seen[key] != p["level"]:
            failures.append(f"{label}: the same colours are listed twice with different levels")
        seen.setdefault(key, p["level"])
        ok = r >= need
        reason = str(p.get("exception") or "").strip() if "exception" in p else None
        results.append({"what": what, "ratio": round(r, 2), "need": need, "ok": ok, "exception": reason})
        if reason is not None and not reason:
            failures.append(f"{label}: an exception needs a written reason")
        elif reason and ok:
            failures.append(f"{label}: passes ({r:.1f}:1), so its exception is no longer needed")
        elif reason:
            exceptions.append(f"{label}: {r:.1f}:1 under {need:g}:1, accepted: {reason}")
        elif not ok:
            failures.append(f"{label}: {r:.1f}:1, needs {need:g}:1 ({p['level']})")
    return {"ok": not failures, "results": results, "failures": failures, "exceptions": exceptions}


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "check" or len(argv) < 2:
        print(__doc__)
        return 2
    bad = False
    for f in argv[1:]:
        try:
            spec = json.loads(Path(f).read_text())
        except (OSError, ValueError) as exc:
            print(f"{f}: can't read it ({exc})")
            bad = True
            continue
        r = check(spec)
        print(f"{spec.get('name') or f}: {'ok' if r['ok'] else 'FAILS'}")
        for x in r["results"]:
            mark = "ok " if x["ok"] else ("exc" if x["exception"] else "BAD")
            print(f"  {mark} {x['ratio']:5.1f}:1 (needs {x['need']:g})  {x['what']}")
        for line in r["failures"]:
            print(f"  FAIL {line}")
        for line in r["exceptions"]:
            print(f"  accepted {line}")
        bad = bad or not r["ok"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
