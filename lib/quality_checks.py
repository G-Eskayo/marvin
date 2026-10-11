#!/usr/bin/env python3
"""Quality checks: code mutation testing, test coverage, and repo growth (ADR 0063, #342).

These checks monitor the health of test coverage and code quality over time by:
- check_mutation_trend: tracks mutation score trends across merged PRs
- check_below_bar_merges: flags PRs that merged without sufficient test coverage for core changes
- check_test_skips: counts code changes committed without test reasons
- check_repo_growth: monitors folder count and disk usage growth
- check_all: aggregates the above into health check results
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_merge_shadow as ams  # noqa: E402
import auto_merge_policy as amp  # noqa: E402
import test_change_rule as tcr  # noqa: E402
import metrics_registry as mr  # noqa: E402
import ticket_agents  # noqa: E402
import project_profile  # noqa: E402


def _fetch_merged_prs(repo: str, run=subprocess.run) -> tuple[list[dict], str | None]:
    """Fetch merged PRs for a repo. Returns (prs_list, error_message).

    One call handles both check_mutation_trend and check_below_bar_merges.
    Robust exception handling; returns empty list on any failure.
    """
    try:
        proc = run(["gh", "pr", "list", "--repo", repo, "--state", "merged", "--limit", "30",
                   "--json", "number,title,body,files"],
                  capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return [], f"gh pr list failed with code {proc.returncode}"
        prs = json.loads(proc.stdout) if proc.stdout else []
        return prs, None
    except subprocess.TimeoutExpired:
        return [], "timeout fetching PRs"
    except OSError:
        return [], "gh not available"
    except json.JSONDecodeError:
        return [], "malformed JSON response"
    except (ValueError, TypeError):
        return [], "unexpected response format"


def check_mutation_trend(repos: list[str] | None = None, run=subprocess.run, fetched: dict[str, tuple[list[dict], str|None]] | None = None) -> list[dict]:
    """Per-repo mutation score trend. Yellow if trending down vs. prior snapshot.
    Uses ticket_agents.board_repos() if repos=None; scores via ams.mutation_score().
    On fetch error, appends yellow result with value=None instead of skipping repo."""
    if repos is None:
        repos = ticket_agents.board_repos() or []
    if not repos:
        return []

    results = []
    for repo in repos:
        cid = f"quality:mutation:{repo}"
        label = f"Code mutation score — {repo}"

        if fetched is not None and repo in fetched:
            prs, error = fetched[repo]
        else:
            prs, error = _fetch_merged_prs(repo, run=run)

        if error:
            results.append({
                "id": cid, "label": label, "severity": "yellow",
                "detail": f"could not fetch PRs: {error}",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": None
            })
            continue

        scores = []
        for pr in prs:
            if not isinstance(pr, dict):
                continue
            body = pr.get("body") or ""
            score = ams.mutation_score(body)
            if score is not None:
                scores.append(score)

        if not scores:
            results.append({
                "id": cid, "label": label, "severity": "green",
                "detail": f"no mutation scores in last 30 merged PRs",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": 0
            })
            continue

        current_avg = sum(scores) / len(scores)

        # Compare against baseline (defensive: handle None/missing values)
        baseline = mr.latest("health-monitor") or {}
        baseline_val = None
        if isinstance(baseline, dict):
            baseline_entry = baseline.get(cid)
            if isinstance(baseline_entry, dict):
                baseline_val = baseline_entry.get("value")

        if baseline_val is not None:
            try:
                baseline_val = float(baseline_val)
                if current_avg < baseline_val * 0.98:
                    results.append({
                        "id": cid, "label": label, "severity": "yellow",
                        "detail": f"mutation score down: {current_avg:.0f}% (was {baseline_val:.0f}%)",
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "value": round(current_avg)
                    })
                else:
                    results.append({
                        "id": cid, "label": label, "severity": "green",
                        "detail": f"mutation score {current_avg:.0f}% across last 30 merged PRs",
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "value": round(current_avg)
                    })
            except (ValueError, TypeError):
                # Baseline value not numeric; treat as no baseline
                results.append({
                    "id": cid, "label": label, "severity": "green",
                    "detail": f"mutation score {current_avg:.0f}% across last 30 merged PRs",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "value": round(current_avg)
                })
        else:
            results.append({
                "id": cid, "label": label, "severity": "green",
                "detail": f"mutation score {current_avg:.0f}% across last 30 merged PRs",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": round(current_avg)
            })

    return results


def check_below_bar_merges(repos: list[str] | None = None, run=subprocess.run, fetched: dict[str, tuple[list[dict], str|None]] | None = None) -> list[dict]:
    """Red if any merged PR touched core paths with zero test-file changes.
    Yellow if any score < 80 but no core-no-tests issue.
    Green otherwise."""
    if repos is None:
        repos = ticket_agents.board_repos() or []
    if not repos:
        return []

    results = []
    for repo in repos:
        cid = f"quality:below-bar:{repo}"
        label = f"Code below mutation bar — {repo}"

        if fetched is not None and repo in fetched:
            prs, error = fetched[repo]
        else:
            prs, error = _fetch_merged_prs(repo, run=run)

        if error:
            results.append({
                "id": cid, "label": label, "severity": "yellow",
                "detail": f"could not fetch PRs: {error}",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": None
            })
            continue

        # Load profile and rules once per repo
        try:
            profile = project_profile.load_profile(repo)
            test_rules = tcr.rules_for_profile(profile)
        except ValueError:
            results.append({
                "id": cid, "label": label, "severity": "green",
                "detail": "Could not load profile; no data to report",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": 0
            })
            continue
        except Exception:
            profile = {}
            test_rules = {}

        try:
            rules = amp.load_rules(rules_path=None)
        except Exception:
            rules = {}

        below_bar_scores = []
        core_no_tests = []

        for pr in prs:
            if not isinstance(pr, dict):
                continue

            body = pr.get("body") or ""
            score = ams.mutation_score(body)

            # Get file paths
            files = pr.get("files")
            if not isinstance(files, list):
                files = []
            file_paths = [f.get("path", "") if isinstance(f, dict) else "" for f in files]
            file_paths = [fp for fp in file_paths if fp]

            # Check for low score
            if score is not None and score < 80:
                below_bar_scores.append({
                    "number": pr.get("number"),
                    "title": str(pr.get("title", ""))[:50],
                    "score": score
                })

            # Check for core-no-tests (any measured score or not)
            test_changed = any(tcr.kind(fp, test_rules) == "test" for fp in file_paths)
            code_changed = any(tcr.kind(fp, test_rules) == "code" for fp in file_paths)

            if code_changed and not test_changed:
                # Check if it touched core paths
                core_touched = False
                for fp in file_paths:
                    if tcr.kind(fp, test_rules) == "code":
                        try:
                            area = amp.area(fp, rules, set())
                            if area == "core":
                                core_touched = True
                                break
                        except Exception:
                            pass

                if core_touched:
                    core_no_tests.append({
                        "number": pr.get("number"),
                        "title": str(pr.get("title", ""))[:50],
                        "score": score
                    })

        # Determine severity: red if core_no_tests, yellow if below_bar_scores, else green
        if core_no_tests:
            detail = "; ".join(f"#{p['number']} ({p['score']}%)" for p in core_no_tests[:3])
            if len(core_no_tests) > 3:
                detail += f" + {len(core_no_tests) - 3} more"
            results.append({
                "id": cid, "label": label, "severity": "red",
                "detail": f"Merged without sufficient test coverage on core paths: {detail}",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": len(core_no_tests)
            })
        elif below_bar_scores:
            detail = "; ".join(f"#{p['number']} ({p['score']}%)" for p in below_bar_scores[:3])
            if len(below_bar_scores) > 3:
                detail += f" + {len(below_bar_scores) - 3} more"
            results.append({
                "id": cid, "label": label, "severity": "yellow",
                "detail": f"Merged with mutation score < 80%: {detail}",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": len(below_bar_scores)
            })
        else:
            results.append({
                "id": cid, "label": label, "severity": "green",
                "detail": "All merged PRs have passing mutation scores or test changes",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": 0
            })

    return results


def check_test_skips(log_path: Path | None = None, window_days: int = 7) -> dict:
    """Yellow if count > 0 in the window. Surfaces most recent reason text.
    Tolerant of missing/corrupt JSONL lines."""
    if log_path is None:
        log_path = Path(os.environ.get("MARVIN_TEST_SKIP_LOG") or
                       Path.home() / ".claude" / "logs" / "test-skips.jsonl")

    cid = "quality:test-skips"
    label = "Code committed without test reasons"

    if not log_path.exists():
        return {
            "id": cid, "label": label, "severity": "green",
            "detail": "no test-skip log (everything has tests or stated reasons)",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "value": 0
        }

    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - window_days * 86400
    count = 0
    reasons = []

    try:
        lines = log_path.read_text(errors="replace").splitlines()
    except OSError:
        return {
            "id": cid, "label": label, "severity": "yellow",
            "detail": "could not read test-skip log",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "value": None
        }

    for line in lines:
        try:
            if not isinstance(line, str):
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict):
                continue
            at = entry.get("at")
            if at is not None:
                try:
                    at = float(at)
                    if at >= cutoff:
                        count += 1
                        reason = entry.get("reason", "")
                        if reason and reason not in reasons:
                            reasons.append(reason)
                except (ValueError, TypeError):
                    continue
        except (json.JSONDecodeError, ValueError):
            continue  # Skip corrupt lines

    severity = "yellow" if count > 0 else "green"
    if count:
        reason_str = "; ".join(reasons[:3])
        if len(reasons) > 3:
            reason_str += f"; + {len(reasons) - 3} more"
        detail = f"{count} code change(s) without test reasons in the last {window_days}d: {reason_str}"
    else:
        detail = f"no code committed without test reasons in the last {window_days}d"

    return {
        "id": cid, "label": label, "severity": severity,
        "detail": detail,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "value": count
    }


def check_repo_growth(repo_path: Path | None = None, rules_path: Path | None = None) -> dict:
    """Monitors folder/file/size counts and new top-level folder growth.
    Two parts: file counts for repo_path (informational, green), and new top-level folders
    over 7 days (severity from config/auto_merge.json's new_top_level_per_week)."""
    if repo_path is None:
        repo_path = Path.home() / ".agents"

    cid = "quality:repo-growth"
    label = "Repository growth monitoring"

    try:
        # Count files, folders, and size via os.walk, excluding .git
        total_files = 0
        total_folders = 0
        total_size = 0

        if not repo_path.is_dir():
            return {
                "id": cid, "label": label, "severity": "yellow",
                "detail": "repo_path is not a readable directory",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "value": None
            }

        for dirpath, dirnames, filenames in os.walk(str(repo_path)):
            # Prune .git from descent
            if ".git" in dirnames:
                dirnames.remove(".git")

            total_folders += len(dirnames)
            for fname in filenames:
                total_files += 1
                try:
                    fpath = Path(dirpath) / fname
                    total_size += fpath.stat().st_size
                except OSError:
                    # Skip broken symlinks or unreadable files
                    pass

        counts_detail = f"{total_files} files, {total_folders} folders, {total_size / 1048576:.0f} MB"
    except (OSError, TypeError):
        counts_detail = "could not count files"

    # Check for new top-level folders in the last 7 days using git log --diff-filter=A
    new_top_level = 0
    detail = f"{counts_detail} (informational)"
    severity = "green"

    try:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        top_level_dirs = set()
        try:
            for item in repo_path.iterdir():
                if item.is_dir() and item.name != ".git":
                    top_level_dirs.add(item.name)
        except OSError:
            top_level_dirs = set()

        new_top_level = 0
        all_git_calls_failed = True

        for dir_name in top_level_dirs:
            try:
                proc = subprocess.run(
                    ["git", "-C", str(repo_path), "log", "--diff-filter=A", "-1", "--format=%aI", "--", dir_name],
                    capture_output=True, text=True, timeout=5
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    all_git_calls_failed = False
                    first_touch_str = proc.stdout.strip()
                    first_touch = datetime.fromisoformat(first_touch_str)
                    if first_touch > week_ago:
                        new_top_level += 1
            except (subprocess.TimeoutExpired, OSError, ValueError):
                # Skip on error (per-dir failure tolerated)
                pass

        # Load severity threshold from auto_merge rules, threading rules_path
        try:
            rules = amp.load_rules(rules_path) if rules_path else amp.load_rules()
            if rules is None:
                rules = {}
            threshold = rules.get("new_top_level_per_week", 2)
        except Exception:
            threshold = 2

        if all_git_calls_failed and top_level_dirs:
            # Fail closed to yellow when repo is not a git repo
            severity = "yellow"
            detail = f"{counts_detail}; could not check git history (not a git repo?)"
        elif new_top_level > threshold:
            severity = "yellow"
            detail = f"{counts_detail}; {new_top_level} new top-level folder(s) in 7d (threshold: {threshold})"
        else:
            detail = f"{counts_detail} (informational); {new_top_level} new top-level folder(s) in 7d"
    except (subprocess.TimeoutExpired, OSError):
        # If major git operation fails, fail closed
        severity = "yellow" if severity == "green" else severity

    return {
        "id": cid, "label": label, "severity": severity,
        "detail": detail,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "value": new_top_level
    }


def check_all(repos: list[str] | None = None, log_path: Path | None = None,
             repo_path: Path | None = None, rules_path: Path | None = None,
             run=subprocess.run) -> list[dict]:
    """Aggregate all quality checks. Does one shared PR fetch per repo.
    Accepts injectable parameters for testing."""
    if repos is None:
        repos = ticket_agents.board_repos() or []

    # Do one shared fetch per repo for both GitHub-sourced checks
    fetched = {}
    for repo in repos:
        fetched[repo] = _fetch_merged_prs(repo, run=run)

    results = []
    results += check_mutation_trend(repos=repos, run=run, fetched=fetched)
    results += check_below_bar_merges(repos=repos, run=run, fetched=fetched)
    results.append(check_test_skips(log_path=log_path, window_days=7))
    results.append(check_repo_growth(repo_path=repo_path, rules_path=rules_path))
    return results
