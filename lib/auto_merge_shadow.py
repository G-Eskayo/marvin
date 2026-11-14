#!/usr/bin/env python3
"""auto_merge_shadow.py — auto-merge's shadow mode, its 3-day report, and switch-on only on Gil's yes (ADR 0064, #341).

Until Gil switches auto-merge on, nothing merges by itself. Every hour (with the scanner, on the mini) each open PR gets
the verdict auto-merge WOULD give it: the policy (auto_merge_policy.py), the project's trust ramp (trust_ramp.py) and
a mutation score of at least 80 % (ADR 0063, #339; no score yet = wait). The first verdict a PR gets is kept, and what
Gil then did with it (merged, closed, reverted) is recorded. A PR by a ramp author (mac-mini-2012's bot, ADR 0069
rule 5) also needs that author's own ramp open; each run records the author's closed PRs into it (#952).

Scoring is multi-PR with a 480-second budget per run (8 min headroom in the hourly slot for other tasks). Failed scores
are logged (error_log), stated in each PR's body, and parked in backoff after 5 consecutive failures; backoff PRs are
skipped in subsequent runs until their retry window opens (ticket_policy.retry_backoff_s).

After SHADOW_DAYS the report says how many PRs it would have merged and lists every one Gil closed or reverted (a
disagreement). The report reaches Gil in the session-start report, the morning brief and an MR Review banner.
Switch-on: only by Gil (`switch-on`), only once the report is ready, and only with no disagreements.

State: ~/.claude/logs/auto-merge-shadow.json on the mini. Missing = a fresh start; corrupt = shadow, never on, and not
overwritten.

    auto_merge_shadow.py run             verdicts for every open PR (hourly)
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
OWNER = "G-Eskayo"          # whose merge or Approve counts as a clean approval for an author ramp
_SCORE = re.compile(r"mutation\s+score[^0-9\n]{0,20}(\d{1,3})\s*%|\*\*score:\*\*\s*(\d{1,3})\s*%", re.I)
SCAN_BUDGET_SEC = 480       # hourly run headroom: 8 minutes per scan, plus reporter/other tasks
MAX_SCORE_FAILURES = 5      # like run_ticket.MAX_CONSECUTIVE_RETRIES: park after this many failures


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
                   author=pr.get("author"), author_ramp_open=facts.get("author_ramp_open", False),
                   author_ramp_streak=facts.get("author_ramp_streak"))
    reasons = list(d["reasons"]) if d["verdict"] == "ask" else []
    score = mutation_score(pr.get("body", ""))
    if score is None:
        reasons.append("mutation score pending (its tests haven't been checked by planting bugs yet, #339)")
    elif score < MIN_SCORE:
        reasons.append(f"its tests caught {score}% of planted bugs; auto-merge needs {MIN_SCORE}%")
    return {"verdict": "ask" if reasons else "auto", "reasons": reasons or d["reasons"], "score": score}


def _classify_failure(exc: Exception) -> dict:
    """Thin wrapper over error_log.classify() to extract failure cause."""
    import error_log
    return error_log.classify(str(exc))


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


def last_scan(path: Path = STATE_PATH) -> dict | None:
    """The last _score_many() summary, or None if not yet available."""
    st = _read(path)
    return st.get("last_scan") if st else None


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


# ── the bot's own trust ramp (ADR 0069 rule 5, #952) ────────────────────────

def ramp_event(view: dict, owner: str = OWNER) -> str | None:
    """A closed PR as an author-ramp event. Merged by the owner (the dashboard's Approve merges as him and leaves no
    GitHub review) or merged with the owner's latest decisive review an APPROVED -> "approved-merge"; merged any other
    way -> "manual-merge" (counts for nothing); closed unmerged -> "deny"; still open or unknown -> None."""
    state = (view or {}).get("state")
    if state == "CLOSED":
        return "deny"
    if state != "MERGED":
        return None
    me = owner.lower()
    if ((view.get("mergedBy") or {}).get("login") or "").lower() == me:
        return "approved-merge"
    decisive = [r.get("state") for r in view.get("reviews") or []
                if ((r.get("author") or {}).get("login") or "").lower() == me and r.get("state") in ("APPROVED", "CHANGES_REQUESTED")]
    return "approved-merge" if decisive and decisive[-1] == "APPROVED" else "manual-merge"


def _ramp_authors(rules: dict) -> list[str]:
    a = rules.get("ramp_authors") if isinstance(rules, dict) else None
    return [x for x in a if isinstance(x, str)] if isinstance(a, list) else []


def author_facts(facts: dict, pr: dict, rules: dict, ramp_path: Path | None = None) -> dict:
    """`facts` plus the PR author's ramp (open and streak); a copy, the shared facts aren't changed."""
    import trust_ramp
    path = ramp_path or trust_ramp.STATE_PATH
    login = pr.get("author") or ""
    if login.strip().lower() not in {a.lower() for a in _ramp_authors(rules)}:
        return {**facts, "author_ramp_open": False, "author_ramp_streak": None}
    login = login.strip()
    return {**facts, "author_ramp_open": trust_ramp.author_is_open(login, path=path),
            "author_ramp_streak": trust_ramp.author_streak(login, path=path)}


def record_author_ramps(repo: str, rules: dict, gh=None, ramp_path: Path | None = None, limit: int = 50) -> list[tuple]:
    """Record each ramp author's recently closed PRs in `repo` into its own ramp, oldest first (repeats count once, so
    every hourly run can look at the same PRs again). A PR whose author isn't exactly that login is skipped, whatever
    its labels. Best effort: GitHub or a corrupt ramp file never break the shadow run. Returns what was recorded."""
    import trust_ramp
    gh = gh or _gh
    path = ramp_path or trust_ramp.STATE_PATH
    done = []
    for login in _ramp_authors(rules):
        try:
            prs = json.loads(gh(["pr", "list", "--repo", repo, "--state", "closed", "--author", login, "--limit",
                                 str(limit), "--json", "number,state,author,mergedBy,reviews,closedAt"]))
            prs = sorted((p for p in prs if isinstance(p, dict)), key=lambda p: (p.get("closedAt") or "", p.get("number") or 0))
            for p in prs:
                if ((p.get("author") or {}).get("login") or "").lower() != login.lower():
                    continue
                event = ramp_event(p)
                if event is None:
                    continue
                trust_ramp.record_author(login, p["number"], event, path=path, repo=repo,
                                         reason=f"{repo}#{p['number']} {event}")
                done.append((login, p["number"], event))
        except Exception as e:  # noqa: BLE001 -- try again next hour; never break the shadow run
            print(f"auto-merge shadow: recording {login}'s trust ramp failed: {e}", file=sys.stderr)
    return done


# ── the hourly run (real GitHub and git; on the mini) ───────────────────────

def _gh(args):
    import subprocess
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from project_catalog import run_env
    # It only adds its mutation section to a PR someone else wrote; whether that PR names its ticket is the author's
    # rule to meet (lib/pr_ticket_check.py, marvin#1004), not a reason to fail the scoring.
    env = {**run_env(), "MARVIN_NO_TICKET": "shadow mutation score: adds a section to an existing PR body"}
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=60, env=env).stdout


def _score_one_pr(pr: dict, repo: str, path: Path) -> dict:
    """Score one PR with the mutation check in a scratch worktree and write to its body. Always returns a result dict,
    never raises. On error, logs to error_log and returns a synthetic result with the cause."""
    import subprocess
    import tempfile
    import error_log
    import disk_ledger
    t0 = time.time()
    try:
        import mutation_check as mc
        mc.render_section, mc.merge_bodies                       # the reviewed engine (PR #351)
    except (ImportError, AttributeError):
        return {"status": "unknown", "number": pr.get("number", "?"), "reason": "mutation_check not installed"}
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
        elapsed = time.time() - t0
        disk_used = disk_ledger.du_kb(scratch)
        return {"status": "scored", "number": pr["number"], "headRefOid": pr["headRefOid"], "elapsed_sec": elapsed, "disk_kb": disk_used}
    except Exception as e:  # noqa: BLE001
        elapsed = time.time() - t0
        try:
            classified = _classify_failure(e)
            cause = classified.get("cause", "unknown error")
        except Exception:  # noqa: BLE001 -- _classify_failure should not raise, but guard it anyway
            cause = "unknown error"
        try:
            error_log.record(source="auto_merge_shadow", message=f"scoring PR #{pr.get('number', '?')} failed: {cause}", raw=str(e))
        except Exception:  # noqa: BLE001 -- error_log.record is guarded internally, but guard again here
            pass
        try:
            body = mc.merge_bodies(pr.get("body") or "", mc.render_section({"reason": cause, "status": "unknown"}))
            _gh(["pr", "edit", pr["url"], "--body", body])
        except Exception as write_err:  # noqa: BLE001 -- don't let a write error mask the original failure
            try:
                error_log.record(source="auto_merge_shadow", message=f"failed to update PR #{pr.get('number', '?')} body", raw=str(write_err))
            except Exception:  # noqa: BLE001
                pass
        try:
            disk_used = disk_ledger.du_kb(scratch)
        except Exception:  # noqa: BLE001 -- disk_ledger.du_kb should not raise, but guard it
            disk_used = 0
        return {"status": "unknown", "number": pr.get("number", "?"), "reason": cause, "elapsed_sec": elapsed, "disk_kb": disk_used}
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(scratch)], cwd=clone, capture_output=True, timeout=60)


def _score_one(prs: list[dict], repo: str, path: Path) -> None:
    """Deprecated: use _score_many. Kept for backward compatibility."""
    st = _read(path) or {}
    pr = pick_unscored(prs, st.get("scored", {}))
    if pr is None:
        return
    result = _score_one_pr(pr, repo, path)
    if result["status"] == "scored":
        with _Locked(path) as s2:
            s2.setdefault("scored", {})[pr["url"]] = pr["headRefOid"]


def _score_many(prs: list[dict], repo: str, path: Path, budget_sec: int = SCAN_BUDGET_SEC, now: float | None = None) -> dict:
    """Score multiple PRs within a budget, with backoff and error logging. Always returns a summary dict, never raises.

    Each unscored PR (oldest first by number) is run through _score_one_pr. PRs in backoff (not_before > now) are
    skipped without consuming budget or being marked scored. A parked PR that receives a new push (different headRefOid)
    is immediately revived (backoff is cleared, failure counter resets). After MAX_SCORE_FAILURES (5) consecutive
    failures, a PR is parked: not_before is set to now + retry_backoff_s(MAX_SCORE_FAILURES) seconds (~4 hours),
    and the PR is not retried until that window passes. Failures are logged to error_log and written to each PR's body.

    Returns: {'scored': N successfully scored this run, 'failed': N still failing and parked/backing off,
              'elapsed_sec': wall time spent on all attempts, 'disk_kb': total disk used by worktrees}.

    Worst case time: budget_sec + overhead for final worktree cleanup (~2 sec per PR, ~60 sec total if budget expires
    mid-attempt). Disk: one worktree per attempt, cleaned up immediately; typical 200-500 KB per check."""
    import ticket_policy
    now = now or time.time()
    t0 = time.time()
    scored_this_run = 0
    failed_this_run = 0
    elapsed = 0.0
    disk = 0
    failed_in_this_run = set()  # mask failed PRs for the rest of this run

    st = _read(path) or {}
    scored_state = st.get("scored", {})
    failures_state = st.get("scoring_failures", {})

    while True:
        # Stop if budget is exhausted
        elapsed_so_far = time.time() - t0
        if elapsed_so_far >= budget_sec:
            break

        # Revive parked PRs that got a new push; exclude backoff PRs and failures from this run
        backoff_urls = set()
        revived_urls = set()
        for url, entry in failures_state.items():
            if isinstance(entry, dict):
                last_oid = entry.get("headRefOid")
                # Find current PR to check for new push
                current_pr = next((p for p in prs if p["url"] == url), None)
                if current_pr and last_oid and last_oid != current_pr.get("headRefOid"):
                    # New push revives a parked PR
                    revived_urls.add(url)
                elif entry.get("not_before", 0) > now:
                    backoff_urls.add(url)

        # Remove revived PRs from failure state
        for url in revived_urls:
            failures_state.pop(url, None)

        excluded_urls = (backoff_urls | failed_in_this_run) - revived_urls
        in_memory_scored = {**scored_state}
        # Mask all excluded URLs by marking them as scored at their current oid
        for p in prs:
            if p["url"] in excluded_urls:
                in_memory_scored[p["url"]] = p.get("headRefOid")

        pr = pick_unscored(prs, in_memory_scored)
        if pr is None:
            break

        result = _score_one_pr(pr, repo, path)
        elapsed += result.get("elapsed_sec", 0)
        disk_cost = result.get("disk_kb", 0)
        # disk_cost can be a string sentinel ("not measured ...") from disk_ledger
        if isinstance(disk_cost, (int, float)) and disk_cost >= 0:
            disk += disk_cost

        with _Locked(path) as state:
            if result["status"] == "scored":
                state.setdefault("scored", {})[pr["url"]] = pr["headRefOid"]
                state.get("scoring_failures", {}).pop(pr["url"], None)
                scored_state[pr["url"]] = pr["headRefOid"]
                scored_this_run += 1
            else:
                # Fetch fresh state to get the current failure count and headRefOid
                current_entry = (state.get("scoring_failures", {}).get(pr["url"], {}) or {})
                last_oid = current_entry.get("headRefOid")
                current_oid = pr["headRefOid"]
                # New push resets the counter
                if last_oid != current_oid:
                    fail_count = 1
                else:
                    fail_count = current_entry.get("count", 0) + 1
                if fail_count >= MAX_SCORE_FAILURES:
                    backoff_sec = ticket_policy.retry_backoff_s(MAX_SCORE_FAILURES)
                    not_before = now + backoff_sec
                    state.setdefault("scoring_failures", {})[pr["url"]] = {"count": fail_count, "headRefOid": current_oid,
                                                                             "not_before": not_before,
                                                                             "reason": result.get("reason", "unknown error")}
                    failed_this_run += 1
                    failures_state[pr["url"]] = {"count": fail_count, "not_before": not_before}
                else:
                    state.setdefault("scoring_failures", {})[pr["url"]] = {"count": fail_count, "headRefOid": current_oid,
                                                                             "reason": result.get("reason", "unknown error")}
                    failed_this_run += 1
                    failed_in_this_run.add(pr["url"])  # Mask it for the rest of this run
                    failures_state[pr["url"]] = {"count": fail_count}

    return {"scored": scored_this_run, "failed": failed_this_run, "elapsed_sec": elapsed, "disk_kb": disk}


def run(repo: str = "G-Eskayo/marvin", path: Path = STATE_PATH) -> list[dict]:
    """Verdicts for every open PR in `repo`, and the outcome of PRs that closed since. Best effort."""
    import subprocess
    import trust_ramp
    prs = json.loads(_gh(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100",
                          "--json", "number,url,title,body,files,headRefName,headRefOid,author"]))
    scan_summary = _score_many(prs, repo, path)
    clone = Path.home() / ".agents"
    tops = {l for l in subprocess.run(["git", "ls-tree", "--name-only", "-d", "origin/main"], cwd=clone,
                                      capture_output=True, text=True).stdout.split()}
    rules = amp.load_rules()
    record_author_ramps(repo, rules)
    facts = {"existing_top_level": tops, "new_top_level_this_week": 0, "ramp_open": trust_ramp.is_open(repo),
             "render_check_passed": False}
    seen = observe([{"number": p["number"], "repo": repo, "url": p["url"], "title": p["title"], "body": p.get("body") or "",
                     "author": (p.get("author") or {}).get("login") or "",    # unreadable author: "" fails closed
                     "files": [{"path": f["path"], "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                                "status": "modified", "previous_path": None} for f in p.get("files", [])]} for p in prs],
                   lambda p: author_facts(facts, p, rules), path)
    st = _read(path) or {"prs": {}}
    open_urls = {p["url"] for p in prs}
    for url, e in st["prs"].items():
        if url not in open_urls and e.get("outcome") is None:
            state = json.loads(_gh(["pr", "view", url, "--json", "state"]))["state"]
            record_outcome(url, "merged" if state == "MERGED" else "closed", path)
    r = report(path)
    with _Locked(path) as st:                                # the dashboard and the morning brief read this
        st["last_report"] = r
        st["last_scan"] = scan_summary
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
