"""Tests for bin/gh (the GitHub gate). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_gh_gate.py -v
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "bin" / "gh"

loader = importlib.machinery.SourceFileLoader("gh_gate", str(GATE))
spec = importlib.util.spec_from_loader("gh_gate", loader)
gg = importlib.util.module_from_spec(spec)
loader.exec_module(gg)

NOW = 1_800_000_000.0


# ── what kind of refusal ────────────────────────────────────────────────────

def test_recognises_the_two_kinds_of_github_refusal():
    assert gg.classify_refusal("GraphQL: API rate limit already exceeded for user ID 1.") == "hourly"
    assert gg.classify_refusal("HTTP 403: API rate limit exceeded for user ID 1.") == "hourly"
    assert gg.classify_refusal("You have exceeded a secondary rate limit. Please wait a few minutes") == "burst"
    assert gg.classify_refusal("HTTP 429: Too Many Requests") == "burst"
    assert gg.classify_refusal("abuse detection mechanism") == "burst"
    assert gg.classify_refusal("Unknown JSON field: stateReason") is None
    assert gg.classify_refusal("") is None


# ── who is calling ──────────────────────────────────────────────────────────

def test_launchd_jobs_are_background_except_the_webhook_that_serves_clicks():
    assert gg.priority_of({"XPC_SERVICE_NAME": "com.marvin.ticket-pipeline"}) == "background"
    assert gg.priority_of({"XPC_SERVICE_NAME": "com.marvin.dashboard-webhook"}) == "interactive"
    assert gg.priority_of({"XPC_SERVICE_NAME": "application.com.marvin.metrics.123"}) == "interactive"
    assert gg.priority_of({}) == "interactive"
    assert gg.priority_of({"XPC_SERVICE_NAME": "com.marvin.ticket-pipeline", "MARVIN_GH_PRIORITY": "interactive"}) == "interactive"


# ── the decision ────────────────────────────────────────────────────────────

def test_nothing_wrong_means_go():
    assert gg.decide("background", {}, {"core": 0.9, "graphql": 0.9}, NOW) == ("go", 0)


def test_a_cooldown_defers_background_and_makes_interactive_wait_briefly_or_fail_clearly():
    st = {"cooldown_until": NOW + 10, "reason": "burst"}
    assert gg.decide("background", st, None, NOW)[0] == "defer"
    assert gg.decide("interactive", st, None, NOW) == ("wait", 10)
    long = {"cooldown_until": NOW + 600, "reason": "hourly"}
    assert gg.decide("interactive", long, None, NOW)[0] == "refuse"


def test_a_low_budget_holds_background_work_back_for_people():
    assert gg.decide("background", {}, {"core": 0.9, "graphql": 0.15}, NOW)[0] == "defer"
    assert gg.decide("interactive", {}, {"core": 0.9, "graphql": 0.15}, NOW) == ("go", 0)
    assert gg.decide("background", {}, None, NOW) == ("go", 0)  # unknown budget never blocks


def test_cooldown_grows_with_repeated_burst_refusals_and_is_capped():
    st = {}
    first = gg.after_refusal(st, "burst", NOW, reset_at=None)
    assert first["cooldown_until"] == NOW + 60 and first["strikes"] == 1
    second = gg.after_refusal(first, "burst", NOW, reset_at=None)
    assert second["cooldown_until"] == NOW + 120
    many = {"strikes": 10}
    assert gg.after_refusal(many, "burst", NOW, reset_at=None)["cooldown_until"] == NOW + gg.MAX_COOLDOWN


def test_an_hourly_refusal_waits_for_githubs_reset_time():
    st = gg.after_refusal({}, "hourly", NOW, reset_at=NOW + 1500)
    assert st["cooldown_until"] == NOW + 1500 and st["reason"] == "hourly"


def test_success_clears_strikes():
    assert gg.after_success({"strikes": 3, "cooldown_until": NOW - 5}) == {"strikes": 0, "cooldown_until": NOW - 5}


# ── the real thing, against a fake gh ───────────────────────────────────────

def _fake_gh(tmp_path, stderr="", rc=0, stdout="ok"):
    d = tmp_path / "realbin"
    d.mkdir(exist_ok=True)
    f = d / "gh"
    f.write_text(f"#!/bin/sh\necho '{stdout}'\necho '{stderr}' >&2\nexit {rc}\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d


def _run(tmp_path, realbin, *args, env_extra=None):
    env = {"PATH": f"{GATE.parent}:{realbin}:/usr/bin:/bin", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1", **(env_extra or {})}
    return subprocess.run([str(GATE), *args], capture_output=True, text=True, env=env, timeout=30)


def test_it_passes_calls_through_and_logs_them(tmp_path):
    p = _run(tmp_path, _fake_gh(tmp_path), "issue", "list")
    assert p.returncode == 0 and p.stdout.strip() == "ok"
    log = [json.loads(l) for l in (tmp_path / ".claude" / "logs" / "gh-calls.jsonl").read_text().splitlines()]
    assert log[-1]["cmd"] == "issue list" and log[-1]["rc"] == 0 and log[-1]["priority"] == "interactive"


def test_a_refusal_starts_a_cooldown_that_the_next_background_call_respects(tmp_path):
    real = _fake_gh(tmp_path, stderr="You have exceeded a secondary rate limit", rc=1)
    first = _run(tmp_path, real, "api", "x")
    assert first.returncode == 1 and "secondary rate limit" in first.stderr
    state = json.loads((tmp_path / ".claude" / "logs" / "gh-gate.json").read_text())
    assert state["reason"] == "burst" and state["strikes"] == 1
    second = _run(tmp_path, _fake_gh(tmp_path), "issue", "list", env_extra={"XPC_SERVICE_NAME": "com.marvin.ticket-pipeline"})
    assert second.returncode == gg.DEFERRED_RC and "gh-gate" in second.stderr and second.stdout == ""


def test_it_never_calls_itself(tmp_path):
    assert gg.find_real_gh(f"{GATE.parent}:{GATE.parent}:/nonexistent") in (None, "/opt/homebrew/bin/gh", "/usr/local/bin/gh")


def _gate_copy(tmp_path, name):
    """A second, separate copy of the gate (a worktree's bin/gh, a sandbox HOME's ~/.agents/bin/gh)."""
    d = tmp_path / name
    d.mkdir()
    f = d / "gh"
    f.write_bytes(GATE.read_bytes())
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d


def test_it_never_hands_a_call_to_another_copy_of_the_gate(tmp_path):
    # 2026-10-21: a worktree's bin/gh and ~/.agents/bin/gh both on PATH. Each took the other for the real gh and they
    # called each other back and forth: 18,040 logged "pr list" calls in two hours, from a caller named "Python".
    other = _gate_copy(tmp_path, "worktree-bin")
    real = _fake_gh(tmp_path)
    assert gg.find_real_gh(f"{other}:{real}:/nonexistent") == str(real / "gh")


def test_two_gate_copies_on_path_make_one_real_call_and_one_log_line(tmp_path):
    other = _gate_copy(tmp_path, "worktree-bin")
    real = _fake_gh(tmp_path)
    env = {"PATH": f"{other}:{GATE.parent}:{real}:/usr/bin:/bin", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1"}
    p = subprocess.run([str(other / "gh"), "pr", "list"], capture_output=True, text=True, env=env, timeout=30)
    assert p.returncode == 0 and p.stdout.strip() == "ok"
    log = (tmp_path / ".claude" / "logs" / "gh-calls.jsonl").read_text().splitlines()
    assert len(log) == 1, log


def test_a_gate_reached_from_inside_a_gate_with_no_real_gh_fails_at_once(tmp_path):
    # Only gate copies on PATH and no real gh anywhere: say so and stop, never loop.
    other = _gate_copy(tmp_path, "worktree-bin")
    # No /usr/bin or /bin on PATH: a machine with a real gh there (the Linux box's apt gh, marvin#623) would otherwise
    # hand the gate a real gh. The gate's shebang is absolute, so it needs nothing else from PATH.
    env = {"PATH": f"{other}:{GATE.parent}", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1"}
    p = subprocess.run([str(other / "gh"), "pr", "list"], capture_output=True, text=True, env=env, timeout=30)
    if gg.find_real_gh("/nonexistent"):  # a real gh is installed in a fallback location on this Mac: one call to it
        assert len((tmp_path / ".claude" / "logs" / "gh-calls.jsonl").read_text().splitlines()) == 1
    else:
        assert p.returncode == 127 and "not installed" in p.stderr


def test_a_gate_started_by_the_real_gh_passes_through_unlogged(tmp_path):
    # A gh extension calling gh again: one call was already gated and logged; the inner one is not counted twice.
    p = _run(tmp_path, _fake_gh(tmp_path), "issue", "list", env_extra={gg.INSIDE_ENV: "1"})
    assert p.returncode == 0 and p.stdout.strip() == "ok"
    assert not (tmp_path / ".claude" / "logs" / "gh-calls.jsonl").exists()


# ── UI PRs carry current, working images (marvin #735) ─────────────────────

SHA735 = "a7174e5642d35c6272c1787ae7db24aa2015db34"
RAW735 = f"https://raw.githubusercontent.com/o/r/{SHA735}/docs/images/pr/a.png"


def _asker(files, body="", compare_since=None):
    """A fake GitHub: the PR's files and body, and what changed since a pinned commit."""
    def ask(args):
        if args[:2] == ["repo", "view"]:
            return {"nameWithOwner": "o/r"}
        if args[:2] == ["pr", "view"]:
            return {"files": [{"path": f} for f in files], "body": body, "headRefOid": "f" * 40}
        if args[0] == "api" and args[1] == "repos/o/r":
            return {"default_branch": "main"}
        if args[0] == "api" and args[1].startswith(f"repos/o/r/compare/{SHA735}..."):
            return {"files": [{"filename": f} for f in (compare_since or [])]}
        if args[0] == "api" and args[1].startswith("repos/o/r/compare/"):
            return {"files": [{"filename": f} for f in files]}
        raise AssertionError(args)
    return ask


def test_creating_a_ui_pr_with_no_images_is_refused(tmp_path):
    msg = gg.ui_evidence_refusal(["pr", "create", "-R", "o/r", "--head", "x", "--title", "t", "--body", "words"],
                                 _asker(["site/page.html"]), profiles_dir=tmp_path)
    assert msg.startswith("NO_UI_EVIDENCE") and "site/page.html" in msg


def test_creating_a_ui_pr_reads_the_body_file_and_uses_the_current_branch(tmp_path):
    body = tmp_path / "b.md"
    body.write_text(f"![a]({RAW735})")
    argv = ["pr", "create", "--body-file", str(body), "--title", "t"]
    assert gg.ui_evidence_refusal(argv, _asker(["site/page.html"]), current_branch=lambda: "feat/x",
                                  profiles_dir=tmp_path) is None


def test_a_non_ui_pr_and_other_gh_calls_pass(tmp_path):
    assert gg.ui_evidence_refusal(["pr", "create", "-R", "o/r", "-H", "x", "-b", "hi"], _asker(["lib/a.py"]),
                                  profiles_dir=tmp_path) is None
    assert gg.ui_evidence_refusal(["issue", "list"], _asker([]), profiles_dir=tmp_path) is None


def test_merging_with_images_older_than_a_later_look_change_is_refused(tmp_path):
    ask = _asker(["site/page.html"], body=f"![a]({RAW735})", compare_since=["site/page.html"])
    assert gg.ui_evidence_refusal(["pr", "merge", "9", "-R", "o/r"], ask, profiles_dir=tmp_path).startswith("STALE_UI_EVIDENCE")
    ok = _asker(["site/page.html"], body=f"![a]({RAW735})", compare_since=["docs/images/pr/a.png"])
    assert gg.ui_evidence_refusal(["pr", "merge", "9", "-R", "o/r"], ok, profiles_dir=tmp_path) is None


def test_the_projects_profile_adds_its_own_ui_paths(tmp_path):
    (tmp_path / "voice.json").write_text(json.dumps({"repo": "o/r", "evidence": {"ui_paths": ["App/Sources/**/*.swift"]}}))
    msg = gg.ui_evidence_refusal(["pr", "ready", "9", "-R", "o/r"], _asker(["App/Sources/MenuBarIcon.swift"]),
                                 profiles_dir=tmp_path)
    assert msg.startswith("NO_UI_EVIDENCE")


def _fake_pr_gh(tmp_path, files, body):
    """A real gh stand-in on PATH that answers the gate's questions and records whether the call went through."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "gh"
    view = json.dumps({"files": [{"path": f} for f in files], "body": body, "headRefOid": "f" * 40})
    fake.write_text(f"#!/bin/sh\nif [ \"$1 $2\" = \"pr view\" ]; then echo '{view}'; exit 0; fi\n"
                    f"echo \"$@\" >> {tmp_path}/ran\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run_gate(tmp_path, bin_dir, argv, extra_env=None):
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "MARVIN_INSTANCE_DIR": str(tmp_path / "inst"),
           **(extra_env or {})}
    return subprocess.run([sys.executable, str(GATE), *argv], capture_output=True, text=True, env=env)


def test_end_to_end_a_refused_merge_never_reaches_github_and_says_why(tmp_path):
    bin_dir = _fake_pr_gh(tmp_path, ["site/page.html"], "no images")
    p = _run_gate(tmp_path, bin_dir, ["pr", "merge", "9", "-R", "o/r", "--merge"])
    assert p.returncode == 1 and "NO_UI_EVIDENCE" in p.stderr
    assert not (tmp_path / "ran").exists()


def test_end_to_end_a_person_can_override_once_with_a_reason(tmp_path):
    bin_dir = _fake_pr_gh(tmp_path, ["site/page.html"], "no images")
    p = _run_gate(tmp_path, bin_dir, ["pr", "merge", "9", "-R", "o/r"], {"MARVIN_UI_EVIDENCE_OK": "copy-only fix"})
    assert p.returncode == 0 and "pr merge 9" in (tmp_path / "ran").read_text()


def test_end_to_end_when_github_cant_be_asked_the_call_goes_through_with_a_note(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "gh"
    fake.write_text(f"#!/bin/sh\nif [ \"$1 $2\" = \"pr view\" ]; then echo offline >&2; exit 1; fi\necho \"$@\" >> {tmp_path}/ran\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    p = _run_gate(tmp_path, bin_dir, ["pr", "merge", "9", "-R", "o/r"])
    assert p.returncode == 0 and "couldn't check" in p.stderr and (tmp_path / "ran").exists()
