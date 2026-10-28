#!/usr/bin/env python3
"""Check if Resume Tailor feature is enabled. Exits 0 if on, 1 if off/missing/corrupt.

Never writes anything. Used as a Phase 0 gate in SKILL.md before any real work happens.

    ~/.agents/venv/bin/python skills/resume-tailor/scripts/check_enabled.py
"""
from __future__ import annotations

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parents[3] / "lib"
sys.path.insert(0, str(LIB_DIR))

import instance  # noqa: E402


def main() -> int:
    if instance.feature_enabled("resume_tailor"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
