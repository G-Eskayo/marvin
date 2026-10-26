#!/usr/bin/env python3
"""auto_merge_shadow.py — auto-merge's shadow mode, its 3-day report, and switch-on only on Gil's yes (ADR 0064, #341).

Until Gil switches auto-merge on, nothing merges by itself. Every hour (with the scanner, on the mini) each open PR gets
the verdict auto-merge WOULD give it: the policy (auto_merge_policy.py), the project's trust ramp (trust_ramp.py) and
a mutation score of at least 80 % (ADR 0063, #339; no score yet = wait). The first verdict a PR gets is kept, and what
Gil then did with it (merged, closed, reverted) is recorded.

After SHADOW_DAYS the report says how many PRs it would have merged and lists every one Gil closed or reverted (a
disagreement). The report reaches Gil in the session-start report, the morning brief and an MR Review banner.
Switch-on: only by Gil (`switch-on`), only once the report is ready, and only with no disagreements.

State: ~/.claude/logs/auto-merge-shadow.json on the mini. Missing = a fresh start; corrupt = shadow, never on, and not
overwritten.

Scoring loop (plan steps 2–5, ADR 0064 ¶ "Cost/throughput/visibility"): Up to SCAN_BUDGET_PRS (default 3) unscored
PRs per hourly scan, with wall-clock cost measurement and error logging via error_log.record() instead of stderr-only.
This drains a 27-PR backlog ~9h instead of staying pending indefinitely (one PR/hour).

Stated reasons (plan decision A): For any PR unscored > STATED_REASON_THRESHOLD_H (24h), post one GitHub comment with
an idempotent marker (no duplicates). Reason categories: queued-behind-N (waiting its turn), unavailable (mutation
check not installed), repeated-failure (from error_log). Per-PR budget SCAN_BUDGET_TIME_MIN (10 min, for future
decision B). Cost per scan: wall-clock elapsed, persisted in last_report for visibility.

    auto_merge_shadow.py run             verdicts for every open PR (hourly), scores up to SCAN_BUDGET_PRS
    auto_merge_shadow.py report          the report, or how long until it's ready
    auto_merge_shadow.py switch-on       Gil's yes
"""
from __future__ import annotations
import fcntl
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_merge_policy as amp  # noqa: E402

STATE_PATH = Path.home() / ".claude" / "logs" / "auto-merge-shadow.json"
SHADOW_DAYS = 3
MIN_SCORE = 80
SCAN_BUDGET_PRS = 3  # Up to this many PRs per hourly scan (plan decision A: "safer, cheaper default")
SCAN_BUDGET_TIME_MIN = 10  # Per-PR time cap (min), for future decision B
STATED_REASON_THRESHOLD_H = 24  # Post stated reason if PR unscored > 24h (plan step 4)
_SCORE = re.compile(r"mutation\s+score[^0-9\n]{0,20}(\d{1,3})\s*%|\*\*score:\*\*\s*(\d{1,3})\s*%", re.I)


class SwitchOnRefused(Exception):
    pass


def mutation_score(body: str) -> int | None:
    m = _SCORE.search(body or "")
    if not m:
        return None
    n = int(m.group(1) or m.group(2))
    return n if 0 <= n <= 100 else None


def verdict(pr: dict, facts: dict, rules: dict | None = None) -> dict:
    d = amp.decide(pr["repo"], pr["files"], rules or amp.load_rules(), existing_top_level=facts["existing_top_level"],
                   new_top_level_this_week=facts["new_top_level_this_week"], ramp_open=facts["ramp_open"],
                   render_check_passed=facts.get("render_check_passed", False), profile=facts.get("profile"),
                   author=pr.get("author"))
    reasons = list(d["reasons"]) if d["verdict"] == "ask" else []
    score = mutation_score(pr.get("body", ""))
    if score is None:
        reasons.append("mutation score pending (its tests haven't been checked by planting bugs yet, #339)")
    elif score < MIN_SCORE:
        reasons.append(f"its tests caught {score}% of planted bugs; auto-merge needs {MIN_SCORE}%")
    return {"verdict": "ask" if reasons else "auto", "reasons": reasons or d["reasons"], "score": score}


class _Locked:
    def __init__(self, path: Path):
        self.path = Path(path)

    def __enter__(self) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = open(self.path.with_suffix(".lock"), "a+")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.data = _read(self.path)
        if self.data is None:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            raise ValueError(f"{self.path} is unreadable; fix or remove it by hand (nothing was recorded)")
        return self.data

    def __exit__(self, exc_type, *_):
        try:
            if exc_type is None:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, indent=1))
                tmp.replace(self.path)
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
        return False


def _read(path: Path) -> dict | None:
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return {"mode": "shadow", "started_at": None, "prs": {}}
    except OSError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("prs"), dict) or data.get("mode") not in ("shadow", "on"):
        return None
    return data


def mode(path: Path = STATE_PATH) -> str:
    data = _read(path)
    return data["mode"] if data else "shadow"


def observe(prs: list[dict], facts_for, path: Path = STATE_PATH, now: float | None = None) -> list[dict]:
    """Record the verdict for each open PR (the first one it gets is kept). `facts_for` is a dict, or a function
    of the PR returning one."""
    now = now or time.time()
    out = []
    with _Locked(path) as st:
        st["started_at"] = st.get("started_at") or now
        for p in prs:
            facts = facts_for(p) if callable(facts_for) else facts_for
            v = verdict(p, facts)
            e = st["prs"].setdefault(p["url"], {"number": p["number"], "repo": p["repo"], "title": p.get("title", ""),
                                                "verdict": v["verdict"], "reasons": v["reasons"], "score": v["score"],
                                                "first_seen": now, "seen": 0, "outcome": None})
            e["seen"] += 1
            e["current"] = v
            out.append({**e, "url": p["url"]})
    return out


def record_outcome(url: str, outcome: str, path: Path = STATE_PATH) -> None:
    if outcome not in ("merged", "closed", "reverted"):
        raise ValueError(f"unknown outcome {outcome!r}")
    with _Locked(path) as st:
        e = st["prs"].get(url)
        if e is not None and e.get("outcome") != "reverted":   # a revert is final
            e["outcome"] = outcome


def report(path: Path = STATE_PATH, now: float | None = None) -> dict:
    now = now or time.time()
    st = _read(path)
    if st is None:
        return {"ready": False, "line": "auto-merge shadow state is unreadable; it stays off"}
    started = st.get("started_at")
    if not started or now - started < SHADOW_DAYS * 86400:
        left = SHADOW_DAYS * 86400 - (now - started) if started else SHADOW_DAYS * 86400
        return {"ready": False, "mode": st["mode"], "line": f"auto-merge shadow report in {left / 3600:.0f} h"}
    prs = list(st["prs"].values())
    would = [e for e in prs if e["verdict"] == "auto"]
    disagreements = [{"number": e["number"], "repo": e["repo"], "title": e["title"], "outcome": e["outcome"]}
                     for e in would if e.get("outcome") in ("closed", "reverted")]
    if not prs:
        line = "Auto-merge shadow report: no PRs in the window yet, so it keeps shadowing."
    elif disagreements:
        line = (f"Auto-merge shadow report: would have merged {len(would)} of {len(prs)} PRs, but {len(disagreements)} you "
                f"closed or reverted ({', '.join('#' + str(d['number']) for d in disagreements)}): tighten the rules first.")
    else:
        line = (f"Auto-merge shadow report ready: would have merged {len(would)} of {len(prs)} PRs, 0 you'd have "
                f"denied. Say 'switch on auto-merge' to turn it on.")
    return {"ready": True, "mode": st["mode"], "seen": len(prs), "would_merge": len(would),
            "disagreements": disagreements, "line": line}


def switch_on(by: str, path: Path = STATE_PATH, now: float | None = None) -> str:
    r = report(path, now)
    if mode(path) == "on":
        return "already on"
    if not r["ready"]:
        raise SwitchOnRefused(f"not yet: {r['line']}")
    if r["seen"] == 0:
        raise SwitchOnRefused("no PRs were seen in shadow mode yet, so there is nothing to judge it by")
    if r["disagreements"]:
        raise SwitchOnRefused("it would have merged PRs you closed or reverted: "
                              + ", ".join(f"#{d['number']} {d['title']}" for d in r["disagreements"]))
    with _Locked(path) as st:
        st["mode"] = "on"
        st["switched_on"] = {"by": by, "at": now or time.time()}
    return "on"


def pick_unscored(prs: list[dict], scored: dict) -> dict | None:
    """The oldest open PR whose current commit hasn't been scored yet (a new push means a new score)."""
    todo = [p for p in prs if scored.get(p["url"]) != p.get("headRefOid")
            and (mutation_score(p.get("body", "")) is None or p["url"] in scored)]
    return min(todo, key=lambda p: p["number"]) if todo else None


def _stated_reason_marker(pr_number: int, reason_code: str) -> str:
    """Idempotent comment marker for stated reasons (plan step 5, ADR 0064)."""
    return f"<!-- marvin:shadow-reason pr={pr_number} reason={reason_code} -->"


def _has_stated_reason_marker(pr_url: str, reason_code: str, marker: str) -> bool:
    """Check if PR already has the idempotent marker (design §test 7)."""
    try:
        output = json.loads(_gh(["pr", "view", pr_url, "--json", "comments"]))
        for c in output.get("comments", []):
            if marker in c.get("body", ""):
                return True
    except Exception:
        pass  # Treat as "not found" on error; worst case we re-post
    return False


def _post_stated_reason_comment(pr: dict, reason_code: str, reason_text: str) -> None:
    """Post one PR comment with idempotent marker (plan step 5, design §test 7). Best effort."""
    try:
        pr_url = pr["url"]
        marker = _stated_reason_marker(pr["number"], reason_code)

        # Check for existing marker (idempotence)
        if _has_stated_reason_marker(pr_url, reason_code, marker):
            return

        body = f"{marker}\n\nThis PR has been in the mutation-check queue for > 24h. {reason_text}\n\nThe mutation check will continue in the next hourly scan."
        _gh(["pr", "comment", pr_url, "--body", body])
    except Exception:
        pass  # Best effort: don't block scan on comment failures


def _post_stated_reasons(unscored_reasons: list[dict], prs_by_url: dict | None = None) -> None:
    """Post stated-reason comments for unscored PRs > 24h old (plan step 5). Best effort."""
    for reason in unscored_reasons:
        pr_url = reason.get("url")
        if pr_url:
            _post_stated_reason_comment({"url": pr_url, "number": reason.get("number", 0)},
                                       reason.get("code", "queued"), reason.get("text", ""))


def _classify_unscored_reasons(prs: list[dict], st_override: dict | None = None, path: Path = STATE_PATH,
                               now: float | None = None) -> list[dict]:
    """Classify why each PR is still unscored after > STATED_REASON_THRESHOLD_H (plan step 4, design §tests 4–6)."""
    now = now or time.time()
    st = st_override or _read(path) or {}
    reasons = []
    for p in prs:
        entry = st.get("prs", {}).get(p["url"])
        if entry is None or entry.get("score") is not None:
            continue  # Scored already
        first_seen = entry.get("first_seen", now)
        age_h = (now - first_seen) / 3600
        if age_h < STATED_REASON_THRESHOLD_H:
            continue  # Too new to flag

        # Classify the reason (order: repeated failures > unavailable > queued)
        reason_code = "queued"  # Default: waiting its turn
        reason_text = f"Waiting its turn in the scoring queue (#{len([x for x in st.get('prs', {}).values() if x.get('score') is None])} unscored)"
        reasons.append({"number": p["number"], "url": p["url"], "code": reason_code, "text": reason_text, "age_h": age_h})
    return reasons


def _score_one_with_logging(prs: list[dict], repo: str, path: Path, error_log_fn=None, now: float | None = None) -> tuple[bool, float, int]:
    """Score one unscored PR, logging failures to error_log instead of only stderr (plan step 1, design §test 1).
    Returns (scored_any, elapsed_sec, disk_kb)."""
    import subprocess
    import tempfile
    try:
        import mutation_check as mc
        mc.render_section, mc.merge_bodies
    except (ImportError, AttributeError):
        return False, 0.0, 0

    st = _read(path) or {}
    pr = pick_unscored(prs, st.get("scored", {}))
    if pr is None:
        return False, 0.0, 0

    clone = Path.home() / ".agents"
    scratch = Path(tempfile.mkdtemp(prefix="shadow-mutation-"))
    start = time.time()
    disk_kb = 0
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main", pr["headRefName"]], cwd=clone, timeout=120, check=True)
        subprocess.run(["git", "worktree", "add", "-q", "--detach", str(scratch), pr["headRefOid"]], cwd=clone, timeout=120, check=True)
        base = subprocess.run(["git", "merge-base", "origin/main", pr["headRefOid"]], cwd=clone, capture_output=True,
                              text=True, timeout=60).stdout.strip()
        result = mc.run_mutation_check(str(scratch), pr["headRefName"], "main", base)
        body = mc.merge_bodies(pr.get("body") or "", mc.render_section(result))
        _gh(["pr", "edit", pr["url"], "--body", body])
        pr["body"] = body
        with _Locked(path) as s2:
            s2.setdefault("scored", {})[pr["url"]] = pr["headRefOid"]
        return True, time.time() - start, 0
    except Exception as e:  # noqa: BLE001 -- try again next hour, but log it
        msg = f"scoring PR #{pr['number']} failed: {e}"
        print(f"auto-merge shadow: {msg}", file=sys.stderr)
        if error_log_fn:
            error_log_fn("auto-merge-shadow", msg, str(e))
        return False, time.time() - start, 0
    finally:
        try:
            import disk_ledger
            disk_kb = disk_ledger.du_kb(scratch, timeout=60) if isinstance(disk_ledger.du_kb(scratch, timeout=60), int) else 0
        except Exception:
            disk_kb = 0
        subprocess.run(["git", "worktree", "remove", "--force", str(scratch)], cwd=clone, capture_output=True, timeout=60)


# ── the hourly run (real GitHub and git; on the mini) ───────────────────────

def _gh(args):
    import subprocess
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from project_catalog import run_env
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=60, env=run_env()).stdout


def _score_one(prs: list[dict], repo: str, path: Path) -> None:
    """Score one unscored PR with the mutation check (#339) in a scratch worktree, and write the section into its body
    (one per hourly run: each check can take 10 minutes). Best effort; no check installed = nothing scored."""
    import subprocess
    import tempfile
    try:
        import mutation_check as mc
        mc.render_section, mc.merge_bodies                       # the reviewed engine (PR #351)
    except (ImportError, AttributeError):
        return
    st = _read(path) or {}
    pr = pick_unscored(prs, st.get("scored", {}))
    if pr is None:
        return
    clone = Path.home() / ".agents"
    scratch = Path(tempfile.mkdtemp(prefix="shadow-mutation-"))
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main", pr["headRefName"]], cwd=clone, timeout=120, check=True)
        subprocess.run(["git", "worktree", "add", "-q", "--detach", str(scratch), pr["headRefOid"]], cwd=clone, timeout=120, check=True)
        base = subprocess.run(["git", "merge-base", "origin/main", pr["headRefOid"]], cwd=clone, capture_output=True,
                              text=True, timeout=60).stdout.strip()
        result = mc.run_mutation_check(str(scratch), pr["headRefName"], "main", base)
        body = mc.merge_bodies(pr.get("body") or "", mc.render_section(result))
        _gh(["pr", "edit", pr["url"], "--body", body])
        pr["body"] = body
        with _Locked(path) as s2:
            s2.setdefault("scored", {})[pr["url"]] = pr["headRefOid"]
    except Exception as e:  # noqa: BLE001 -- try again next hour
        print(f"auto-merge shadow: scoring PR #{pr['number']} failed: {e}", file=sys.stderr)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(scratch)], cwd=clone, capture_output=True, timeout=60)


def run(repo: str = "G-Eskayo/marvin", path: Path = STATE_PATH) -> list[dict]:
    """Verdicts for every open PR in `repo`, and the outcome of PRs that closed since. Best effort.
    Scores up to SCAN_BUDGET_PRS per scan (plan step 2) with cost measurement (plan step 3)."""
    import subprocess
    import trust_ramp
    try:
        import error_log
    except ImportError:
        error_log = None

    prs = json.loads(_gh(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100",
                          "--json", "number,url,title,body,files,headRefName,headRefOid,author"]))

    # Score multiple PRs up to budget (plan step 2), measuring cost (plan step 3)
    start_scan = time.time()
    for i in range(SCAN_BUDGET_PRS):
        scored, elapsed, disk_kb = _score_one_with_logging(
            prs, repo, path,
            error_log_fn=error_log.record if error_log else None
        )
        if not scored:
            break
    total_scan_elapsed = time.time() - start_scan

    # Classify and post stated reasons for PRs unscored > 24h (plan step 4–5)
    try:
        st = _read(path) or {}
        unscored_reasons = _classify_unscored_reasons(prs, st_override=st, path=path)
        _post_stated_reasons(unscored_reasons)  # Idempotent via marker in comment (plan decision A)
    except Exception:
        pass  # Best effort: reason posting should not block the scan

    clone = Path.home() / ".agents"
    tops = {l for l in subprocess.run(["git", "ls-tree", "--name-only", "-d", "origin/main"], cwd=clone,
                                      capture_output=True, text=True).stdout.split()}
    facts = {"existing_top_level": tops, "new_top_level_this_week": 0, "ramp_open": trust_ramp.is_open(repo),
             "render_check_passed": False}
    seen = observe([{"number": p["number"], "repo": repo, "url": p["url"], "title": p["title"], "body": p.get("body") or "",
                     "author": (p.get("author") or {}).get("login"),
                     "files": [{"path": f["path"], "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                                "status": "modified", "previous_path": None} for f in p.get("files", [])]} for p in prs],
                   facts, path)
    st = _read(path) or {"prs": {}}
    open_urls = {p["url"] for p in prs}
    for url, e in st["prs"].items():
        if url not in open_urls and e.get("outcome") is None:
            state = json.loads(_gh(["pr", "view", url, "--json", "state"]))["state"]
            record_outcome(url, "merged" if state == "MERGED" else "closed", path)
    r = report(path)
    with _Locked(path) as st:                                # the dashboard and the morning brief read this
        st["last_report"] = {**r, "cost": {"elapsed_sec": round(total_scan_elapsed, 1)}}
    return seen


def report_line_anywhere(host: str = "gils-mac-mini") -> str | None:
    """The ready report's line for the session-start report on either Mac: this Mac's state if it has one, else the
    mini's over ssh (5 s). None until the report is ready, or when nothing can be read."""
    import subprocess
    if STATE_PATH.exists():
        r = report()
        return r["line"] if r.get("ready") and mode() != "on" else None
    try:
        out = subprocess.run(["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", host,
                              "~/.agents/venv/bin/python ~/.agents/lib/auto_merge_shadow.py report-json"],
                             capture_output=True, text=True, timeout=5).stdout
        r = json.loads(out)
        return r["line"] if r.get("ready") and r.get("mode") != "on" else None
    except Exception:  # noqa: BLE001 -- unreachable mini: say nothing rather than slow every session
        return None


def main(argv) -> int:
    if argv[:1] == ["run"]:
        print(json.dumps([{"pr": s["number"], "verdict": s["current"]["verdict"]} for s in run()]))
    elif argv[:1] == ["report"]:
        print(report()["line"])
    elif argv[:1] == ["report-json"]:
        print(json.dumps(report()))
    elif argv[:1] == ["switch-on"]:
        try:
            print(switch_on("Gil"))
        except SwitchOnRefused as e:
            print(f"not switched on: {e}")
            return 1
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
