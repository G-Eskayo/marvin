"""marvin show (marvin#715): the CLI's checks, the copy into the outbox, and delivery to the dashboard.

Tries to break it: a temp file deleted before the copy, a huge file, a path outside the allowed roots, a symlink out,
secrets, an HTML page naming files outside its folder, two projects, a dashboard that isn't running or is too old.
Everything runs in tmp_path; the real HOME, outbox and dashboard are never touched.
"""
import json
import os
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))
import marvin_show as ms  # noqa: E402

DAY = date(2026, 11, 2)


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    outbox = home / ".claude" / "outbox"
    outbox.mkdir(parents=True)
    agents = home / ".agents"
    portfolio = home / "Developer" / "portfolio-website-updater"
    for d in (agents / "instance" / "docs" / "plans", portfolio / "docs"):
        d.mkdir(parents=True)
    # tmp_path itself is under /private/var/folders (a temp root): the "home" must not look like temp to the checks.
    scratch = Path("/private/tmp") / f"marvin-show-test-{os.getpid()}-{tmp_path.name}"
    scratch.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ms, "TEMP_ROOTS", ("/private/tmp", "/tmp"))
    projects = [
        {"id": "marvin", "name": "MARVIN", "repo": "G-Eskayo/marvin", "localPaths": [str(agents)]},
        {"id": "marvin-instance", "name": "MARVIN instance", "repo": "G-Eskayo/marvin-instance", "localPaths": [str(agents / "instance")]},
        {"id": "portfolio-website-updater", "name": "Portfolio", "repo": "G-Eskayo/portfolio-website-updater", "localPaths": [str(portfolio)]},
    ]
    yield {"home": home, "outbox": outbox, "agents": agents, "portfolio": portfolio, "scratch": scratch, "projects": projects}
    import shutil
    shutil.rmtree(scratch, ignore_errors=True)


def build(w, target, cwd=None, **kw):
    args = {"pr": None, "repo": None, "project": None, "topic": None, "label": None}
    args.update(kw)
    return ms.build_request(target, cwd=str(cwd or w["portfolio"]), projects=w["projects"], outbox=w["outbox"], today=DAY,
                            home=w["home"], **args)


def test_a_temp_screenshot_is_copied_into_the_outbox_under_its_project(world):
    shot = world["scratch"] / "migration.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    body, what = build(world, str(shot), topic="portfolio migration screenshots")
    copy = Path(body["path"])
    # The ticket's case: the folder starts with the project slug, so the Docs tab files it under the portfolio.
    assert copy.parent.name == "portfolio-website-updater-2026-11-02-portfolio-migration-screenshots"
    assert copy.read_bytes() == shot.read_bytes()
    assert body == {"kind": "file", "path": str(copy), "project": "portfolio-website-updater", "outboxName": copy.parent.name}
    assert what.startswith("copied to ")
    # Shown twice: one copy. A different file with the same name: a second name, never an overwrite.
    assert build(world, str(shot), topic="portfolio migration screenshots")[0]["path"] == str(copy)
    shot.write_bytes(b"\x89PNG\r\n\x1a\nother")
    assert Path(build(world, str(shot), topic="portfolio migration screenshots")[0]["path"]).name == "migration-2.png"


def test_a_temp_file_deleted_before_the_copy_is_refused_plainly_and_leaves_nothing(world):
    gone = world["scratch"] / "gone.png"
    with pytest.raises(ms.Refused, match="Not found"):
        build(world, str(gone))
    # Deleted between the check and the copy:
    real = world["scratch"] / "race.png"
    real.write_bytes(b"x")
    with pytest.raises(ms.Refused, match="deleted"):
        ms.copy_to_outbox(str(world["scratch"] / "race-vanished.png"), "marvin", None, outbox=world["outbox"], today=DAY)
    assert list(world["outbox"].iterdir()) == []


def test_a_huge_temp_file_is_refused_before_anything_is_copied(world, monkeypatch):
    monkeypatch.setattr(ms, "MAX_COPY_BYTES", 1024)
    big = world["scratch"] / "big.pdf"
    big.write_bytes(b"%PDF-" + b"0" * 4096)
    with pytest.raises(ms.Refused, match="Too big for the outbox"):
        build(world, str(big))
    assert list(world["outbox"].iterdir()) == []


def test_paths_outside_the_allowed_roots_and_secrets_are_refused(world):
    outside = world["home"] / "Desktop" / "private.png"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")
    token = world["home"] / ".claude" / ".gh-token"
    token.write_text("ghp_x")
    env = world["portfolio"] / ".env"
    env.write_text("KEY=1")
    link = world["scratch"] / "innocent.png"
    link.symlink_to(token)  # a temp symlink to a secret: judged where it really points
    cases = {str(outside): "Outside", str(token): "secret", str(env): "secret", str(link): "secret",
             "/etc/hosts": "Outside", str(world["portfolio"] / "docs"): "folder"}
    for p, why in cases.items():
        with pytest.raises(ms.Refused, match=why):
            build(world, p)
    plain_link = world["scratch"] / "desk.png"
    plain_link.symlink_to(outside)
    with pytest.raises(ms.Refused, match="Outside"):
        build(world, str(plain_link))


def test_files_in_clones_and_the_outbox_are_shown_in_place_with_their_project(world):
    plan = world["agents"] / "instance" / "docs" / "plans" / "p.md"
    plan.write_text("# Plan")
    body, _ = build(world, str(plan))
    assert body == {"kind": "file", "path": str(plan.resolve()), "project": "marvin-instance"}
    doc = world["portfolio"] / "docs" / "x.md"
    doc.write_text("x")
    assert build(world, "docs/x.md", cwd=world["portfolio"])[0]["project"] == "portfolio-website-updater"
    assert list(world["outbox"].iterdir()) == []  # nothing is copied unless it is in temp


def test_a_temp_html_page_brings_only_the_files_it_names(world):
    page_dir = world["scratch"] / "mock"
    page_dir.mkdir()
    (page_dir / "app.js").write_text("x=1")
    (page_dir / "img").mkdir()
    (page_dir / "img" / "a.png").write_bytes(b"png")
    (page_dir / "unrelated-notes.md").write_text("private scratch")
    (page_dir / ".env").write_text("KEY=1")
    secret = world["home"] / "Desktop" / "s.txt"
    secret.parent.mkdir(parents=True)
    secret.write_text("s")
    (page_dir / "leak.js").symlink_to(secret)
    (page_dir / "index.html").write_text(
        '<script src="app.js"></script><img src="img/a.png"><link href=".env"><script src="leak.js"></script>'
        '<script src="../../etc/passwd"></script><img src="https://evil.example/x.png"><img src="/etc/hosts">'
        "<div style=\"background:url('img/a.png')\"></div>")
    body, _ = build(world, str(page_dir / "index.html"), project="marvin", topic="show window mockup")
    folder = Path(body["path"]).parent
    assert folder.name == "marvin-2026-11-02-show-window-mockup"
    got = sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())
    assert got == ["app.js", "img/a.png", "index.html"]


def test_a_temp_file_with_no_project_asks_for_one(world, tmp_path):
    shot = world["scratch"] / "x.png"
    shot.write_bytes(b"x")
    nowhere = world["home"]
    with pytest.raises(ms.Refused, match="--project"):
        build(world, str(shot), cwd=nowhere)


def test_pr_files_and_urls(world):
    body, _ = build(world, "docs/design/m/index.html", pr=934, repo="G-Eskayo/marvin")
    assert body == {"kind": "pr", "repo": "G-Eskayo/marvin", "path": "docs/design/m/index.html", "number": 934, "project": "marvin"}
    assert build(world, "./docs/plan.md", pr=1, repo="G-Eskayo/marvin")[0]["path"] == "docs/plan.md"
    blob, _ = build(world, "https://github.com/G-Eskayo/marvin/blob/design/924/docs/design/m/index.html", branch_exists=lambda r: r == "design/924")
    assert blob == {"kind": "pr", "repo": "G-Eskayo/marvin", "ref": "design/924", "path": "docs/design/m/index.html"}
    # A SHA or a branch the clone doesn't know: the first part is the ref.
    assert build(world, "https://github.com/G-Eskayo/marvin/blob/abc1234/docs/a.md", branch_exists=lambda r: True)[0]["ref"] == "abc1234"
    assert build(world, "https://github.com/G-Eskayo/marvin/blob/main/docs/a.md", branch_exists=lambda r: False)[0]["path"] == "docs/a.md"
    url, _ = build(world, "https://dev.gileskayo.me/projects/", project="portfolio-website-updater")
    assert url == {"kind": "url", "url": "https://dev.gileskayo.me/projects/", "project": "portfolio-website-updater"}


# ── delivery ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_dashboard_that_is_not_running_is_started_and_asked_again():
    answers = iter([None, None, (200, {"ok": True, "project": "marvin"})])
    started = []
    code, answer = ms.deliver({"kind": "url"}, 1, post=lambda b, p: next(answers), start=lambda: started.append(1) or True, sleep=lambda s: None)
    assert (code, answer["project"], started) == (0, "marvin", [1])


def test_a_dashboard_that_never_comes_up_or_is_too_old_says_so():
    code, answer = ms.deliver({}, 1, post=lambda b, p: None, start=lambda: True, sleep=lambda s: None, wait_s=3)
    assert code == 3 and "isn't running" in answer["reason"]
    code, answer = ms.deliver({}, 1, post=lambda b, p: None, launch=False)
    assert code == 3
    code, answer = ms.deliver({}, 1, post=lambda b, p: (404, {}))
    assert code == 3 and "older than marvin show" in answer["reason"]
    code, answer = ms.deliver({}, 1, post=lambda b, p: (422, {"ok": False, "reason": "Outside"}))
    assert (code, answer["reason"]) == (2, "Outside")


def test_post_show_talks_json_to_a_real_local_server():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["type"] = self.headers["Content-Type"]
            seen["origin"] = self.headers.get("Origin")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"ok": True, "window": "opened"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    try:
        assert ms.post_show({"kind": "url", "url": "https://x"}, srv.server_address[1]) == (200, {"ok": True, "window": "opened"})
    finally:
        srv.server_close()
    assert seen == {"type": "application/json", "origin": None, "body": {"kind": "url", "url": "https://x"}}
    # Nothing listening: None, not an exception.
    assert ms.post_show({}, srv.server_address[1], timeout=2) is None


# ── which Mac ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_mac_with_the_most_recent_input_wins_and_an_asleep_one_never_does():
    assert ms.pick_mac(300.0, {"gils-mac-mini": 4.0}) == "gils-mac-mini"
    assert ms.pick_mac(2.0, {"gils-mac-mini": 4.0}) is None
    assert ms.pick_mac(5.0, {"gils-mac-mini": 5.0}) is None  # a tie stays here
    assert ms.pick_mac(900.0, {"gils-mac-mini": None}) is None  # asleep / off / no answer
    assert ms.pick_mac(None, {"gils-mac-mini": 10.0}) == "gils-mac-mini"
    assert ms.pick_mac(None, {}) is None
    assert ms.parse_idle('    |   "HIDIdleTime" = 1500000000\n') == 1.5
    assert ms.parse_idle("ssh: connect to host x port 22: Operation timed out") is None


class FakeRun:
    """ssh to the other Mac, scripted: the inbox folder, then that Mac's marvin-show --here."""

    def __init__(self, answer=None, code=0, inbox_ok=True):
        self.calls, self.answer, self.code, self.inbox_ok = [], answer, code, inbox_ok

    def __call__(self, host, cmd, timeout=8, stdin=None):
        import subprocess as sp
        self.calls.append(cmd)
        if "show-inbox" in cmd and "mkdir" in cmd:
            return sp.CompletedProcess(cmd, 0 if self.inbox_ok else 255, "/Users/g/.agents/var/show-inbox/1-2" if self.inbox_ok else "", "")
        if self.answer is None:
            return sp.CompletedProcess(cmd, 255, "", "ssh: Operation timed out")
        return sp.CompletedProcess(cmd, self.code, json.dumps(self.answer) + "\n", "")


def test_a_file_goes_to_the_other_macs_inbox_then_its_own_marvin_show(world):
    page = world["scratch"] / "m" / "index.html"
    page.parent.mkdir()
    (page.parent / "app.js").write_text("x")
    page.write_text('<script src="app.js"></script>')
    copied = []
    run = FakeRun({"ok": True, "project": "marvin", "window": "reused", "request": {"x": 1}})
    body = {"kind": "file", "path": str(page), "project": "marvin", "outboxName": "marvin-2026-11-02-m", "label": "it's a page"}
    code, answer = ms.deliver_remote("gils-mac-mini", body, run=run, copy=lambda h, s, d: copied.append((s.name, d)) or True)
    assert code == 0 and answer == {"ok": True, "project": "marvin", "window": "reused"}
    assert copied == [("index.html", "/Users/g/.agents/var/show-inbox/1-2/index.html"), ("app.js", "/Users/g/.agents/var/show-inbox/1-2/app.js")]
    cmd = run.calls[-1]
    assert cmd.startswith("$HOME/.agents/bin/marvin-show --here --json --project marvin")
    assert "--outbox-name marvin-2026-11-02-m" in cmd and "'it'\"'\"'s a page'" in cmd  # quoted for the remote shell
    assert cmd.endswith("/Users/g/.agents/var/show-inbox/1-2/index.html")


def test_the_other_mac_failing_means_show_it_here(world):
    f = world["agents"] / "a.md"
    f.write_text("x")
    body = {"kind": "file", "path": str(f), "project": "marvin"}
    ok_copy = lambda h, s, d: True
    assert ms.deliver_remote("m", body, run=FakeRun(inbox_ok=False), copy=ok_copy) is None  # asleep at the first ssh
    assert ms.deliver_remote("m", body, run=FakeRun(answer=None), copy=ok_copy) is None  # dropped mid-way
    assert ms.deliver_remote("m", body, run=FakeRun({"ok": True}), copy=lambda h, s, d: False) is None  # copy failed
    assert ms.deliver_remote("m", body, run=FakeRun({"ok": False, "reason": "x"}, code=3), copy=ok_copy) is None  # its dashboard down
    assert ms.deliver_remote("m", {**body, "path": str(world["agents"] / "gone.md")}, run=FakeRun({"ok": True}), copy=ok_copy) is None
    # Refused there is an answer, not a fallback.
    assert ms.deliver_remote("m", body, run=FakeRun({"ok": False, "reason": "Outside"}, code=2), copy=ok_copy) == (2, {"ok": False, "reason": "Outside"})


def test_a_huge_file_is_not_sent_across(world, monkeypatch):
    monkeypatch.setattr(ms, "MAX_COPY_BYTES", 10)
    f = world["agents"] / "big.png"
    f.write_bytes(b"x" * 100)
    assert ms.deliver_remote("m", {"kind": "file", "path": str(f)}, run=FakeRun({"ok": True}), copy=lambda *a: True) is None


def test_pr_files_and_urls_go_across_without_copying():
    run = FakeRun({"ok": True})
    ms.deliver_remote("m", {"kind": "pr", "repo": "G-Eskayo/marvin", "number": 934, "path": "docs/a.md"}, run=run, copy=None)
    assert run.calls[-1].endswith("--pr 934 --repo G-Eskayo/marvin docs/a.md")
    ms.deliver_remote("m", {"kind": "pr", "repo": "G-Eskayo/marvin", "ref": "design/924", "path": "docs/a.md"}, run=run)
    assert run.calls[-1].endswith("https://github.com/G-Eskayo/marvin/blob/design/924/docs/a.md")
    ms.deliver_remote("m", {"kind": "url", "url": "https://x.example/a b"}, run=run)
    assert run.calls[-1].endswith("'https://x.example/a b'")


def test_the_inbox_keeps_a_week(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(), new.mkdir()
    os.utime(old, (0, 0))
    ms.prune_inbox(tmp_path)
    assert not old.exists() and new.exists()
    ms.prune_inbox(tmp_path / "missing")  # no inbox yet: nothing to do


def test_main_with_here_never_asks_the_other_mac(world, monkeypatch, capsys):
    f = world["agents"] / "a.md"
    f.write_text("x")
    monkeypatch.setattr(ms, "read_catalog", lambda: world["projects"])
    monkeypatch.setattr(ms, "HOME", world["home"])
    monkeypatch.setattr(ms, "mac_peers", lambda: (_ for _ in ()).throw(AssertionError("asked a peer")))
    monkeypatch.setattr(ms, "prune_inbox", lambda: None)
    monkeypatch.setattr(ms, "deliver", lambda body, port, launch=True: (0, {"ok": True, "project": body.get("project"), "window": "opened", "label": "a.md"}))
    monkeypatch.setattr(ms, "build_request", lambda t, **kw: ({"kind": "file", "path": t, "project": "marvin"}, t))
    assert ms.main([str(f), "--here", "--outbox-name", "marvin-2026-11-02-a"]) == 0
    assert "Shown on this Mac, in the marvin window" in capsys.readouterr().out
