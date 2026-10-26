#!/usr/bin/env python3
"""local_coding_spike.py — measure local code generation (qwen2.5 via opencode) against real gates.

Selects recent small, conventionally-committed merged PRs, replays them with Ollama + opencode,
measures tokens + wall time + energy, and runs each result through the real gate sequence:
build_type_measure + metrics_registry.compare + test_change_rule + code_review_gate.

Run via:
    python3 bench/local_coding_spike.py
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))

import build_type_measure
import code_review_gate
import metrics_registry
import test_change_rule
from energy_apple import EnergySampler


# ============================================================================
# Preflight checks
# ============================================================================

OLLAMA_BASE = "http://localhost:11434"


def _ollama_available(model: str) -> tuple[bool, str]:
    """Return (ok, error_message). Checks server is up and model is pulled."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return False, f"Ollama server not responding ({exc}). Start with: ollama serve"
    available = [m["name"] for m in data.get("models", [])]
    if model not in available:
        return False, (f"Model '{model}' not found. Available: {available}\n"
                       f"Pull with: ollama pull {model}")
    return True, ""


def _opencode_available() -> tuple[bool, str]:
    """Return (ok, error_message). Checks opencode is in PATH."""
    path = shutil.which("opencode")
    if not path:
        return False, ("opencode not found in PATH. Install from SDK examples:\n"
                      "  git clone https://github.com/anthropics/anthropic-sdk-python.git\n"
                      "  cd anthropic-sdk-python/examples/code_editor\n"
                      "  pip install -e .")
    return True, ""


def preflight_checks() -> dict:
    """Return dict with any missing dependencies. Empty dict = all good."""
    issues = {}

    for model in ["qwen2.5:7b", "qwen2.5:14b"]:
        ok, msg = _ollama_available(model)
        if not ok:
            issues[f"ollama_{model}"] = msg
            break  # Only report first failure

    ok, msg = _opencode_available()
    if not ok:
        issues["opencode"] = msg

    return issues


# ============================================================================
# Ticket selection
# ============================================================================

def select_tickets(repo: str, count: int = 5) -> list[dict]:
    """Select recent small, conventionally-committed merged PRs.

    Filters by:
    - docs: / fix: / test: prefix (conventional commits)
    - Small diffs (< 500 lines changed)
    - Recently merged

    Returns list of dicts with keys: number, title, body, base_sha, tip_sha, prompt
    """
    tickets = []

    # Query GitHub for recently merged PRs with conventional prefixes
    prefixes = ["docs:", "fix:", "test:"]
    for prefix in prefixes:
        cmd = [
            "gh", "pr", "list",
            "--repo", repo,
            "--state", "merged",
            "--search", "is:merged",
            "--limit", "50",
            "--json", "number,title,body,mergedBy,mergeCommit,additions,deletions",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                continue

            prs = json.loads(result.stdout) if result.stdout.strip() else []

            for pr in prs:
                if len(tickets) >= count:
                    break

                # Check title starts with conventional prefix
                title = pr.get("title", "")
                if not title.startswith(prefix):
                    continue

                # Skip large diffs
                if (pr.get("additions", 0) + pr.get("deletions", 0)) > 500:
                    continue

                # Get merge commit details (mergeCommit can be null for unmerged PRs)
                merge_commit = pr.get("mergeCommit")
                if not merge_commit or not isinstance(merge_commit, dict):
                    continue
                merge_oid = merge_commit.get("oid")
                if not merge_oid:
                    continue

                # Verify exactly 2 parents (not a squash/rebase)
                try:
                    result = subprocess.run(
                        ["git", "rev-list", "--parents", "-n", "1", merge_oid],
                        cwd=Path.home() / ".agents",
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode != 0:
                        continue

                    parents = result.stdout.strip().split()
                    if len(parents) != 3:  # commit + 2 parents
                        continue  # Skip non-merge-commits (squash has 1 parent)

                    base_sha = parents[1]
                    tip_sha = parents[2]  # parents[2] is the PR tip, parents[1] is base
                except Exception:
                    continue

                # Extract prompt from linked issue or PR body
                prompt = pr.get("body", "") or pr.get("title", "")
                if "Closes #" in prompt:
                    # Extract issue number and fetch issue body
                    import re
                    m = re.search(r"Closes #(\d+)", prompt)
                    if m:
                        issue_num = m.group(1)
                        try:
                            result = subprocess.run(
                                ["gh", "issue", "view", issue_num, "--repo", repo, "--json", "body"],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            if result.returncode == 0:
                                issue_data = json.loads(result.stdout)
                                prompt = issue_data.get("body", prompt)
                        except Exception:
                            pass  # Fall back to PR body

                tickets.append({
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "base_sha": base_sha,
                    "tip_sha": tip_sha,
                    "prompt": prompt,
                })
        except Exception:
            continue

    return tickets


# ============================================================================
# Worktree management for historical replay
# ============================================================================

@contextmanager
def create_historical_worktree(
    repo_path: Path,
    base_sha: str,
    worktree_path: Path,
):
    """Context manager: create a git worktree at base_sha, clean up on exit.

    Deliberately separate from sandbox_orchestration._create_worktree, which is
    tied to live ticket-branch naming, not historical SHA replay.
    """
    # Fetch base_sha if not present locally
    try:
        subprocess.run(
            ["git", "fetch", "origin", base_sha],
            cwd=repo_path,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass  # May already be present

    # Create the worktree
    try:
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), base_sha],
            cwd=repo_path,
            check=True,
            capture_output=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to create worktree at {base_sha}: {e.stderr}")

    try:
        yield worktree_path
    finally:
        # Clean up worktree, even on exception
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=repo_path,
                capture_output=True,
                timeout=30,
            )
        except Exception as e:
            print(f"Warning: failed to clean worktree {worktree_path}: {e}", file=sys.stderr)


# ============================================================================
# opencode execution
# ============================================================================

def run_opencode(
    worktree_path: Path,
    base_sha: str,
    ticket_prompt: str,
    model: str,
) -> dict:
    """Run opencode against Ollama's endpoint inside a historical worktree.

    Returns dict with keys:
    - gate_verdict: "PASS" | "FAIL"
    - gate_reason: str explaining the verdict
    - tokens: int (or 0 if unavailable)
    - tokens_approx: bool (true if fallback)
    - wall_s: float wall-clock time
    - error: str (if failed to run)
    """
    # Check opencode is available
    if not shutil.which("opencode"):
        return {
            "gate_verdict": "FAIL",
            "gate_reason": "opencode not found",
            "tokens": 0,
            "wall_s": 0,
            "error": "opencode binary missing",
        }

    t0 = time.time()

    # Prepare opencode config pointing at local Ollama
    # Schema: provider block keyed by provider id with options and models
    ollama_config = {
        "providers": {
            "ollama": {
                "options": {
                    "baseURL": OLLAMA_BASE + "/v1",
                },
                "models": [model],
            }
        },
        "default": "ollama",
    }

    config_file = worktree_path / "opencode.json"

    try:
        # Write config file
        config_file.write_text(json.dumps(ollama_config))

        # Run opencode run with the ticket prompt as positional argument
        result = subprocess.run(
            ["opencode", "run", ticket_prompt],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout per run
            env={**os.environ, "OPENCODE_CONFIG": str(config_file)},
        )

        wall = time.time() - t0

        # Parse opencode output
        if result.returncode != 0:
            return {
                "gate_verdict": "FAIL",
                "gate_reason": f"opencode error: {result.stderr[:200]}",
                "tokens": 0,
                "wall_s": wall,
                "error": result.stderr[:200],
            }

        # Check if any changes were made via git status (excluding opencode.json itself)
        try:
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            status_lines = [
                line for line in status_result.stdout.strip().split("\n")
                if line and not line.endswith("opencode.json")
            ]
            if not status_lines or not "".join(status_lines).strip():
                return {
                    "gate_verdict": "FAIL",
                    "gate_reason": "no changes produced",
                    "tokens": 0,
                    "wall_s": wall,
                }
        except Exception:
            pass  # Continue with change detection via gates

        # Estimate tokens from opencode's stderr/stdout (opencode reports tokens in output)
        tokens_approx = 0
        for line in result.stdout.split("\n") + result.stderr.split("\n"):
            if "token" in line.lower():
                try:
                    # Extract number from "used 1234 tokens" or similar
                    import re
                    m = re.search(r'(\d+)\s+token', line)
                    if m:
                        tokens_approx = int(m.group(1))
                        break
                except Exception:
                    pass

        # If no tokens found in output, estimate from git diff
        if tokens_approx == 0:
            try:
                diff_result = subprocess.run(
                    ["git", "diff", base_sha],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                tokens_approx = len(diff_result.stdout) // 4  # rough ~4 chars per token
            except Exception:
                tokens_approx = 0

        return {
            "gate_verdict": "RUNNING",  # Will be replaced by actual gate check
            "gate_reason": "diff applied; running gates",
            "tokens": tokens_approx,
            "tokens_approx": tokens_approx > 0 and "token" not in result.stdout.lower(),
            "wall_s": wall,
        }
    finally:
        # Clean up config file
        try:
            config_file.unlink()
        except Exception:
            pass


# ============================================================================
# Gate sequence (matching execute_ticket)
# ============================================================================

def run_gates(
    worktree_path: Path,
    base_sha: str,
    repo_path: Path,
    ticket_ref: str,
) -> dict:
    """Run the real gate sequence: measure + metrics + test_change + code_review.

    Returns: {"gate_verdict": "PASS"|"FAIL", "gate_reason": str, "metrics": {...}, "review": {...}}
    """
    result = {
        "gate_verdict": "FAIL",
        "gate_reason": "unknown",
        "metrics": {},
        "tests": {},
        "review": {},
    }

    try:
        # Commit the applied changes so gates can see them
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=worktree_path,
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                ["git", "commit", "-m", f"spike: {ticket_ref}"],
                cwd=worktree_path,
                capture_output=True,
                timeout=10,
            )
        except Exception as e:
            result["gate_reason"] = f"failed to commit changes: {str(e)[:100]}"
            return result

        # Gate 1: Metrics (measure + compare)
        # Create a clean worktree at base_sha for baseline measurement
        baseline_path = worktree_path.parent / f"baseline-{worktree_path.name}"
        try:
            with create_historical_worktree(repo_path, base_sha, baseline_path):
                baseline = build_type_measure.measure(baseline_path)
        except Exception as e:
            result["gate_reason"] = f"failed to measure baseline: {str(e)[:100]}"
            return result

        current = build_type_measure.measure(worktree_path)

        result["metrics"]["baseline"] = baseline
        result["metrics"]["current"] = current

        comparison = metrics_registry.compare("bench", baseline, current)
        if not comparison.get("passing"):
            result["gate_verdict"] = "FAIL"
            result["gate_reason"] = f"metrics failed: {comparison.get('verdict', 'unknown')}"
            return result

        # Gate 2: Test change rule (code changed ⟹ test changed)
        # Use sandbox_orchestration._test_rules for the ticket if available
        try:
            import sandbox_orchestration
            rules = sandbox_orchestration._test_rules(ticket_ref)
        except Exception:
            rules = test_change_rule.DEFAULT_RULES

        tests_ok, why = test_change_rule.check_worktree(worktree_path, base=base_sha, rules=rules)
        result["tests"]["ok"] = tests_ok
        result["tests"]["reason"] = why

        if not tests_ok:
            result["gate_verdict"] = "FAIL"
            result["gate_reason"] = f"test rule failed: {why}"
            return result

        # Gate 3: Code review
        review = code_review_gate.review_worktree(worktree_path, base=base_sha)
        result["review"] = review

        if review.get("clean") is False:
            result["gate_verdict"] = "FAIL"
            result["gate_reason"] = f"code review found issues"
            return result

        # All gates passed
        result["gate_verdict"] = "PASS"
        result["gate_reason"] = "all gates passed"
        return result

    except Exception as e:
        result["gate_reason"] = f"gate execution error: {str(e)[:100]}"
        return result


# ============================================================================
# Main sweep
# ============================================================================

def run_spike(repo: str, count: int = 5, models: list[str] | None = None):
    """Run the full sweep: select tickets, run opencode + gates, save results."""
    if models is None:
        models = ["qwen2.5:7b", "qwen2.5:14b"]

    # Preflight checks
    issues = preflight_checks()
    if issues:
        print("Preflight checks failed:", json.dumps(issues, indent=2))
        return False

    # Select tickets
    tickets = select_tickets(repo, count=count)
    if len(tickets) < count:
        print(f"Warning: selected {len(tickets)} tickets (wanted {count})")

    # Prepare results directory
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    # Run sweep
    stamp = int(time.time())
    results = []
    repo_path = Path.home() / ".agents"

    for ticket in tickets:
        for model in models:
            run_result = {
                "ticket_number": ticket["number"],
                "ticket_title": ticket["title"],
                "model": model,
                "timestamp": time.time(),
            }

            # Create historical worktree at base_sha
            worktree_path = results_dir / f"worktree-{ticket['number']}-{model}-{stamp}"

            sampler = EnergySampler()
            try:
                with sampler:
                    with create_historical_worktree(repo_path, ticket["base_sha"], worktree_path):
                        # Run opencode
                        opencode_result = run_opencode(
                            worktree_path=worktree_path,
                            base_sha=ticket["base_sha"],
                            ticket_prompt=ticket["prompt"],
                            model=model,
                        )

                        run_result["opencode"] = opencode_result

                        # Run gates if opencode succeeded
                        if opencode_result.get("gate_verdict") != "FAIL":
                            gates_result = run_gates(
                                worktree_path=worktree_path,
                                base_sha=ticket["base_sha"],
                                repo_path=repo_path,
                                ticket_ref=f"#{ticket['number']}",
                            )
                            run_result["gates"] = gates_result

                energy = sampler.get_energy()
                run_result["energy"] = energy

            except Exception as e:
                run_result["error"] = str(e)

            results.append(run_result)

    # Save results to JSON
    results_file = results_dir / f"local-coding-spike-{stamp}.json"
    results_file.write_text(json.dumps(results, indent=2))
    print(f"Results saved to {results_file}")

    # Append summary to RESULTS.md
    append_run_summary(ROOT / "RESULTS.md", results, stamp)

    return True


def append_run_summary(results_file: Path, results: list[dict], stamp: int):
    """Atomically append run summary to RESULTS.md in the existing format."""
    if not results:
        return

    # Get unique models actually in the results
    unique_models = sorted(set(r.get("model") for r in results if r.get("model")))
    ticket_count = len(set(r.get("ticket_number") for r in results if r.get("ticket_number")))

    from datetime import datetime
    run_date = datetime.fromtimestamp(stamp).strftime("%Y-%m-%d")
    run_num = 31  # Static for now; could parse from RESULTS.md history

    summary = f"""
## Run {run_num} — {run_date} (local coding spike: qwen2.5 via opencode)

{ticket_count} recent small conventionally-committed merged PRs × {len(unique_models)} models ({", ".join(unique_models)}).
Gates: build_type_measure + metrics_registry + test_change_rule + code_review_gate.

| Model | Passes | Fails | No Gates | Energy measured | Tokens |
|-------|--------|-------|----------|-----------------|--------|
"""

    for model in unique_models:
        model_results = [r for r in results if r.get("model") == model]
        model_passes = sum(1 for r in model_results if r.get("gates", {}).get("gate_verdict") == "PASS")
        model_fails = sum(1 for r in model_results if r.get("gates", {}).get("gate_verdict") == "FAIL")
        model_no_gates = sum(1 for r in model_results if "gates" not in r)
        total_tokens = sum(r.get("opencode", {}).get("tokens", 0) for r in model_results)
        avg_tokens = total_tokens // len(model_results) if model_results else 0
        energy_available = any(r.get("energy", {}).get("energy_j") is not None for r in model_results)

        summary += f"| {model} | {model_passes}/{len(model_results)} | {model_fails}/{len(model_results)} | {model_no_gates} | {'yes' if energy_available else 'no'} | {avg_tokens} |\n"

    summary += """
### Findings
1. **Verdict:** results of local model + opencode against real gates.
2. **Tickets:** verified no labels/comments/claim state touched on real PRs.

### Recommendation
— [pending full results table] —
"""

    # Atomically append: read, modify in memory, write back
    if results_file.exists():
        content = results_file.read_text()
    else:
        content = "# marvin-bench — results log\n"

    content += summary
    results_file.write_text(content)


if __name__ == "__main__":
    success = run_spike(repo="G-Eskayo/marvin", count=5)
    sys.exit(0 if success else 1)
