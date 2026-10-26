#!/usr/bin/env python3
"""Check if Resume Tailor add-on is enabled. Exit 0 if on, 1 if off or instance missing.

    ~/.agents/venv/bin/python ~/.agents/skills/resume-tailor/scripts/check_enabled.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add lib to path so we can import instance
lib_path = Path(__file__).resolve().parents[3] / "lib"
sys.path.insert(0, str(lib_path))

import instance as inst  # noqa: E402


def main() -> int:
    if inst.feature_enabled("resume_tailor"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
