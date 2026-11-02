"""The private website demo (marvin#1007): these tests try to make it publish itself, serve something it shouldn't,
or leave a broken site up. Real git and a real HTTP server; only npm is faked (no network, no node in the suite)."""
from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import site_demo as sd


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def origin(tmp_path):
    """A bare 'GitHub' with a branch holding a site/ folder, and the demo checkout cloned from it."""
    work = tmp_path / "work"
    (work / "site").mkdir(parents=True)
    _git(work, "init", "-q", "-b", "main")
    (work / "site" / "package-lock.json").write_text("{}")
    (work / "site" / "page.txt").write_text("v1")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "v1")
    _git(work, "checkout", "-q", "-b", "feat/site")
    (work / "site" / "page.txt").write_text("v2")
    _git(work, "commit", "-qam", "v2 on the branch")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return bare


@pytest.fixture
def demo(home, origin):
    _git(home, "clone", "-q", str(origin), str(home / ".agents-site-demo"))
    return home / ".agents-site-demo"


class Npm:
    """npm stand-in: `npm ci` makes node_modules, `npm run build` copies page.txt into dist/index.html."""

    def __init__(self, fail_build=False, no_index=False):
        self.calls = []
        self.fail_build, self.no_index = fail_build, no_index

    def __call__(self, cmd, cwd=None, **kw):
        if cmd[0] != "npm":
            return subprocess.run(cmd, cwd=cwd, **kw)
        self.calls.append(cmd[:2])
        site = Path(cwd)
        if cmd[1] == "ci":
            (site / "node_modules").mkdir(exist_ok=True)
        elif self.fail_build:
            return subprocess.CompletedProcess(cmd, 1, "", "astro: build exploded")
        else:
            (site / "dist").mkdir(exist_ok=True)
            if not self.no_index:
                (site / "dist" / "index.html").write_text((site / "page.txt").read_text())
            (site / "dist" / "404.html").write_text("custom not found")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _served(site="marvin"):
    return (sd.data_dir(site) / "current" / "index.html").read_text()


# ── binding: never wider than the tailnet ───────────────────────────────

@pytest.mark.parametrize("ip", ["0.0.0.0", "::", "192.168.1.20", "10.0.0.5", "8.8.8.8", "100.128.0.1", "", "localhost"])
def test_it_refuses_to_serve_anywhere_but_the_tailnet_or_loopback(ip):
    with pytest.raises(sd.DemoError):
        sd.check_bind(ip)


@pytest.mark.parametrize("ip", ["100.101.102.103", "100.64.0.1", "100.127.255.254", "127.0.0.1"])
def test_tailnet_and_loopback_addresses_are_allowed(ip):
    assert sd.check_bind(ip) == ip


def _fake_tailscale(stdout, code=0):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout, "")


@pytest.mark.parametrize("out,want", [
    ("100.101.102.103\n", "100.101.102.103"),
    ("fd7a:115c::1\n100.70.1.2\n", "100.70.1.2"),       # skips IPv6 and anything else
    ("192.168.1.4\n", None),                             # a LAN address is not the tailnet
    ("garbage", None),
    ("", None),
])
def test_tailscale_ipv4_only_accepts_a_tailnet_address(monkeypatch, out, want):
    monkeypatch.setattr(sd.host_os, "tailscale_bin", lambda: "/x/tailscale")
    assert sd.tailscale_ipv4(_fake_tailscale(out)) == want


def test_no_tailscale_means_no_address_and_serve_exits_without_binding(home, monkeypatch):
    monkeypatch.setattr(sd.host_os, "tailscale_bin", lambda: None)
    assert sd.serve("marvin", 0) == 1
    st = sd.read_status("marvin")
    assert st["serving"] is False and "Tailscale" in st["error"]


def test_tailscale_down_is_no_address(monkeypatch):
    monkeypatch.setattr(sd.host_os, "tailscale_bin", lambda: "/x/tailscale")
    assert sd.tailscale_ipv4(_fake_tailscale("100.101.102.103", code=1)) is None


def test_magicdns_name_drops_the_trailing_dot_and_survives_junk(monkeypatch):
    monkeypatch.setattr(sd.host_os, "tailscale_bin", lambda: "/x/tailscale")
    assert sd.magicdns_name(_fake_tailscale(json.dumps({"Self": {"DNSName": "box.tail1.ts.net."}}))) == "box.tail1.ts.net"
    assert sd.magicdns_name(_fake_tailscale("not json")) is None
    assert sd.magicdns_name(_fake_tailscale(json.dumps({"Self": {"DNSName": 5}}))) is None


# ── the server: static files only ───────────────────────────────────────

@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    (root / "docs").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "index.html").write_text("home")
    (root / "docs" / "index.html").write_text("docs")
    (root / "404.html").write_text("custom not found")
    (tmp_path / "secret.txt").write_text("outside the site")
    srv = sd.make_server(root, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url, method="GET"):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=5) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def test_pages_and_folders_serve_their_index(server):
    assert _get(server + "/")[:2] == (200, "home")
    assert _get(server + "/docs/")[:2] == (200, "docs")


def test_a_missing_page_gets_the_sites_own_404(server):
    assert _get(server + "/nope/")[:2] == (404, "custom not found")


def test_a_folder_without_an_index_is_a_404_not_a_listing(server):
    code, body, _ = _get(server + "/empty/")
    assert code == 404 and "Directory listing" not in body


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/docs/../../secret.txt", "//etc/passwd"])
def test_path_traversal_never_leaves_the_site(server, path):
    code, body, _ = _get(server + path)
    assert "outside the site" not in body and "root:" not in body


def test_only_get_and_head(server):
    assert _get(server + "/", "POST")[0] == 501
    assert _get(server + "/", "DELETE")[0] == 501
    assert _get(server + "/", "HEAD")[0] == 200


def test_responses_are_not_cached_and_not_sniffed(server):
    _, _, headers = _get(server + "/")
    assert headers["Cache-Control"] == "no-cache" and headers["X-Content-Type-Options"] == "nosniff"


# ── building: triggered, atomic, and a failure keeps the last good site ──

def test_build_checks_out_the_branch_builds_and_swaps_it_in(demo):
    npm = Npm()
    st = sd.build("marvin", "feat/site", run=npm)
    assert st["ok"] is True and st["branch"] == "feat/site" and st["commit_subject"] == "v2 on the branch"
    assert _served() == "v2"
    assert ["npm", "ci"] in npm.calls
    assert st["rebuild_command"] == sd.REBUILD_COMMAND


def test_a_second_build_remembers_the_branch_and_skips_npm_ci_when_the_lockfile_is_unchanged(demo):
    sd.build("marvin", "feat/site", run=Npm())
    npm = Npm()
    st = sd.build("marvin", run=npm)
    assert st["ok"] and st["branch"] == "feat/site"
    assert ["npm", "ci"] not in npm.calls


def test_a_failed_build_keeps_the_last_good_site_up_and_says_why(demo):
    sd.build("marvin", "feat/site", run=Npm())
    st = sd.build("marvin", run=Npm(fail_build=True))
    assert st["ok"] is False and "build exploded" in st["error"]
    assert _served() == "v2"


def test_a_build_with_no_index_page_is_not_swapped_in(demo):
    sd.build("marvin", "main", run=Npm())
    st = sd.build("marvin", "feat/site", run=Npm(no_index=True))
    assert st["ok"] is False and "index.html" in st["error"]
    assert _served() == "v1"


def test_a_branch_that_does_not_exist_fails_cleanly(demo):
    st = sd.build("marvin", "no/such-branch", run=Npm())
    assert st["ok"] is False and "fetch" in st["error"]


def test_old_builds_are_pruned_to_the_last_two(demo):
    for _ in range(4):
        sd.build("marvin", "feat/site", run=Npm())
    assert len(list((sd.data_dir("marvin") / "builds").iterdir())) == sd.KEEP_BUILDS
    assert _served() == "v2"


def test_local_edits_in_the_demo_checkout_stop_the_build_instead_of_being_wiped(demo):
    (demo / "site" / "page.txt").write_text("someone's edit")
    st = sd.build("marvin", "feat/site", run=Npm())
    assert st["ok"] is False and "local edits" in st["error"]
    assert (demo / "site" / "page.txt").read_text() == "someone's edit"


def test_it_never_builds_in_the_live_engine_checkout(home, origin, monkeypatch):
    _git(home, "clone", "-q", str(origin), str(home / ".agents"))
    monkeypatch.setattr(sd, "src_dir", lambda: home / ".agents")
    st = sd.build("marvin", "feat/site", run=Npm())
    assert st["ok"] is False and "live engine checkout" in st["error"]


def test_no_demo_checkout_is_a_clear_error(home):
    st = sd.build("marvin", "main", run=Npm())
    assert st["ok"] is False and "no demo checkout" in st["error"]


def test_two_builds_at_once_the_second_is_refused(demo):
    lock = sd.data_dir("marvin") / "build.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    import fcntl
    with open(lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(sd.DemoError, match="another build"):
            sd.build("marvin", "feat/site", run=Npm())


def test_setup_installs_a_post_merge_hook_and_never_overwrites_someone_elses(demo):
    st = sd.setup("marvin", "feat/site")
    hook = demo / ".git" / "hooks" / "post-merge"
    assert st["branch"] == "feat/site" and sd.HOOK_MARK in hook.read_text() and "site-demo" in hook.read_text()
    sd.setup("marvin", "feat/site")  # ours: replaced quietly
    hook.write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(sd.DemoError, match="isn't ours"):
        sd.setup("marvin", "feat/site")


def test_status_file_is_valid_json_with_what_the_dashboard_needs(demo):
    sd.build("marvin", "feat/site", run=Npm())
    st = json.loads(sd.status_path("marvin").read_text())
    for key in ("site", "branch", "commit", "built_at", "ok", "rebuild_command", "serve_dir", "source"):
        assert key in st
    assert str(sd.status_path("marvin")).endswith(".claude/logs/site-demo-marvin.json")
