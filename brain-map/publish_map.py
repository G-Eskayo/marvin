#!/usr/bin/env python3
"""
publish_map.py — put the privacy-checked map snapshot live on gileskayo.me (ADR 0056).

The one thing MARVIN may push to the portfolio repo: `deploy/marvin-map/**`. The repo's GitHub action uploads
`deploy/` to /gileskayo.me/wp-content/, so the live site serves /wp-content/marvin-map/, the same path as the dev site.

Works in its own sparse checkout (only deploy/marvin-map/ on disk), never Gil's working copy, so his uncommitted
portfolio changes can't be swept in. Refuses when the commit would touch anything else, or the snapshot is empty.
No commit when nothing changed. A push that loses a race is rebased onto the new main and retried.

Called by deploy_snapshot.py after the dev deploy passed its checks, when MARVIN_SNAPSHOT_PUBLISH=1.
    python publish_map.py [--snapshot DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

REMOTE = "https://github.com/G-Eskayo/portfolio-website-updater.git"
CHECKOUT = Path.home() / "Developer" / "portfolio-map-publisher"
SNAPSHOT = Path(__file__).parent / "snapshot"
ALLOWED_PREFIX = "deploy/marvin-map/"   # fixed: the only path ADR 0056 allows
TARGET = "deploy/marvin-map"           # where the snapshot is copied
REQUIRED = ("index.html", "tree-data.json")
PUSH_ATTEMPTS = 3


class PublishRefused(Exception):
    pass


def _env() -> dict:
    """launchd has no gh login and a locked keychain: reuse the pipeline's shared token (project_catalog.run_env) and
    point git's credential helper at gh for this process only, as task_dispatch does."""
    import os
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
        import project_catalog
        env = project_catalog.run_env()
    except Exception:  # noqa: BLE001
        env = dict(os.environ)
    if env.get("GH_TOKEN"):
        gh = shutil.which("gh", path=env.get("PATH")) or "gh"
        env.update({"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": "",
                    "GIT_CONFIG_KEY_1": "credential.helper", "GIT_CONFIG_VALUE_1": f"!{gh} auth git-credential"})
    env["GIT_TERMINAL_PROMPT"] = "0"  # never wait for a password nobody will type
    return env


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=180, env=_env())
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout.strip()


def _ensure_checkout(checkout: Path, remote: str) -> None:
    if not (checkout / ".git").exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "-q", "--sparse", "--no-checkout"]
        if remote.startswith("https://"):
            args.append("--filter=blob:none")  # only fetch file contents that get checked out
        _git(checkout.parent, *args, remote, str(checkout))
    _git(checkout, "sparse-checkout", "set", "--no-cone", f"/{TARGET}/")
    _git(checkout, "fetch", "-q", "origin", "main")
    _git(checkout, "checkout", "-q", "-B", "main", "origin/main")  # a dedicated checkout: always start from main
    _git(checkout, "reset", "-q", "--hard", "origin/main")


def _copy(snapshot: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(snapshot, dest)


def publish(snapshot: Path = SNAPSHOT, checkout: Path = CHECKOUT, remote: str = REMOTE) -> str:
    """Returns "unchanged" or "published <sha>". Raises PublishRefused when the guard says no."""
    snapshot, checkout = Path(snapshot), Path(checkout)
    missing = [f for f in REQUIRED if not (snapshot / f).is_file()]
    if missing:
        raise PublishRefused(f"snapshot is missing {missing}: nothing to publish")

    _ensure_checkout(checkout, remote)
    _copy(snapshot, checkout / TARGET)
    _git(checkout, "add", "-A", "--sparse", "--", TARGET)
    changed = [p for p in _git(checkout, "diff", "--cached", "--name-only").splitlines() if p]
    if not changed:
        return "unchanged"
    outside = [p for p in changed if not p.startswith(ALLOWED_PREFIX)]
    if outside:
        _git(checkout, "reset", "-q", "--hard", "origin/main")
        raise PublishRefused(f"would change files outside {ALLOWED_PREFIX}: {outside[:5]}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _git(checkout, "commit", "-q", "-m", f"map: publish the MARVIN map snapshot ({stamp})\n\n"
         f"Automatic, ADR 0056 in G-Eskayo/marvin: only {ALLOWED_PREFIX} changes. {len(changed)} file(s).")
    for attempt in range(PUSH_ATTEMPTS):
        try:
            _git(checkout, "push", "-q", "origin", "HEAD:main")
            return f"published {_git(checkout, 'rev-parse', '--short', 'HEAD')} ({len(changed)} file(s))"
        except RuntimeError:
            if attempt == PUSH_ATTEMPTS - 1:
                raise
            _git(checkout, "fetch", "-q", "origin", "main")
            _git(checkout, "rebase", "-q", "origin/main")  # someone pushed meanwhile: keep theirs, add ours on top
    raise RuntimeError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    args = ap.parse_args()
    try:
        print(publish(args.snapshot))
    except PublishRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
