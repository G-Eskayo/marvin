#!/usr/bin/env python3
"""One-time migration: grant all known add-ons to instances that have no explicit "features" config.

Used at PR merge time to preserve the implicit "everything is on" behavior that existed before
feature gates were introduced (ADR 0074). A fresh instance with no features key gets all three
add-ons turned on; an instance that already made a choice about any add-on keeps that choice.

    ~/.agents/venv/bin/python lib/addon_migrate.py
    ~/.agents/venv/bin/python lib/addon_migrate.py --instance-dir /tmp/test-instance
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KNOWN_ADDONS = ("portfolio", "resume_tailor", "seal_ingest")


def apply_legacy_grant(config: dict) -> dict:
    """Ensure all known add-ons have an explicit feature flag; grant them if none exist.

    Returns the (possibly modified) config dict. Does not write; caller is responsible for
    persistence. Handles malformed/missing features gracefully (same as lib/instance.py).
    """
    if not isinstance(config, dict):
        config = {}

    features = config.get("features")
    if not isinstance(features, dict):
        features = {}

    for addon in KNOWN_ADDONS:
        if addon not in features:
            features[addon] = True

    config["features"] = features
    return config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--instance-dir", type=Path, default=None,
                    help="Path to instance dir (default: MARVIN_INSTANCE_DIR or ~/.agents/instance)")
    args = ap.parse_args(argv)

    if args.instance_dir:
        inst_dir = args.instance_dir
    else:
        import os
        inst_dir = Path(os.environ.get("MARVIN_INSTANCE_DIR") or Path.home() / ".agents" / "instance")

    config_path = inst_dir / "instance.json"

    try:
        if config_path.exists():
            data = json.loads(config_path.read_text())
        else:
            data = {}
    except (ValueError, OSError):
        data = {}

    before = json.dumps(data.get("features") or {}, sort_keys=True)
    updated = apply_legacy_grant(data)
    after = json.dumps(updated.get("features") or {}, sort_keys=True)

    if before == after:
        print(f"addon_migrate: {config_path} unchanged (features already configured)")
        return 0

    inst_dir.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_name(f".{config_path.name}.tmp")
    tmp.write_text(json.dumps(updated, indent=2) + "\n")
    tmp.replace(config_path)

    print(f"addon_migrate: {config_path} updated (all known add-ons granted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
