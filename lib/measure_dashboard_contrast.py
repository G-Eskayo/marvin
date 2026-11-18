#!/usr/bin/env python3
"""Measure and report dashboard contrast ratios."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
import contrast as cx

REPO = Path(__file__).resolve().parents[1]
palette_file = REPO / "config" / "palette" / "dashboard.json"

with open(palette_file) as f:
    palette = json.load(f)

print(f"\n{palette['name']}")
print("=" * 70)
print(f"{'Pair':<50} {'Ratio':>8}")
print("-" * 70)

for p in palette.get("pairs", []):
    what = p.get("what", "")
    if "opacity" in p:
        bg = cx.over(p["bg"], p["opacity"], p.get("backdrop", "#ffffff"))
    else:
        bg = p["bg"]

    ratio = cx.ratio(p["fg"], bg)
    level = p.get("level", "?")
    need = palette.get("levels", {}).get(level, "?")
    status = "✓" if ratio >= float(need) else "✗"

    print(f"{what:<50} {ratio:>6.1f}:1 {status}")
