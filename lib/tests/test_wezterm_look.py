"""marvin#1069: MARVIN's WezTerm look, synced, guarded, installed on each Mac, accessible palette."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contrast  # noqa: E402
import wezterm_look as wl  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PALETTE = json.loads((REPO / "config" / "palette" / "wezterm.json").read_text())
GILS = """local wezterm = require 'wezterm'
local config = wezterm.config_builder()
config.color_scheme = 'Tokyo Night'
config.scrollback_lines = 10000
config.ssh_domains = { { name = 'mac-mini', remote_address = 'gils-mac-mini', multiplexing = 'WezTerm' } }
return config
"""


# ── installer ───────────────────────────────────────────────────────────────────────────────

def test_install_adds_the_guarded_loader_before_return_and_keeps_everything_else(tmp_path):
    cfg = tmp_path / "wezterm.lua"
    cfg.write_text(GILS)
    assert wl.install(cfg, tmp_path / "lua") == "installed"
    text = cfg.read_text()
    assert "pcall(function() require('marvin').apply(config) end)" in text
    assert text.index("pcall(") < text.rindex("return config")
    for kept in ("Tokyo Night", "scrollback_lines = 10000", "mac-mini"):
        assert kept in text
    assert (tmp_path / "wezterm.lua.pre-marvin-look").read_text() == GILS


def test_install_twice_changes_nothing(tmp_path):
    cfg = tmp_path / "wezterm.lua"
    cfg.write_text(GILS)
    wl.install(cfg, tmp_path)
    once = cfg.read_text()
    assert wl.install(cfg, tmp_path) == "already installed" and cfg.read_text() == once


def test_install_creates_a_config_when_there_is_none(tmp_path):
    cfg = tmp_path / "sub" / "wezterm.lua"
    assert wl.install(cfg, tmp_path) == "installed" and "require('marvin')" in cfg.read_text()


def test_a_config_without_return_config_is_refused_not_mangled(tmp_path):
    cfg = tmp_path / "wezterm.lua"
    cfg.write_text("return { font_size = 14 }\n")
    with pytest.raises(ValueError, match="by hand"):
        wl.install(cfg, tmp_path)
    assert cfg.read_text() == "return { font_size = 14 }\n"


def test_the_per_mac_install_runs_it():
    assert "wezterm_look.install()" in (REPO / "lib" / "marvin_hooks.py").read_text()


# ── palette: one source, measured ───────────────────────────────────────────────────────────

def test_every_terminal_text_colour_is_a_checked_pair():
    t = PALETTE["terminal"]
    checked = {p["fg"].lower() for p in PALETTE["pairs"] if p["bg"].lower() == t["background"].lower()
               and "opacity" not in p}
    for c in [t["foreground"], t["tab_inactive_fg"], *t["ansi"][1:], *t["brights"]]:
        assert c.lower() in checked, f"{c} is used for text but never measured"
    assert contrast.check(PALETTE)["ok"]


def test_the_glass_levels_are_the_ones_gil_chose():
    assert (PALETTE["terminal"]["glass_unfocused"], PALETTE["terminal"]["glass_focused"]) == (0.3, 0.6)


# ── the real WezTerm loads it (skipped where WezTerm isn't installed) ───────────────────────

def _wezterm():
    for c in (Path.home() / ".local/bin/wezterm", Path("/Applications/WezTerm.app/Contents/MacOS/wezterm"),
              Path("/opt/homebrew/bin/wezterm")):
        if c.exists():
            return str(c)
    found = shutil.which("wezterm")
    if not found:
        pytest.skip("WezTerm isn't installed on this machine")
    return found


def _fonts_used(tmp_path, agents: Path) -> str:
    cfg = tmp_path / "wezterm.lua"
    cfg.write_text(GILS)
    wl.install(cfg, agents / "config" / "wezterm")
    r = subprocess.run([_wezterm(), "--config-file", str(cfg), "ls-fonts", "--text", "Il1"], capture_output=True,
                       text=True, timeout=60)
    return r.stdout + r.stderr


def _copy_agents(tmp_path) -> Path:
    agents = tmp_path / "agents"
    for sub in ("config/wezterm", "config/palette", "design/fonts"):
        shutil.copytree(REPO / sub, agents / sub)
    return agents


def test_wezterm_loads_marvin_term_mono_from_the_synced_folder(tmp_path):
    out = _fonts_used(tmp_path, REPO)
    assert "MARVIN Term Mono" in out and "MarvinTermMono-Beam.ttf" in out


def test_a_broken_look_file_leaves_wezterm_working_on_its_own_settings(tmp_path):
    agents = _copy_agents(tmp_path)
    (agents / "config" / "wezterm" / "marvin.lua").write_text("this is not lua (((\n")
    out = _fonts_used(tmp_path, agents)
    assert "MARVIN Term Mono" not in out and "glyph=" in out   # WezTerm still started and rendered with its default


def test_a_missing_font_falls_back_and_still_loads(tmp_path):
    agents = _copy_agents(tmp_path)
    (agents / "design" / "fonts" / "MarvinTermMono-Beam.ttf").unlink()
    out = _fonts_used(tmp_path, agents)
    assert "glyph=" in out and "MarvinTermMono-Beam.ttf" not in out


def test_a_broken_palette_file_keeps_the_font_and_skips_the_colours(tmp_path):
    agents = _copy_agents(tmp_path)
    (agents / "config" / "palette" / "wezterm.json").write_text("{not json")
    out = _fonts_used(tmp_path, agents)
    assert "MARVIN Term Mono" in out


def test_the_palette_and_glass_really_apply_in_wezterm(tmp_path):
    cfg = tmp_path / "wezterm.lua"
    cfg.write_text(f"""local wezterm = require 'wezterm'
local config = wezterm.config_builder()
package.path = package.path .. ';{REPO}/config/wezterm/?.lua'
require('marvin').apply(config)
assert(config.colors.foreground == '{PALETTE["terminal"]["foreground"]}')
assert(config.colors.ansi[2] == '{PALETTE["terminal"]["ansi"][1]}')
assert(config.window_background_opacity == {PALETTE["terminal"]["glass_focused"]})
wezterm.log_info('LOOK OK')
return config
""")
    r = subprocess.run([_wezterm(), "--config-file", str(cfg), "ls-fonts", "--text", "I"], capture_output=True,
                       text=True, timeout=60)
    assert "LOOK OK" in r.stdout + r.stderr
