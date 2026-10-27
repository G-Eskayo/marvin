#!/usr/bin/env python3
"""One-time migration: apply legacy grant to new feature-gated add-ons.

When the feature gate system launches (marvin#647), all of Gil's add-ons are already in use
(Portfolio has been running for months, Seal ingest runs via launchd). This script converts
the empty `{"features": {}}` into an all-enabled state, so nothing silently turns off.

Only run once, after instance.json exists. A second run is a no-op; respects explicit prior choices
(if portfolio was already set False, leaves it False).

    ~/.agents/venv/bin/python lib/addon_migrate.py

Optional --instance-dir flag overrides ~/.agents/instance (tests only).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import instance as inst

KNOWN_ADDONS = ("portfolio", "resume_tailor", "seal_ingest")


def apply_legacy_grant(config: dict) -> dict:
    """Grant all known add-ons if not already present. Idempotent.

    Args:
        config: instance.json data (dict, possibly empty or malformed)

    Returns:
        Updated config with all known add-ons granted (only missing keys added).
    """
    if not isinstance(config, dict):
        config = {}

    features = config.get("features")
    if not isinstance(features, dict):
        features = {}
        config["features"] = features

    # Grant each add-on only if not already present (respects prior explicit choices)
    for addon in KNOWN_ADDONS:
        if addon not in features:
            features[addon] = True

    return config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--instance-dir", type=Path, default=None,
                    help="instance.json location (default: ~/.agents/instance)")
    a = ap.parse_args(argv)

    instance_dir = Path(a.instance_dir) if a.instance_dir else inst.instance_dir()
    instance_json = instance_dir / "instance.json"

    if not instance_json.exists():
        print(f"addon-migrate: {instance_json} not found; nothing to migrate", file=sys.stderr)
        return 1

    try:
        config = json.loads(instance_json.read_text())
    except (ValueError, UnicodeDecodeError) as e:
        print(f"addon-migrate: {instance_json} is not valid JSON: {e}", file=sys.stderr)
        return 1

    original = json.dumps(config, sort_keys=True)
    config = apply_legacy_grant(config)
    updated = json.dumps(config, sort_keys=True)

    if original == updated:
        print(f"addon-migrate: {instance_json} already migrated (no change needed)")
        return 0

    # Write back only if changed
    instance_json.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print(f"addon-migrate: {instance_json} migrated ({len(KNOWN_ADDONS)} add-ons granted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
