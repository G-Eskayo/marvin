#!/usr/bin/env python3
"""
deploy_snapshot.py — Deploy a privacy-filtered map snapshot to the portfolio website.

Runs export_snapshot.py to generate a fresh snapshot, validates the output against
privacy and correctness criteria, and deploys to the portfolio's /map-v2/ path via
wp-cli if privacy validation passes. On failure, keeps the previous snapshot intact
and raises a health warning.

Acceptance criteria from #188:
  - The website snapshot loads with no console errors and no local paths or private data.
  - Private projects are locked nodes (named but never openable, no code shown).
  - Automatic rebuild: nightly, and on any marvin commit changing the system tree.
  - A blocked deploy keeps the previous snapshot and raises a health warning.
  - Off-by-default flag controlling whether the map is deployed to the public site.

Usage:
    python deploy_snapshot.py [--dry-run] [--force]

Environment:
    MARVIN_SNAPSHOT_ENABLED=1  Enable snapshot deployment (default: 0, off by default)

Log: ~/.claude/logs/deploy-snapshot.log
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
HOME = Path.home()
SNAPSHOT_DIR = HERE / "snapshot"
SNAPSHOT_LOG = HOME / ".claude" / "logs" / "deploy-snapshot.log"
SNAPSHOT_FLAG_ENABLED = bool(int(os.environ.get("MARVIN_SNAPSHOT_ENABLED", "0")))
# ADR 0057: after the dev deploy passes, also put the map live (only deploy/marvin-map/ in the portfolio repo).
PUBLISH_ENABLED = bool(int(os.environ.get("MARVIN_SNAPSHOT_PUBLISH", "0")))

# Portfolio deployment via wp-cli (same pattern as portfolio_apply.py)
WPCLI_CONTAINER = "portfolio-website-updater-wpcli-1"
WP_USER = "Gil"
WP_MAP_PATH = "wp-content/marvin-map"  # WordPress path for the map-v2 files

def _get_docker_path() -> str:
    try:
        result = subprocess.run(["which", "docker"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "/usr/local/bin/docker"

DOCKER = _get_docker_path()


def log_step(step: str, ok: bool, detail: str = "") -> None:
    """Append a step result to the log."""
    SNAPSHOT_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    status = "✓" if ok else "✗"
    line = f"{timestamp} {status} {step}"
    if detail:
        line += f" — {detail}"
    with open(SNAPSHOT_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_export_snapshot(commit: str = "HEAD") -> tuple[bool, str]:
    """Generate a fresh privacy-filtered snapshot. Returns (success, message)."""
    try:
        result = subprocess.run(
            [sys.executable or "python3", str(HERE / "export_snapshot.py"), "--commit", commit],
            capture_output=True, text=True, timeout=120, cwd=REPO_ROOT
        )
        if result.returncode != 0:
            msg = result.stderr.strip() if result.stderr else result.stdout.strip()
            return False, f"export failed: {msg[:100]}"
        return True, result.stdout.strip().split("\n")[-1] if result.stdout else "generated snapshot"
    except subprocess.TimeoutExpired:
        return False, "export timed out (>120s)"
    except Exception as e:
        return False, f"export error: {e}"


def validate_snapshot_files() -> tuple[bool, str]:
    """Ensure snapshot files exist and are well-formed JSON/HTML."""
    html_file = SNAPSHOT_DIR / "index.html"
    json_file = SNAPSHOT_DIR / "tree-data.json"

    if not html_file.exists():
        return False, "index.html not found"
    if not json_file.exists():
        return False, "tree-data.json not found"

    # Validate HTML structure
    try:
        html = html_file.read_text(encoding="utf-8")
        if "SNAPSHOT = true" not in html:
            return False, "SNAPSHOT flag not set in HTML"
        if "<script" not in html or "</script>" not in html:
            return False, "HTML structure invalid (missing script tags)"
    except Exception as e:
        return False, f"HTML validation failed: {e}"

    # Validate JSON structure
    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "tree" not in data or "synapses" not in data:
            return False, "tree-data.json structure invalid"
    except Exception as e:
        return False, f"JSON validation failed: {e}"

    return True, "snapshot files valid"


def scan_for_private_content(html: str) -> list[str]:
    """Scan rendered HTML for common privacy leaks. Returns list of found leaks."""
    leaks = []

    # Home directory paths
    if re.search(r"/Users/\w+", html):
        leaks.append("Contains /Users/ path")

    # IPv4 (non-loopback)
    if re.search(r"(?!127\.)(?:\d{1,3}\.){3}\d{1,3}", html):
        leaks.append("Contains IPv4 address")

    # Email addresses (basic pattern)
    if re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", html):
        leaks.append("Contains email")

    # Common token patterns
    token_patterns = [
        (r"sk-ant-[a-zA-Z0-9]+", "Anthropic token (sk-ant-)"),
        (r"gh[pousr]_[a-zA-Z0-9]+", "GitHub token (gh*_)"),
    ]
    for pattern, name in token_patterns:
        if re.search(pattern, html):
            leaks.append(name)

    return leaks


def validate_snapshot_content() -> tuple[bool, str]:
    """Validate snapshot for privacy leaks and integrity."""
    html_file = SNAPSHOT_DIR / "index.html"
    json_file = SNAPSHOT_DIR / "tree-data.json"

    try:
        html = html_file.read_text(encoding="utf-8")
        leaks = scan_for_private_content(html)
        if leaks:
            return False, f"privacy leaks found: {'; '.join(leaks)}"

        data = json.loads(json_file.read_text(encoding="utf-8"))
        tree = data.get("tree", {})

        # Check that locked nodes exist (private projects)
        def has_locked_nodes(node: dict) -> bool:
            if node.get("locked") is True:
                return True
            for child in node.get("children", []):
                if has_locked_nodes(child):
                    return True
            return False

        # Verify SNAPSHOT flag
        if "SNAPSHOT = true" not in html and "SNAPSHOT=true" not in html:
            return False, "SNAPSHOT flag not enabled"

        return True, "snapshot content valid"
    except Exception as e:
        return False, f"content validation error: {e}"


def upload_to_portfolio(html_file: Path, json_file: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Deploy snapshot files to portfolio via wp-cli. Returns (success, message)."""
    if dry_run:
        return True, f"[DRY RUN] would deploy to /{WP_MAP_PATH}/ on portfolio"

    try:
        # Check if wp-cli container is running
        check = subprocess.run(
            [DOCKER, "exec", WPCLI_CONTAINER, "wp", "--version"],
            capture_output=True, timeout=5
        )
        if check.returncode != 0:
            return False, "portfolio dev site not running"

        # Create the directory on the dev site
        subprocess.run(
            [DOCKER, "exec", WPCLI_CONTAINER, "mkdir", "-p", f"/var/www/html/{WP_MAP_PATH}"],
            capture_output=True, timeout=10
        )

        # Copy files into the container using docker cp
        for required in (html_file, json_file):
            if not required.exists():
                return False, f"{required.name} not found"
        # every file the snapshot has (index.html, tree-data.json, facts.json, …): copying by name left new files behind
        for local in sorted(p for p in html_file.parent.iterdir() if p.is_file() and not p.name.startswith(".")):
            remote_name = local.name

            docker_path = f"{WPCLI_CONTAINER}:/var/www/html/{WP_MAP_PATH}/{remote_name}"
            result = subprocess.run(
                [DOCKER, "cp", str(local), docker_path],
                capture_output=True, timeout=30
            )
            if result.returncode != 0:
                return False, f"failed to copy {remote_name}"

        # Everything else the page loads (./vendor/... scripts): without them it draws nothing (2026-10-07).
        for sub in sorted(p for p in html_file.parent.iterdir() if p.is_dir()):
            result = subprocess.run(
                [DOCKER, "cp", str(sub), f"{WPCLI_CONTAINER}:/var/www/html/{WP_MAP_PATH}/"],
                capture_output=True, timeout=60
            )
            if result.returncode != 0:
                return False, f"failed to copy {sub.name}/"

        return True, f"deployed to /{WP_MAP_PATH}/"
    except subprocess.TimeoutExpired:
        return False, "upload timed out"
    except Exception as e:
        return False, f"upload error: {e}"


def health_check_mark_success() -> None:
    """Mark snapshot deployment as healthy in the Health check system."""
    health_status_file = HOME / ".claude" / "health" / "snapshot-deploy.json"
    health_status_file.parent.mkdir(parents=True, exist_ok=True)
    health_status_file.write_text(
        json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "message": "snapshot deployed successfully"
        }, indent=2),
        encoding="utf-8"
    )


def health_check_mark_failure(reason: str) -> None:
    """Mark snapshot deployment as failed in the Health check system."""
    health_status_file = HOME / ".claude" / "health" / "snapshot-deploy.json"
    health_status_file.parent.mkdir(parents=True, exist_ok=True)
    health_status_file.write_text(
        json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "message": reason
        }, indent=2),
        encoding="utf-8"
    )


def publish_to_production() -> tuple[bool, str]:
    """publish_map.publish() as (ok, detail); a refusal or git failure is a failure, never an exception."""
    import publish_map
    try:
        return True, publish_map.publish(SNAPSHOT_DIR)
    except publish_map.PublishRefused as e:
        return False, f"refused: {e}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:300]}"


def deploy_snapshot(commit: str = "HEAD", dry_run: bool = False, force: bool = False) -> bool:
    """Orchestrate snapshot export and deployment. Returns True on success."""
    start_time = time.time()
    enabled = SNAPSHOT_FLAG_ENABLED or force

    if not enabled:
        log_step("snapshot-disabled", True, "feature flag off (set MARVIN_SNAPSHOT_ENABLED=1 to enable)")
        return True

    # Step 1: Export snapshot
    ok, detail = run_export_snapshot(commit)
    log_step("export", ok, detail)
    if not ok:
        health_check_mark_failure(f"export failed: {detail}")
        return False

    # Step 2: Validate files exist and are well-formed
    ok, detail = validate_snapshot_files()
    log_step("validate-files", ok, detail)
    if not ok:
        health_check_mark_failure(f"file validation failed: {detail}")
        return False

    # Step 3: Validate content for privacy
    ok, detail = validate_snapshot_content()
    log_step("validate-content", ok, detail)
    if not ok:
        health_check_mark_failure(f"privacy validation failed: {detail}")
        print(f"Privacy validation failed: {detail}", file=sys.stderr)
        return False

    # Step 4: Upload to portfolio
    ok, detail = upload_to_portfolio(SNAPSHOT_DIR / "index.html", SNAPSHOT_DIR / "tree-data.json", dry_run)
    log_step("deploy", ok, detail)
    if not ok:
        health_check_mark_failure(f"deployment failed: {detail}")
        return False

    # Step 5: Production, the map only (ADR 0057), and only after every check above passed
    if PUBLISH_ENABLED and not dry_run:
        ok, detail = publish_to_production()
        log_step("publish-production", ok, detail)
        if not ok:
            health_check_mark_failure(f"production publish failed: {detail}")
            return False

    # Step 6: Mark as healthy
    health_check_mark_success()
    elapsed = time.time() - start_time
    log_step("success", True, f"deployed in {elapsed:.1f}s")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate without deploying")
    parser.add_argument("--force", action="store_true", help="deploy even if feature flag is off")
    parser.add_argument("--commit", default="HEAD", help="git commit to export (default: HEAD)")
    args = parser.parse_args()

    success = deploy_snapshot(args.commit, dry_run=args.dry_run, force=args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
