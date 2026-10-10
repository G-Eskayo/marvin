#!/usr/bin/env python3
"""Quality trends collector — four metrics per project visible via Health checks (ADR 0063, #342).

Collects: mutation-test score trends, test skip frequency, below-80%-score PR count, repo growth.
Persists via metrics_registry for cross-machine aggregation and trend charts in the dashboard.
One daily snapshot per project; one Health check that watches mutation scores and skip-rate regressions.

    quality_trends.py run      scheduled daily on the mini (one job, not per-ticket)
    python health_checks.py    already reads the snapshots via check_quality_trends()
"""
from __future__ import annotations
import fcntl
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_merge_policy as amp  # noqa: E402
import auto_merge_shadow as ams  # noqa: E402
import job_events  # noqa: E402
import machine_profile  # noqa: E402
import metrics_registry as mr  # noqa: E402
import project_catalog  # noqa: E402

try:
    import project_profile  # noqa: E402
except ImportError:
    project_profile = None

HOME = Path.home()
SKIP_LOG_PATH = HOME / ".claude" / "logs" / "test-skips.jsonl"
TIME_BOX_SECONDS = 30


def _gh(args: list[str]) -> str:
    """Run gh command with shared environment, return stdout."""
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env=project_catalog.run_env()
    ).stdout


def new_top_level_folders_since(repo_path: Path, since_days: int = 7) -> set[str]:
    """Top-level dirs at HEAD minus top-level dirs at a commit `since_days` ago.
    Missing/shallow history returns empty set, not crash."""
    repo_path = Path(repo_path)
    if not (repo_path / ".git").exists():
        return set()

    def _top_level_at(ref: str) -> set[str]:
        try:
            result = subprocess.run(
                ["git", "ls-tree", "-d", "--name-only", ref],
                cwd=repo_path, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return set(line.strip() for line in result.stdout.strip().split("\n") if line.strip())
        except (subprocess.TimeoutExpired, Exception):
            pass
        return set()

    try:
        # Use git's relative date parser instead of manual epoch math
        result = subprocess.run(
            ["git", "rev-list", "-1", f"--before={since_days} days ago", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            old_ref = result.stdout.strip()
        else:
            return set()
    except (subprocess.TimeoutExpired, Exception):
        return set()

    current = _top_level_at("HEAD")
    old = _top_level_at(old_ref)
    return current - old


def repo_size(repo_path: Path, time_budget_seconds: float = TIME_BOX_SECONDS) -> dict:
    """Return {files, folders, size_bytes, truncated?} for the repo.
    Excludes .git, node_modules, venv, __pycache__, and other generated files.
    Time-boxed: returns partial counts with truncated=True if budget exceeded."""
    repo_path = Path(repo_path)
    if not repo_path.exists():
        return {"files": 0, "folders": 0, "size_bytes": 0, "truncated": False}

    # Separate exact names and glob patterns
    EXCLUDE_EXACT = {".git", "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache", "build", "dist"}
    EXCLUDE_GLOB = [".venv-*"]

    files = 0
    folders = 0
    size_bytes = 0
    start_time = time.time()

    def should_exclude(name: str) -> bool:
        if name in EXCLUDE_EXACT:
            return True
        for pattern in EXCLUDE_GLOB:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    try:
        for root, dirs, fnames in os.walk(repo_path):
            # Check time budget before processing this directory
            if time.time() - start_time > time_budget_seconds:
                return {"files": files, "folders": folders, "size_bytes": size_bytes, "truncated": True}

            dirs[:] = [d for d in dirs if not should_exclude(d)]
            folders += len(dirs)
            files += len(fnames)

            # Also check budget inside the fnames loop (handles single huge leaf directories)
            for i, f in enumerate(fnames):
                if i % 500 == 0 and time.time() - start_time > time_budget_seconds:
                    return {"files": files, "folders": folders, "size_bytes": size_bytes, "truncated": True}
                try:
                    size_bytes += os.path.getsize(Path(root) / f)
                except OSError:
                    pass
    except (OSError, Exception):
        pass

    return {"files": files, "folders": folders, "size_bytes": size_bytes, "truncated": False}


def _tail_lines(path: Path, max_lines: int = 5000) -> list[str]:
    """Read last max_lines from a file, bounded tail read.
    Works in 64 KB chunks from EOF, accumulates until max_lines or BOF.
    Limitation: assumes chronological appends, so matches older-in-file than the tail window are missed."""
    if not path.exists():
        return []

    lines = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)  # Seek to EOF
            file_size = f.tell()

            chunk_size = 65536
            pos = file_size

            while pos > 0 and len(lines) < max_lines:
                pos = max(0, pos - chunk_size)
                f.seek(pos)
                chunk = f.read(min(chunk_size, file_size - pos))
                try:
                    chunk_text = chunk.decode("utf-8", errors="ignore")
                except Exception:
                    break
                chunk_lines = chunk_text.split("\n")
                # Skip the incomplete first line (it's a tail from the previous chunk)
                if pos > 0:
                    chunk_lines = chunk_lines[1:]
                lines = chunk_lines + lines
                # Stop if we have enough
                if len(lines) >= max_lines:
                    lines = lines[-max_lines:]
                    break
        return lines
    except Exception:
        return []


def _repo_matches(logged_repo: str, clone_path: Path, repo: str) -> bool:
    """Check if a logged repo path matches the expected repo.
    Exact match, or (for pipeline worktrees) token match on the short name."""
    # Exact match
    if logged_repo == str(clone_path):
        return True

    # Pipeline worktree pattern: ~/.agents-pipeline-worktrees/pipeline-owner-name-#ticket
    short_name = repo.split("/")[-1]
    worktrees_root = HOME / ".agents-pipeline-worktrees"

    if worktrees_root.as_posix() in logged_repo:
        # Extract the repo short name from the worktree dirname
        # Format: pipeline-g-eskayo-marvin-342 contains "marvin"
        for token in logged_repo.replace("/", "-").replace("#", "-").split("-"):
            if token == short_name:
                return True

    return False


def recent_skips(log_path: Path, repo: str, clone_path: Path, since_days: int = 7) -> list[dict]:
    """Filter test-skips.jsonl by repo + time window using tail-bounded read.
    Tolerant of missing file and malformed lines."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []

    cutoff = time.time() - since_days * 86400
    result = []

    try:
        for line in _tail_lines(log_path):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if _repo_matches(entry.get("repo", ""), clone_path, repo) and entry.get("at", 0) >= cutoff:
                    result.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass

    return result


def merged_pr_scores(gh, repo: str, since_days: int = 7) -> list[dict]:
    """Fetch merged PRs and parse their mutation scores. gh failure returns []."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    try:
        prs_text = gh("pr", "list", "--repo", repo, "--state", "merged",
                      "--limit", "100", "--json", "number,mergedAt,body")
        prs = json.loads(prs_text)
        if not isinstance(prs, list):
            prs = []
    except (Exception, json.JSONDecodeError):
        return []

    result = []
    for pr in prs:
        try:
            merged_at_str = pr.get("mergedAt", "")
            if merged_at_str:
                merged_at = datetime.fromisoformat(merged_at_str.replace("Z", "+00:00"))
                if merged_at < cutoff:
                    continue
            else:
                # Skip PRs with unparseable dates
                continue
        except (ValueError, AttributeError):
            continue

        body = pr.get("body") or ""
        score = ams.mutation_score(body)
        result.append({"number": pr.get("number"), "score": score})

    return result


def collect(repo: str, repo_path: Path, gh, log_path: Path, clone_path: Path, now: float) -> dict:
    """Collect the four metrics for one project."""
    repo_path = Path(repo_path)

    mutation_scores = []
    prs_data = merged_pr_scores(gh, repo, since_days=7)
    for pr in prs_data:
        if pr.get("score") is not None:
            mutation_scores.append(pr["score"])

    # Score 0% is below 80 and counts; use is not None check
    prs_below_80pct = len([p for p in prs_data if p.get("score") is not None and p["score"] < ams.MIN_SCORE])
    unscored_prs = len([p for p in prs_data if p.get("score") is None])

    mutation_score_pct = None
    if mutation_scores:
        mutation_score_pct = sum(mutation_scores) / len(mutation_scores)

    test_skips = len(recent_skips(log_path, repo, clone_path, since_days=7))

    growth = repo_size(repo_path)
    new_top_level = len(new_top_level_folders_since(repo_path, since_days=7))

    return {
        "mutation_score_pct": mutation_score_pct,
        "prs_below_80pct": prs_below_80pct,
        "prs_unscored": unscored_prs,
        "test_skips_7d": test_skips,
        "new_top_level_7d": new_top_level,
        "repo_files": growth["files"],
        "repo_folders": growth["folders"],
        "repo_size_bytes": growth["size_bytes"],
    }


def record_all(repos: list[dict] | None = None, now: float | None = None, gh=None, log_path: Path | None = None) -> None:
    """Collect and record all metrics for all repos. Idempotent per day: replaces if already today."""
    if project_profile is None:
        return

    if repos is None:
        repos = list(project_profile.all_profiles())
    if now is None:
        now = time.time()
    if gh is None:
        gh = _gh
    if log_path is None:
        log_path = SKIP_LOG_PATH

    log_path = Path(log_path)

    # Load catalog once for all catalog-mode projects
    catalog_path = project_catalog.catalog_path()
    catalog = project_catalog.read_catalog(catalog_path)

    for repo_info in repos:
        repo = repo_info.get("repo")
        if not repo:
            continue

        try:
            profile = next((p for p in project_profile.all_profiles() if p.get("repo") == repo), None)
            if not profile:
                continue

            clone_path = project_profile.resolve_clone(profile, catalog=catalog, ensure=False)
            if not clone_path:
                continue

            metrics = collect(repo, clone_path, gh, log_path, clone_path, now)

            short_name = repo.split("/")[-1]
            subsystem = f"quality-trends-{short_name}"  # hyphen, not dot

            # Build payload: always include these keys
            payload = {
                "prs_below_80pct": {"value": metrics["prs_below_80pct"], "higher_is_better": False},
                "prs_unscored": {"value": metrics["prs_unscored"], "higher_is_better": False},
                "test_skips_7d": {"value": metrics["test_skips_7d"], "higher_is_better": False},
                "new_top_level_7d": {"value": metrics["new_top_level_7d"], "higher_is_better": False},
                "repo_files": {"value": metrics["repo_files"], "higher_is_better": True},
                "repo_folders": {"value": metrics["repo_folders"], "higher_is_better": True},
                "repo_size_bytes": {"value": metrics["repo_size_bytes"], "higher_is_better": True},
            }

            # Only include mutation_score_pct if we have real scores (never fabricate 0)
            if metrics["mutation_score_pct"] is not None:
                payload["mutation_score_pct"] = {
                    "value": metrics["mutation_score_pct"],
                    "higher_is_better": True
                }

            mr.record(subsystem, payload, replace_same_day=True)
        except Exception as e:
            print(f"Failed to collect metrics for {repo}: {str(e)[:200]}", file=sys.stderr)
            job_events.step(f"{repo} failed", str(e)[:200])
            continue


def check_quality_trends(repos: list[dict] | None = None) -> list[dict]:
    """Health check for quality trends. Reads latest snapshots and reports severity.

    Severity ladder:
    - green (informational): no snapshot yet ("no data yet")
    - red: any recent skip touches a core-area file (per config/auto_merge.json)
    - yellow: trending up (test_skips_7d or mutation_score_pct regressing), or stale snapshot (>2 days old)
    - green: otherwise
    """
    if repos is None:
        if project_profile:
            repos = list(project_profile.all_profiles())
        else:
            repos = []

    results = []

    if not repos:
        return [
            {
                "id": "quality:trends",
                "label": "Quality trends",
                "severity": "green",
                "detail": "No projects to monitor (quality-trends inactive)",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": None,
            }
        ]

    rules = amp.load_rules()

    for repo_info in repos:
        repo = repo_info.get("repo")
        if not repo:
            continue

        short_name = repo.split("/")[-1]
        subsystem = f"quality-trends-{short_name}"
        cid = f"quality:{short_name}"
        label = f"Quality trends: {short_name}"

        try:
            profile = next((p for p in project_profile.all_profiles() if p.get("repo") == repo), None)
            if not profile:
                continue

            clone_path = project_profile.resolve_clone(profile, ensure=False)
            if not clone_path:
                continue

            # Check for recent core-area skips
            recent = recent_skips(SKIP_LOG_PATH, repo, clone_path, since_days=7)
            severity = "green"
            detail = "No recent issues"

            # Red if any skip touches a core file
            for skip_entry in recent:
                for file_path in skip_entry.get("files", []):
                    area = amp.area(file_path, rules, [])
                    if area == "core":
                        severity = "red"
                        detail = f"Core-area code merged without tests: {file_path}"
                        break
                if severity == "red":
                    break

            if severity != "red":
                # Check for trending (yellow)
                metrics = mr.latest(subsystem)
                if metrics is None:
                    severity = "green"
                    detail = "No data yet"
                else:
                    # Check if snapshot is stale (>2 days old)
                    path = mr._snapshot_path(subsystem)
                    if path.exists():
                        snapshots = json.loads(path.read_text())
                        if snapshots:
                            last_ts_str = snapshots[-1].get("timestamp", "")
                            try:
                                last_ts = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
                                age = (datetime.now(timezone.utc) - last_ts).total_seconds()
                                if age > 2 * 86400:
                                    severity = "yellow"
                                    detail = "Snapshot is stale (>2 days old)"
                            except (ValueError, IndexError):
                                pass

                    # Check for trends via mr.compare (if >=2 snapshots)
                    if severity == "green" and 'snapshots' in locals() and len(snapshots) >= 2:
                        prev = snapshots[-2].get("metrics", {})
                        curr = snapshots[-1].get("metrics", {})
                        comparison = mr.compare(subsystem, prev, curr)
                        if comparison.get("verdict") == "regressed":
                            severity = "yellow"
                            regressed_metrics = [n for n, m in comparison.get("metrics", {}).items() if m.get("direction") == "regressed"]
                            detail = f"Metrics regressing: {', '.join(regressed_metrics)}"

                    # Build detail with current values
                    if severity == "green" and metrics:
                        score = metrics.get("mutation_score_pct", {}).get("value")
                        detail = f"Mutation score: {score:.0f}%" if score is not None else "No score data"

            results.append({
                "id": cid,
                "label": label,
                "severity": severity,
                "detail": detail,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": None,
            })
        except Exception as e:
            results.append({
                "id": cid,
                "label": label,
                "severity": "yellow",
                "detail": f"Check failed: {str(e)[:100]}",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": None,
            })

    return results


@job_events.reported("quality-trends", "Quality trends")
def run(repos: list[dict] | None = None) -> None:
    """CLI entry: collect and record all metrics."""
    if repos is None:
        if project_profile:
            repos = list(project_profile.all_profiles())
        else:
            repos = [{"repo": "G-Eskayo/marvin"}]

    job_events.step("Collecting quality metrics", f"{len(repos)} projects")

    record_all(repos, now=time.time(), gh=_gh, log_path=SKIP_LOG_PATH)
    job_events.step("Complete", "all snapshots recorded")


if __name__ == "__main__":
    run()
