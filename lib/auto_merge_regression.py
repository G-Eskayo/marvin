#!/usr/bin/env python3
"""auto_merge_regression.py — rung 3's own merge: a fix for a regression of a known incident (ADR 0064 amendment,
2026-10-26), in shadow mode until the owner says yes.

The incident ladder (incident_ladder.py) queues a regressed incident for a pipeline build. That PR may merge without
the owner's Approve **even when it touches core areas** (the amendment covers known-incident regressions only), when
every one of these holds:

- its ticket is a watched incident that regressed (labels `watch` and `regression`);
- it adds a **regression test that fails before the fix and passes after** (checked here on real git: the PR's test
  files run against the base commit, then against the PR's head);
- its mutation score is at least 80 % (ADR 0063), main is green (main_health) and its checks pass;
- everything else ADR 0064's policy says still holds (no dependency change, size, plain paths, never finance-os); only
  the "is core" reasons are waived;
- at most one per incident per day, and the trust ramp is open (a revert resets it).

After it merges, the incident's probe is re-measured over the time since the merge (once POST_MERGE_WAIT_S has
passed); if it still trips, the merge is reverted (ADR 0064's revert path) and the ramp resets.

**Shadow mode** (now): nothing merges or reverts by itself. Each rung-3 PR gets the verdict it WOULD get, and after
the owner merges one, what the re-measure WOULD have done (keep or revert). The report reaches the owner through the
morning brief; switching on is ADR 0064's switch (auto_merge_shadow.switch_on), never this module.

State: ~/.claude/logs/auto-merge-regression.json, the same shape and lock as auto_merge_shadow's (its _Locked/_read).

    auto_merge_regression.py run      verdicts for open rung-3 PRs + post-merge re-measures (hourly, with the scan)
    auto_merge_regression.py report   the shadow report line
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_merge_policy as amp  # noqa: E402
import auto_merge_shadow as ams  # noqa: E402

STATE_PATH = Path.home() / ".claude" / "logs" / "auto-merge-regression.json"
POST_MERGE_WAIT_S = 2 * 3600
TEST_TIMEOUT_S = 900
_BRANCH = re.compile(r"^pipeline/(?:[\w.-]+/[\w.-]+#)?(\d{1,7})$")
_CLOSES = re.compile(r"^\s*Closes\s+(?:[\w.-]+/[\w.-]+)?#(\d{1,7})\b", re.I | re.M)


def incident_of(pr: dict) -> int | None:
    """The ticket a pipeline PR was built for: its pipeline/<n> branch, else its 'Closes #n' line."""
    m = _BRANCH.match(pr.get("headRefName") or "")
    if m:
        return int(m.group(1))
    m = _CLOSES.search(pr.get("body") or "")
    return int(m.group(1)) if m else None


# ── the failing-first regression test, on real git ─────────────────────────────────────────────────────────────

def _git(clone: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, timeout=timeout)


def _added_tests(clone: Path, base: str, head: str) -> list[str]:
    """Python test files the PR added or changed (fit_check.is_test), plain paths only."""
    import fit_check
    out = _git(clone, "diff", "--name-only", "--diff-filter=AM", f"{base}...{head}").stdout.split()
    return [p for p in out if p.endswith(".py") and fit_check.is_test(p) and amp._plain(p)]


def _pytest(tree: Path, tests: list[str], python: str = sys.executable, run=subprocess.run) -> int:
    import cleanup_sweep
    with cleanup_sweep.disposable_basetemp() as basetemp_args:
        try:
            return run([python, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests, *basetemp_args], cwd=tree,
                       capture_output=True, text=True, timeout=TEST_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            return -1


def regression_test_check(clone: Path, base: str, head: str, pytest=_pytest) -> dict:
    """{"ok", "failed_before", "passed_after", "tests", "why"}. Before = the base commit with only the PR's test files
    applied: they must run and FAIL (pytest exit 1; a collection error, exit 2, is not a failing test). After = the
    PR's head: they must pass (exit 0). Any doubt is not ok."""
    tests = _added_tests(Path(clone), base, head)
    res = {"ok": False, "failed_before": False, "passed_after": False, "tests": tests}
    if not tests:
        return {**res, "why": "the PR adds or changes no test file"}
    scratch = Path(tempfile.mkdtemp(prefix="regression-test-"))
    try:
        for tree, rev in ((scratch / "before", base), (scratch / "after", head)):
            if _git(Path(clone), "worktree", "add", "-q", "--detach", str(tree), rev).returncode != 0:
                return {**res, "why": f"couldn't check out {rev[:12]}"}
        if _git(scratch / "before", "checkout", head, "--", *tests).returncode != 0:
            return {**res, "why": "couldn't put the PR's tests onto the base commit"}
        before = pytest(scratch / "before", tests)
        after = pytest(scratch / "after", tests)
    finally:
        for tree in (scratch / "before", scratch / "after"):
            _git(Path(clone), "worktree", "remove", "--force", str(tree))
        subprocess.run(["rm", "-rf", str(scratch)], capture_output=True)
    res.update(failed_before=before == 1, passed_after=after == 0)
    res["ok"] = res["failed_before"] and res["passed_after"]
    res["why"] = ("fails before the fix and passes after" if res["ok"] else
                  "its tests pass on the code before the fix too, so they don't catch the regression" if before == 0 else
                  f"its tests couldn't run before the fix (pytest exit {before})" if before != 1 else
                  f"its tests don't pass after the fix (pytest exit {after})")
    return res


# ── the verdict ────────────────────────────────────────────────────────────────────────────────────────────────

def regression_rules(rules: dict) -> dict:
    """ADR 0064's rules with the core list narrowed to `known_incident_regressions.still_core` (the merge gate and
    auto-merge itself: a fix can never loosen the rules that let it merge). Without `core_ok: true`, or with a
    malformed section, the rules are unchanged (every core file still waits)."""
    sec = rules.get("known_incident_regressions") if isinstance(rules, dict) else None
    if not isinstance(sec, dict) or sec.get("core_ok") is not True or not isinstance(sec.get("still_core"), list) \
            or not sec["still_core"]:
        return rules
    return {**rules, "core": [str(c) for c in sec["still_core"]]}


def verdict(pr: dict, facts: dict, rules: dict | None = None) -> dict:
    """Would rung 3 merge this PR by itself? {"verdict": "auto" | "ask", "reasons": [...]}. `facts`: ticket_labels,
    regression_test (regression_test_check's result or None), main_green, checks_green, ramp_open,
    merged_today (rung-3 auto-merges of this incident today), existing_top_level."""
    rules = rules or amp.load_rules()
    reasons = []
    labels = set(facts.get("ticket_labels") or ())
    if not {"watch", "regression"} <= labels:
        reasons.append("its ticket isn't a regression of a watched incident (needs `watch` and `regression`)")
    d = amp.decide(pr["repo"], pr["files"], regression_rules(rules), existing_top_level=facts.get("existing_top_level", ()),
                   new_top_level_this_week=0, ramp_open=facts.get("ramp_open", False), author=pr.get("author"))
    if d["verdict"] == "ask":
        reasons += d["reasons"]
    rt = facts.get("regression_test")
    if not rt:
        reasons.append("its regression test hasn't been checked yet (fails before, passes after)")
    elif not rt.get("ok"):
        reasons.append(f"regression test: {rt.get('why')}")
    score = ams.mutation_score(pr.get("body", ""))
    if score is None:
        reasons.append("mutation score pending (#339)")
    elif score < ams.MIN_SCORE:
        reasons.append(f"its tests caught {score}% of planted bugs; it needs {ams.MIN_SCORE}%")
    if facts.get("main_green") is not True:
        reasons.append("main isn't green")
    if facts.get("checks_green") is not True:
        reasons.append("its checks aren't all passing")
    if not facts.get("ramp_open"):
        reasons.append("the trust ramp is closed (a revert or a denial reset it)")
    if facts.get("merged_today", 0) >= 1:
        reasons.append("a rung-3 fix for this incident already merged itself today")
    reasons = list(dict.fromkeys(reasons))
    return {"verdict": "ask" if reasons else "auto", "reasons": reasons or ["a tested fix for a known regression"]}


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def merged_today(state: dict, incident: int, now: float) -> int:
    """Rung-3 PRs for this incident that would have merged themselves today (the per-day cap)."""
    return sum(1 for e in state.get("prs", {}).values() if e.get("incident") == incident and e.get("verdict") == "auto"
               and e.get("would_merge_at") and _day(e["would_merge_at"]) == _day(now))


def observe(prs: list[dict], facts_for, path: Path = STATE_PATH, now: float | None = None) -> list[dict]:
    """Record the verdict for each open rung-3 PR. The verdict is re-taken while it is open (a new push can earn it);
    the first 'auto' is kept, with when it would have merged."""
    now = now or time.time()
    out = []
    with ams._Locked(path) as st:
        st["started_at"] = st.get("started_at") or now
        for p in prs:
            facts = {**facts_for(p), "merged_today": merged_today(st, p["incident"], now)}
            v = verdict(p, facts)
            e = st["prs"].setdefault(p["url"], {"number": p["number"], "repo": p["repo"], "incident": p["incident"],
                                                "title": p.get("title", ""), "verdict": "ask", "outcome": None})
            if e["verdict"] != "auto":
                e.update(verdict=v["verdict"], reasons=v["reasons"])
                if v["verdict"] == "auto":
                    e["would_merge_at"] = now
            e["current"] = v
            out.append({**e, "url": p["url"]})
    return out


def post_merge(path: Path, measure, merged_at_of, now: float | None = None) -> list[dict]:
    """For each rung-3 PR the owner merged in shadow mode: once POST_MERGE_WAIT_S has passed, re-measure its incident's
    probe over the time since the merge and record what auto-merge WOULD do: keep it, or revert it (ADR 0064's revert
    path) because the probe still trips. Recorded once; a probe that throws is tried next hour."""
    import purpose_metrics as pm
    now = now or time.time()
    done = []
    with ams._Locked(path) as st:
        for url, e in st["prs"].items():
            if e.get("outcome") != "merged" or "would_revert" in e or not e.get("probe"):
                continue
            merged_at = e.get("merged_at") or merged_at_of(url)
            if not merged_at:
                continue
            e["merged_at"] = merged_at
            if now - merged_at < POST_MERGE_WAIT_S:
                continue
            days = min(pm.PROBE_WINDOW_DAYS, (now - merged_at) / 86400)
            try:
                value, _per = measure(e["probe"], days)
            except Exception as exc:  # noqa: BLE001 -- measured again next hour
                e["post_merge_error"] = str(exc)[:200]
                continue
            spec = {"target": f"<= {pm.PROBES[e['probe']][1]:g}", "baseline": None}
            e.update(probe_after_merge=value, would_revert=not pm.met(spec, value), checked_at=now)
            done.append({**e, "url": url})
    return done


def report(path: Path = STATE_PATH) -> dict:
    st = ams._read(path)
    if st is None:
        return {"line": "rung-3 auto-merge shadow state is unreadable; it stays off", "seen": 0}
    prs = list(st["prs"].values())
    would = [e for e in prs if e["verdict"] == "auto"]
    reverts = [e for e in prs if e.get("would_revert")]
    denied = [e for e in would if e.get("outcome") == "closed"]
    if not prs:
        return {"line": None, "seen": 0}
    line = (f"Rung-3 auto-merge (shadow): {len(prs)} regression fix PR(s); it would have merged {len(would)}"
            + (f" ({', '.join('#' + str(e['number']) for e in would)})" if would else "")
            + (f", and reverted {len(reverts)} after the probe still tripped" if reverts else "")
            + (f"; you closed {len(denied)} it would have merged" if denied else "") + ".")
    return {"line": line, "seen": len(prs), "would_merge": len(would), "would_revert": len(reverts),
            "disagreements": len(denied)}


# ── the hourly run (real GitHub and git; on the Mac that runs the scan) ────────────────────────────────────────

def _checks_green(rollup) -> bool:
    return bool(rollup) and all((c.get("conclusion") or c.get("state")) in ("SUCCESS", "NEUTRAL", "SKIPPED")
                                for c in rollup if isinstance(c, dict))


def _main_green() -> bool:
    import main_health
    try:
        return json.loads(main_health.STATE.read_text()).get("ok") is True
    except (OSError, ValueError, AttributeError):
        return False


def run(repo: str | None = None, path: Path = STATE_PATH, gh=None) -> list[dict]:
    """Best effort. One regression-test check per hourly run (each runs tests twice), like the mutation scoring."""
    import instance
    import purpose_metrics as pm
    import trust_ramp
    repo = repo or instance.engine_repo()
    gh = gh or ams._gh
    clone = Path.home() / ".agents"
    prs = [p for p in json.loads(gh(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json",
                                     "number,url,title,body,files,headRefName,headRefOid,author,statusCheckRollup"]))
           if incident_of(p)]
    tested = (ams._read(path) or {}).get("tested", {})
    entries, checked = [], False
    for p in prs:
        issue = json.loads(gh(["issue", "view", str(incident_of(p)), "--repo", repo, "--json", "labels,body"]))
        labels = {l.get("name") for l in issue.get("labels") or []}
        if "watch" not in labels:
            continue
        spec = pm.parse(issue.get("body"))
        cached = tested.get(p["url"])
        if not cached or cached.get("sha") != p["headRefOid"]:
            cached = None
            if not checked:   # one per hourly run: each check runs the PR's tests twice
                checked = True
                _git(clone, "fetch", "-q", "origin", "main", p["headRefName"])
                base = _git(clone, "merge-base", "origin/main", p["headRefOid"]).stdout.strip()
                cached = {"sha": p["headRefOid"], **regression_test_check(clone, base, p["headRefOid"])}
                with ams._Locked(path) as s2:
                    s2.setdefault("tested", {})[p["url"]] = cached
        entries.append({"pr": p, "labels": labels, "test": cached, "probe": spec["measure"] if spec else None})
    tops = set(_git(clone, "ls-tree", "--name-only", "-d", "origin/main").stdout.split())
    main_green, ramp = _main_green(), trust_ramp.is_open(repo)
    by_url = {r["pr"]["url"]: r for r in entries}
    seen = observe([{"number": r["pr"]["number"], "repo": repo, "url": r["pr"]["url"], "title": r["pr"]["title"],
                     "incident": incident_of(r["pr"]), "body": r["pr"].get("body") or "",
                     "author": (r["pr"].get("author") or {}).get("login"),
                     "files": [{"path": f["path"], "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)}
                               for f in r["pr"].get("files", [])]} for r in entries],
                   lambda p: {"ticket_labels": by_url[p["url"]]["labels"], "regression_test": by_url[p["url"]]["test"],
                              "main_green": main_green, "checks_green": _checks_green(by_url[p["url"]]["pr"].get("statusCheckRollup")),
                              "ramp_open": ramp, "existing_top_level": tops}, path)
    with ams._Locked(path) as s3:
        for r in entries:
            s3["prs"][r["pr"]["url"]]["probe"] = r["probe"]
        open_urls = set(by_url)
        for url, e in s3["prs"].items():
            if url not in open_urls and e.get("outcome") is None:
                state = json.loads(gh(["pr", "view", url, "--json", "state,mergedAt"]))
                e["outcome"] = "merged" if state.get("state") == "MERGED" else "closed"
                if state.get("mergedAt"):
                    e["merged_at"] = datetime.fromisoformat(state["mergedAt"].replace("Z", "+00:00")).timestamp()
    post_merge(path, pm.measure_everywhere, lambda url: None)
    return seen


def main(argv) -> int:
    if argv[:1] == ["run"]:
        print(json.dumps([{"pr": s["number"], "verdict": s["current"]["verdict"]} for s in run()]))
    elif argv[:1] == ["report"]:
        print(report()["line"] or "no rung-3 PRs yet")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
