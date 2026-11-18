"""Dashboard celestial-navigation tokens: every --dim use meets WCAG AA (marvin#1148)."""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contrast as cx  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _read_css(path):
  """Read a CSS file and return its text."""
  return (REPO / path).read_text()


def test_every_dim_text_use_passes_aa():
  """Every use of --dim in dashboard CSS sits on a background that meets WCAG AA."""
  boot_css = _read_css("dashboard/src/components/boot.css")
  show_css = _read_css("dashboard/src/components/show_window.css")

  # Extract the actual colour values from the CSS
  boot_match = re.search(r'--dim:\s*(#[0-9a-fA-F]+)', boot_css)
  show_match = re.search(r'--dim:\s*(#[0-9a-fA-F]+)', show_css)

  assert boot_match, "boot.css must define --dim"
  assert show_match, "show_window.css must define --dim"

  dim_color = boot_match.group(1)
  assert dim_color == show_match.group(1), "both CSS files must use the same --dim value"

  # Extract background colours
  boot_bg_match = re.search(r'--dash:\s*(#[0-9a-fA-F]+)', boot_css)
  show_bg_match = re.search(r'--bg:\s*(#[0-9a-fA-F]+)', show_css)

  assert boot_bg_match, "boot.css must define --dash"
  assert show_bg_match, "show_window.css must define --bg"

  boot_bg = boot_bg_match.group(1)
  show_bg = show_bg_match.group(1)

  # Test the colour pairs
  boot_ratio = cx.ratio(dim_color, boot_bg)
  show_ratio = cx.ratio(dim_color, show_bg)

  assert boot_ratio >= 4.5, f"--dim ({dim_color}) on boot background ({boot_bg}) is {boot_ratio:.1f}:1, needs 4.5:1 (WCAG AA)"
  assert show_ratio >= 4.5, f"--dim ({dim_color}) on show background ({show_bg}) is {show_ratio:.1f}:1, needs 4.5:1 (WCAG AA)"


def test_no_hover_or_disabled_rule_uses_dim_below_aa():
  """No :hover, :focus, :disabled, or :focus-visible state uses --dim without measuring it."""
  boot_css = _read_css("dashboard/src/components/boot.css")
  show_css = _read_css("dashboard/src/components/show_window.css")

  for path, css in [("boot.css", boot_css), ("show_window.css", show_css)]:
    # Find all CSS rules: selector + block
    rules = re.finditer(r'([^{]+)\{([^}]+)\}', css)
    for rule_match in rules:
      selector = rule_match.group(1)
      block = rule_match.group(2)

      # Check if selector contains a state pseudo-class (with optional arguments like :not(...))
      if re.search(r':[a-z-]+(?:\([^)]*\))?', selector):
        # If this rule uses --dim, it must be explicitly measured
        if 'var(--dim)' in block:
          pytest.fail(f"Dashboard {path} uses a state pseudo-class with --dim (requires explicit contrast measurement): {selector.strip()}")


def test_6b551f_is_gone_from_dashboard_src():
  """The old --dim colour is not used anywhere in dashboard/src (not even as a comment)."""
  import subprocess

  # Use ripgrep (rg) if available, fall back to grep
  try:
    result = subprocess.run(
      ['rg', '-i', '6b551f', 'dashboard/src/'],
      cwd=REPO,
      capture_output=True,
      text=True
    )
    assert result.returncode == 1, f"Found old --dim colour #6b551f in dashboard/src: {result.stdout}"
  except (FileNotFoundError, OSError):
    # rg not available, use grep
    result = subprocess.run(
      ['grep', '-ri', '6b551f', 'dashboard/src/'],
      cwd=REPO,
      capture_output=True,
      text=True
    )
    assert result.returncode == 1, f"Found old --dim colour #6b551f in dashboard/src: {result.stdout}"


def test_a_planted_bad_pair_fails_exactly_like_the_real_bug_did():
  """Regression test: a palette with the old --dim colour fails with the expected message."""
  palette = json.loads((REPO / "config" / "palette" / "dashboard.json").read_text())

  # Find a --dim pair and revert it to the old value
  bad_palette = {
    **palette,
    "pairs": [
      {**p, "fg": "#6b551f" if p.get("fg") == "#b89235" else p["fg"]}
      for p in palette.get("pairs", [])
    ]
  }

  result = cx.check(bad_palette)
  assert not result["ok"], "Expected the reverted colour to fail the contrast check"

  # Verify the failure message is clear
  failures = " ".join(result["failures"])
  assert "2.9" in failures or "2.6" in failures, "Expected failure message to show the actual ratio (~2.9 or ~2.6)"
  assert "4.5" in failures, "Expected failure message to show the required ratio (4.5)"


def test_dashboard_palette_included_in_ci_check():
  """The existing CI test discovers and validates dashboard.json."""
  palettes = sorted((REPO / "config" / "palette").glob("*.json"))
  dashboard_json = REPO / "config" / "palette" / "dashboard.json"

  assert dashboard_json in palettes, f"dashboard.json should be in {palettes}"

  # Verify it passes the same check the CI uses
  palette = json.loads(dashboard_json.read_text())
  result = cx.check(palette)
  assert result["ok"], f"dashboard.json failed contrast check: {'; '.join(result['failures'])}"
