#!/usr/bin/env python3
"""Install MARVIN's WezTerm look on this Mac (marvin#1069, PRD #1058).

The look itself is config/wezterm/marvin.lua in ~/.agents (synced). This adds the one guarded loader to the Mac's own
~/.config/wezterm/wezterm.lua, just before its `return config`, keeping everything else the person set there:

    package.path = package.path .. ';<~/.agents>/config/wezterm/?.lua'
    pcall(function() require('marvin').apply(config) end)

Idempotent. Run by `marvin_hooks.py install`, the per-Mac install, so no Mac is silently left without it.
    wezterm_look.py install     prints "installed" / "already installed" / why it couldn't
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
LUA_DIR = HERE.parents[1] / "config" / "wezterm"
WEZTERM_CONFIG = Path.home() / ".config" / "wezterm" / "wezterm.lua"
MARKER = "require('marvin').apply(config)"
FRESH = "local wezterm = require 'wezterm'\nlocal config = wezterm.config_builder()\nreturn config\n"


def loader(lua_dir: Path = LUA_DIR) -> str:
    return ("-- MARVIN's look (marvin#1069): font, accessible palette, glass. Lives in ~/.agents so every Mac matches;\n"
            "-- if it ever breaks, pcall leaves WezTerm on the settings above.\n"
            f"package.path = package.path .. ';{lua_dir}/?.lua'\n"
            f"pcall(function() {MARKER} end)\n")


def install(config: Path = WEZTERM_CONFIG, lua_dir: Path = LUA_DIR) -> str:
    text = config.read_text() if config.exists() else FRESH
    if MARKER in text:
        return "already installed"
    idx = text.rfind("return config")
    if idx < 0:
        raise ValueError(f"{config} has no 'return config' to load MARVIN's look before; add the loader by hand:\n"
                         + loader(lua_dir))
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        backup = config.with_name(config.name + ".pre-marvin-look")
        if not backup.exists():
            backup.write_text(text)
    config.write_text(text[:idx] + loader(lua_dir) + "\n" + text[idx:])
    return "installed"


def main(argv: list[str]) -> int:
    if argv[:1] == ["install"]:
        try:
            print(install())
        except (OSError, ValueError) as exc:
            print(f"not installed: {exc}")
            return 1
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
