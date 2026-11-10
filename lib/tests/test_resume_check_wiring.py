"""Where the resume check (marvin#1221) is wired: the SessionStart report's handoff section, the remote-session
resume prompt (and ticket 478's three gaps there), and the two places a handoff is written (the skill, via the
PostToolUse hook, and the transcript rebuild). Temp HOME only; GitHub is never called.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_resume_check_wiring.py -v
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
SCRIPTS = LIB.parent / "skills" / "handoff" / "scripts"
sys.path.insert(0, str(LIB))

import resume_check as rc  # noqa: E402
import session_start_report as ssr  # noqa: E402

UTC = timezone.utc


def _load(name, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── SessionStart report ──────────────────────────────────────────────────────

@pytest.fixture
def handoffs(monkeypatch, tmp_path):
    claude = tmp_path / ".claude"
    (claude / "handoffs").mkdir(parents=True)
    monkeypatch.setattr(ssr, "CLAUDE_DIR", claude)
    monkeypatch.setattr(ssr, "HOME", tmp_path)
    seen = []

    def fake_check(text, when, **kw):
        seen.append((text, when))
        return rc.Report("unverified", when, reason="GitHub unreachable (test)")

    monkeypatch.setattr(ssr.resume_check, "check", fake_check)
    monkeypatch.setattr(ssr.resume_check, "log_run", lambda *a, **k: seen.append(("log", k)))
    return claude / "handoffs", seen


def test_the_section_ranks_by_as_of_not_mtime(handoffs):
    d, seen = handoffs
    rebuilt = d / "handoff-2026-11-09-21-50.md"
    rebuilt.write_text(f"---\nas_of: {(datetime.now(UTC) - timedelta(days=6)):%Y-%m-%dT%H:%M:%SZ}\n---\n# old content")
    live = d / "handoff-2026-11-08-10-00.md"
    live.write_text(f"---\nas_of: {(datetime.now(UTC) - timedelta(days=1)):%Y-%m-%dT%H:%M:%SZ}\n---\n# newer content")
    os.utime(live, (1, 1))
    out = ssr.check_handoff()
    assert "handoff-2026-11-08-10-00.md" in out and "newer content" in out


def test_unreachable_github_is_said_never_silent_and_the_run_is_logged(handoffs):
    d, seen = handoffs
    (d / "handoff-x.md").write_text(f"---\nas_of: {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}\n---\n# H\n#5")
    out = ssr.check_handoff()
    assert "unverified" in out and "GitHub unreachable" in out
    assert any(s[0] == "log" and s[1]["where"] == "session-start" for s in seen)


def test_a_handoff_older_than_seven_days_by_as_of_is_not_shown_even_with_a_new_mtime(handoffs):
    d, _ = handoffs
    (d / "handoff-x.md").write_text("---\nas_of: 2026-01-01T00:00:00Z\n---\n# ancient")
    assert ssr.check_handoff() is None


def test_a_check_that_raises_still_shows_the_handoff_labelled(handoffs, monkeypatch):
    d, _ = handoffs
    (d / "handoff-x.md").write_text("# H")
    monkeypatch.setattr(ssr.resume_check, "check", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    out = ssr.check_handoff()
    assert out and "handoff-x.md" in out and "unverified" in out


# ── check_remote_session (ticket 478 + the surfaced prompt) ───────────────────

@pytest.fixture
def remote(monkeypatch, tmp_path):
    mod = _load("check_remote_session", monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(mod, "remote_devices", lambda: {"mini": {"tailscale_hostname": "mini"}})
    monkeypatch.setattr(mod, "_check_remote", lambda d, h: {"device_id": d, "mtime": time.time() - 60,
                                                            "transcript_path": "/t.jsonl"})
    calls = []
    monkeypatch.setattr(mod, "dispatch", lambda cmd, **k: calls.append(cmd) or type("R", (), {"ok": True})())
    monkeypatch.setattr(mod.subprocess, "run", lambda argv, **k: None)
    return mod, calls


def test_478_a_remote_transcript_older_than_24h_is_ignored(remote, monkeypatch):
    mod, calls = remote
    monkeypatch.setattr(mod, "_check_remote", lambda d, h: {"device_id": d, "mtime": time.time() - 25 * 3600,
                                                            "transcript_path": "/t.jsonl"})
    mod.main()  # a fresh state file (last_seen = 0) used to let a months-old transcript through
    assert calls == []


def test_478_a_failed_generation_is_not_retried_inside_the_back_off(remote, monkeypatch):
    mod, calls = remote
    monkeypatch.setattr(mod, "dispatch", lambda cmd, **k: calls.append(cmd) or type("R", (), {"ok": False})())
    mod.main()
    mod.main()
    assert len(calls) == 1
    state = json.loads(mod.STATE_PATH.read_text())
    assert state.get("mini:failed_at")


def test_478_the_back_off_expires(remote, monkeypatch):
    mod, calls = remote
    mod.STATE_PATH.write_text(json.dumps({"mini:failed_at": time.time() - mod.FAIL_BACKOFF_S - 5}))
    mod.main()
    assert len(calls) == 1
    assert "mini:failed_at" not in json.loads(mod.STATE_PATH.read_text()), "success clears the failure"


def test_478_a_hung_remote_only_skips_itself(monkeypatch, tmp_path):
    mod = _load("check_remote_session", monkeypatch, tmp_path)

    def run(argv, **k):
        if "hung" in argv:
            raise subprocess.TimeoutExpired(argv, 15)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"mtime": time.time(), "transcript_path": "/t"}), "")

    monkeypatch.setattr(mod.subprocess, "run", run)
    assert mod._check_remote("a", "hung") is None
    assert mod._check_remote("b", "ok")["device_id"] == "b"


def test_the_surfaced_prompt_carries_the_check_and_strikes_changed_urgent_steps(remote, monkeypatch, tmp_path, capsys):
    mod, _ = remote
    h = tmp_path / "h.md"
    h.write_text("---\nas_of: 2026-11-03T00:00:00Z\nmachine: mac-mini-1\n---\n# H\n## Resume prompt\n---\n"
                 "URGENT: fix G-Eskayo/marvin#17\nThen read the docs.\n---\n")

    def fake_check(text, when, **kw):
        r = rc.Report("verified", when, checked=1, refs=1,
                      changed=[rc.Changed("G-Eskayo/marvin#17", "t", ["closed 2026-11-04"])])
        r.line_refs = {"URGENT: fix G-Eskayo/marvin#17": ["G-Eskayo/marvin#17"]}
        return r

    logged = []
    monkeypatch.setattr(mod.resume_check, "check", fake_check)
    monkeypatch.setattr(mod.resume_check, "log_run", lambda *a, **k: logged.append(k))
    mod._surface_resume_prompt(h)
    out = capsys.readouterr().out
    assert "1 of 1 changed since, treat as history" in out
    assert "~~URGENT: fix G-Eskayo/marvin#17~~" in out and "Then read the docs." in out
    assert logged and logged[0]["where"] == "remote-resume"


def test_the_surfaced_handoff_is_chosen_by_as_of(remote, monkeypatch, tmp_path):
    mod, _ = remote
    d = tmp_path / ".claude" / "handoffs"
    d.mkdir(parents=True)
    (d / "handoff-b.md").write_text("---\nas_of: 2026-11-01T00:00:00Z\n---\n")
    (d / "handoff-a.md").write_text("---\nas_of: 2026-11-08T00:00:00Z\n---\n")
    os.utime(d / "handoff-a.md", (1, 1))
    picked = []
    monkeypatch.setattr(mod, "_surface_resume_prompt", lambda p: picked.append(p.name))
    mod.main()
    assert picked == ["handoff-a.md"]


# ── where handoffs are written ───────────────────────────────────────────────

def test_the_rebuild_dates_the_handoff_by_the_transcript_not_today(monkeypatch, tmp_path):
    mod = _load("generate_handoff_from_transcript", monkeypatch, tmp_path)
    t = tmp_path / "s.jsonl"
    t.write_text("\n".join(json.dumps(x) for x in [
        {"type": "user", "timestamp": "2026-11-03T18:00:00.000Z", "message": {"content": "do the thing"}},
        {"type": "assistant", "timestamp": "2026-11-03T18:40:00.000Z", "message": {"content": [{"type": "text", "text": "ok"}]}},
        {"type": "summary", "timestamp": "2026-11-09T21:00:00.000Z"},
    ]) + "\n")
    assert mod.last_message_time(t) == datetime(2026, 11, 3, 18, 40, tzinfo=UTC)


def test_the_rebuild_never_overwrites_an_existing_handoff_and_stamps_its_own(monkeypatch, tmp_path):
    mod = _load("generate_handoff_from_transcript", monkeypatch, tmp_path)
    d = tmp_path / "handoffs"
    d.mkdir()
    monkeypatch.setattr(mod, "HANDOFF_DIR", d)
    skill = d / "handoff-2026-11-09-21-50.md"
    skill.write_text("# skill-written")
    target = mod.handoff_path(datetime(2026, 11, 9, 21, 50, tzinfo=UTC))
    assert target != skill and not target.exists()
    t = tmp_path / "abc123.jsonl"
    t.write_text(json.dumps({"type": "user", "timestamp": "2026-11-03T18:40:00Z", "message": {"content": "hi"}}) + "\n")

    def launch(kind, prompt, **k):
        assert str(target) in prompt
        target.write_text("---\nas_of: 2026-11-09T21:50:00Z\nsource: skill\n---\n# rebuilt")  # the child's own hook
        return type("R", (), {"exit_code": 0, "stderr": "", "text": ""})()

    monkeypatch.setattr(mod.marvin_launcher, "launch", launch)
    monkeypatch.setattr(mod, "handoff_path", lambda now=None: target)
    monkeypatch.setattr(mod, "machine_label", lambda: "mac-mini-1")
    monkeypatch.setattr(sys, "argv", ["x", str(t)])
    mod.main()
    assert skill.read_text() == "# skill-written"
    fm = rc.parse_front_matter(target.read_text())
    assert fm == {"as_of": "2026-11-03T18:40:00Z", "machine": "mac-mini-1", "session": "abc123", "source": "rebuilt"}


def test_the_post_write_hook_stamps_a_skill_written_handoff(monkeypatch, tmp_path, capsys):
    mod = _load("emit-resume-prompt", monkeypatch, tmp_path)
    d = tmp_path / ".claude" / "handoffs"
    d.mkdir(parents=True)
    h = d / "handoff-2026-11-09-22-00.md"
    h.write_text("# Handoff\n## Resume prompt\n---\nGo.\n---\n")
    monkeypatch.setattr(mod, "machine_label", lambda: "macbook-pro-1")
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(h)}, "session_id": "sess-1"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    mod.main()
    fm = rc.parse_front_matter(h.read_text())
    assert fm["machine"] == "macbook-pro-1" and fm["session"] == "sess-1" and fm["source"] == "skill"
    assert abs(rc._parse_time(fm["as_of"]) - datetime.now(UTC)) < timedelta(minutes=1)
    assert "Go." in capsys.readouterr().out


def test_the_post_write_hook_keeps_an_existing_stamp(monkeypatch, tmp_path):
    mod = _load("emit-resume-prompt", monkeypatch, tmp_path)
    d = tmp_path / ".claude" / "handoffs"
    d.mkdir(parents=True)
    h = d / "handoff-x.md"
    original = "---\nas_of: 2026-11-03T18:40:00Z\nmachine: mac-mini-1\nsource: rebuilt\n---\n# H\n"
    h.write_text(original)
    monkeypatch.setattr(mod, "machine_label", lambda: "macbook-pro-1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(h)}})))
    mod.main()
    assert h.read_text() == original
