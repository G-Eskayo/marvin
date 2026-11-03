"""mac-mini-2012 as the merge gate's extra runner (marvin #933): the box's result is recorded next to the Mac's and
never decides anything. Git is real here (a temp repo plays the gate's clone, a shared clone plays the box's
checkout); the box-side shell runs for real against a throwaway HOME with a fake venv python."""
import base64
import json
import subprocess
import sys

import pytest

import box_runner as br
import task_dispatch as td

GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


@pytest.fixture(autouse=True)
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(br, "LOG", tmp_path / "logs" / "box-runs.jsonl")
    return tmp_path / "logs" / "box-runs.jsonl"


def lines(log):
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


def commit(repo, name):
    (repo / name).write_text(name)
    subprocess.run([*GIT, "-C", str(repo), "add", name], check=True)
    subprocess.run([*GIT, "-C", str(repo), "commit", "-qm", name], check=True)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "mac-repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    base = commit(r, "base.txt")
    return r, base


def refs(repo):
    return subprocess.run(["git", "-C", str(repo), "for-each-ref", "refs/box-runs/"], capture_output=True,
                          text=True).stdout.strip()


# ── reading pytest ───────────────────────────────────────────────────────────────────────────────────────────

def test_failing_tests_are_read_from_the_short_summary():
    out = """lib/tests/test_a.py ..F
=========================== short test summary info ============================
FAILED lib/tests/test_a.py::test_one - AssertionError: no
FAILED lib/tests/test_a.py::test_one - AssertionError: again
ERROR bench/lib/tests/test_b.py::test_two
FAILED this is not a test id
1 failed, 3 errors in 2.0s"""
    assert br.failing_tests(out) == ["bench/lib/tests/test_b.py::test_two", "lib/tests/test_a.py::test_one"]
    assert br.failing_tests("") == [] and br.failing_tests(None) == []


@pytest.mark.parametrize("result,outcome", [
    (td.DispatchResult(ok=True, device_id="box", output="9 passed"), "passed"),
    (td.DispatchResult(ok=False, device_id="box", timed_out=True), "timeout"),
    (td.DispatchResult(ok=False, device_id="box", unreachable=True, error="exit 255"), "offline"),
    (td.DispatchResult(ok=False, error="no machine that accepts 'test' work is currently available"), "offline"),
    (td.DispatchResult(ok=False, device_id="box", error="exit 1: ", output="FAILED a.py::t - x\n1 failed"), "failed"),
    (td.DispatchResult(ok=False, device_id="box", error="exit 1: ", output="no summary at all"), "error"),
    (td.DispatchResult(ok=False, device_id="box", error="exit 3: bundle"), "error"),       # the hand-off failed
    (td.DispatchResult(ok=False, device_id="box", error="exit 2: interrupted"), "error"),
])
def test_each_way_a_box_run_ends_has_its_own_outcome(result, outcome):
    assert br.classify(result) == outcome


# ── the hand-off: bundle, then the box-side shell, for real ──────────────────────────────────────────────────

@pytest.fixture
def box_home(tmp_path, repo):
    """The box: a HOME whose ~/.agents is a clone of the Mac repo at its base commit, and a fake venv python that
    reports which commit it was run on."""
    mac, base = repo
    home = tmp_path / "box-home"
    home.mkdir()
    subprocess.run(["git", "clone", "-q", str(mac), str(home / ".agents")], check=True)
    venv = home / ".agents" / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text('#!/bin/bash\necho "ran on $(git rev-parse HEAD) gate=$MARVIN_MERGE_GATE args=$*"\n'
                                 'cat pr.txt 2>/dev/null\nexit ${FAKE_EXIT:-0}\n')
    (venv / "python").chmod(0o755)
    return home


def run_box_side(home, stdin, fake_exit=0):
    return subprocess.run(["/bin/bash", "-c", br.box_command()], input=stdin, capture_output=True, text=True,
                          env={"HOME": str(home), "PATH": "/usr/bin:/bin:/opt/homebrew/bin", "FAKE_EXIT": str(fake_exit)},
                          timeout=60)


def test_the_box_runs_exactly_the_gates_commit_from_a_small_bundle_and_keeps_nothing(repo, box_home):
    mac, base = repo
    commit(mac, "pr.txt")
    sha = commit(mac, "pr2.txt")
    bundle = br.make_bundle(str(mac), sha, base)
    assert len(bundle) < 5000                                  # only the PR's commits, not the repo
    r = run_box_side(box_home, base64.b64encode(bundle).decode())
    assert r.returncode == 0, r.stderr
    assert f"ran on {sha} gate=1 args=-m pytest -q -n 8 -p no:cacheprovider" in r.stdout and "pr.txt" in r.stdout
    assert refs(mac) == ""                                     # the bundle's temporary ref is gone
    # the box's own checkout is untouched: same HEAD, no new refs, no worktrees
    box = box_home / ".agents"
    assert subprocess.run(["git", "-C", str(box), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() == base
    assert refs(box) == ""


def test_a_red_suite_on_the_box_keeps_its_exit_code(repo, box_home):
    mac, base = repo
    sha = commit(mac, "pr.txt")
    r = run_box_side(box_home, base64.b64encode(br.make_bundle(str(mac), sha, base)).decode(), fake_exit=1)
    assert r.returncode == 1


def test_a_garbled_hand_off_is_exit_3_not_a_test_failure(box_home):
    r = run_box_side(box_home, "this is not base64 of a bundle")
    assert r.returncode == 3


def test_a_box_checkout_ahead_of_the_gates_base_still_gets_a_usable_bundle(repo, box_home):
    mac, base = repo
    sha = commit(mac, "pr.txt")
    subprocess.run([*GIT, "-C", str(mac), "checkout", "-q", "-b", "main-moved", base], check=True)
    ahead = commit(mac, "main-later.txt")                     # main moved on after the gate fetched
    subprocess.run(["git", "-C", str(box_home / ".agents"), "fetch", "-q", str(mac), "main-moved"], check=True)
    subprocess.run(["git", "-C", str(box_home / ".agents"), "checkout", "-q", ahead], check=True)
    r = run_box_side(box_home, base64.b64encode(br.make_bundle(str(mac), sha, ahead)).decode())
    assert r.returncode == 0 and f"ran on {sha}" in r.stdout


def test_a_box_that_already_has_the_commit_still_gets_a_bundle(repo, box_home):
    mac, base = repo
    r = run_box_side(box_home, base64.b64encode(br.make_bundle(str(mac), base, base)).decode())
    assert r.returncode == 0 and f"ran on {base}" in r.stdout


def test_an_unknown_box_checkout_refuses_rather_than_shipping_the_whole_repo(repo):
    mac, base = repo
    with pytest.raises(RuntimeError, match="not known"):
        br.make_bundle(str(mac), base, "0" * 40)
    with pytest.raises(RuntimeError):
        br.make_bundle(str(mac), base, None)


# ── run: whatever happens, one record, the pin released, the gate untouched ──────────────────────────────────

def pinned(mac, sha, run_id="r1"):
    subprocess.run(["git", "-C", str(mac), "update-ref", f"refs/box-runs/{run_id}", sha], check=True)


@pytest.mark.parametrize("result,outcome", [
    (td.DispatchResult(ok=True, device_id="mac-mini-2012", output="commit x\n12 passed in 150s"), "passed"),
    (td.DispatchResult(ok=False, device_id="mac-mini-2012", timed_out=True, error="timed out after 480s"), "timeout"),
    (td.DispatchResult(ok=False, device_id="mac-mini-2012", unreachable=True, error="exit 255"), "offline"),
    (td.DispatchResult(ok=False, device_id="mac-mini-2012", error="exit 1: ", output="FAILED a.py::t\n1 failed"), "failed"),
])
def test_a_run_records_its_outcome_and_always_releases_its_pin(repo, log, result, outcome):
    mac, base = repo
    sha = commit(mac, "pr.txt")
    pinned(mac, sha)
    seen = {}

    def dispatch(cmd, **kw):
        seen.update(kw)
        return result
    entry = br.run("r1", str(mac), sha, "PR #1", dispatch=dispatch, head=lambda: base)
    assert entry["outcome"] == outcome and refs(mac) == ""
    assert seen["fallback"] is False and seen["need"] == "test" and seen["timeout"] == 480
    assert base64.b64decode(seen["stdin"])[:20].startswith(b"# v")   # a git bundle header
    (rec,) = [l for l in lines(log) if l["event"] == "box"]
    assert rec["outcome"] == outcome and rec["sha"] == sha and "seconds" in rec


def test_a_box_that_cannot_be_asked_is_offline_and_nothing_is_sent(repo, log):
    mac, base = repo
    pinned(mac, base)
    entry = br.run("r1", str(mac), base, "PR #1", dispatch=lambda *a, **k: pytest.fail("nothing to send"),
                   head=lambda: None)
    assert entry["outcome"] == "offline" and refs(mac) == ""


def test_a_run_that_blows_up_is_an_error_record_not_a_crash(repo, log):
    mac, base = repo
    pinned(mac, base)

    def boom(*a, **k):
        raise OSError("ssh exploded")
    entry = br.run("r1", str(mac), base, "PR #1", dispatch=boom, head=lambda: base)
    assert entry["outcome"] == "error" and "ssh exploded" in entry["error"] and refs(mac) == ""


# ── submit: quick, detached, never raises into the gate ──────────────────────────────────────────────────────

def test_submit_pins_the_commit_and_starts_the_run_detached(repo, log):
    mac, base = repo
    spawned = []
    out = br.submit(str(mac), "PR #7", spawn=lambda argv, **kw: spawned.append((argv, kw)))
    assert out["sha"] == base and refs(mac).endswith(f"refs/box-runs/{out['id']}")
    (argv, kw), = spawned
    assert argv[1].endswith("box_runner.py") and argv[2:4] == ["run", out["id"]] and kw["start_new_session"] is True
    assert argv[argv.index("--repo") + 1] == str(mac.resolve()) or argv[argv.index("--repo") + 1] == str(mac)
    assert lines(log)[0]["event"] == "sent"


def test_submit_from_a_worktree_pins_in_the_main_repo(repo, tmp_path):
    # The gate's clone is a `git worktree` of the shared checkout: the pin must outlive the worktree.
    mac, base = repo
    wt = tmp_path / "gate-clone"
    subprocess.run(["git", "-C", str(mac), "worktree", "add", "-q", "--detach", str(wt), "HEAD"], check=True)
    spawned = []
    out = br.submit(str(wt), "PR #8", spawn=lambda argv, **kw: spawned.append(argv))
    subprocess.run(["git", "-C", str(mac), "worktree", "remove", "--force", str(wt)], check=True)
    assert refs(mac).endswith(f"refs/box-runs/{out['id']}")
    assert spawned[0][spawned[0].index("--repo") + 1] in (str(mac), str(mac.resolve()))


def test_two_gates_at_once_get_separate_runs(repo):
    mac, base = repo
    a = br.submit(str(mac), "PR #1", spawn=lambda *a, **k: None)
    b = br.submit(str(mac), "PR #2", spawn=lambda *a, **k: None)
    assert a["id"] != b["id"] and len(refs(mac).splitlines()) == 2


def test_submit_never_raises_into_the_gate(tmp_path, log):
    assert br.submit(str(tmp_path / "not-a-repo"), "PR #1", spawn=lambda *a, **k: pytest.fail("no spawn")) is None
    assert lines(log)[-1]["outcome"] == "error"

    def spawn_fails(*a, **k):
        raise OSError("fork failed")
    subprocess.run(["git", "init", "-q", str(tmp_path / "r")], check=True)
    commit(tmp_path / "r", "x")
    assert br.submit(str(tmp_path / "r"), "PR #1", spawn=spawn_fails) is None


def test_it_can_be_switched_off(repo, monkeypatch):
    monkeypatch.setenv("MARVIN_BOX_RUNNER", "off")
    assert br.submit(str(repo[0]), "PR #1", spawn=lambda *a, **k: pytest.fail("off")) is None


def test_submit_is_fast(repo):
    import time
    t = time.monotonic()
    br.submit(str(repo[0]), "PR #1", spawn=lambda *a, **k: None)
    assert time.monotonic() - t < 2.0


# ── box vs Mac ───────────────────────────────────────────────────────────────────────────────────────────────

def box_line(sha, outcome, failing=()):
    """What run() does when the box finishes: record, then compare."""
    br._append({"event": "box", "sha": sha, "label": "PR #1", "outcome": outcome, "failing": list(failing)})
    br.compare(sha)


def test_agreement_is_recorded_once_whichever_finishes_last(log):
    br.verdict("s1", "passed")
    box_line("s1", "passed")
    assert br.compare("s1") is None                       # once per pair: box_line already compared
    assert len([l for l in lines(log) if l["event"] == "compare"]) == 1


def test_a_box_failure_the_mac_did_not_have_is_a_disagreement(log):
    box_line("s2", "failed", ["lib/tests/test_x.py::t"])
    br.verdict("s2", "passed")
    (c,) = [l for l in lines(log) if l["event"] == "compare"]
    assert c["agree"] is False and c["box_only"] == ["lib/tests/test_x.py::t"] and c["mac_only"] == []


def test_a_mac_failure_the_box_did_not_have_is_a_disagreement(log):
    br.verdict("s3", "failed", "FAILED lib/tests/test_y.py::t - boom\n")
    box_line("s3", "passed")
    c = [l for l in lines(log) if l["event"] == "compare"][0]
    assert c["agree"] is False and c["mac_only"] == ["lib/tests/test_y.py::t"]


def test_both_red_on_different_tests_is_still_a_disagreement(log):
    br.verdict("s4", "failed", "FAILED a.py::t1\n")
    box_line("s4", "failed", ["a.py::t2"])
    c = [l for l in lines(log) if l["event"] == "compare"][0]
    assert c["agree"] is False


@pytest.mark.parametrize("outcome", ["timeout", "offline", "error"])
def test_a_box_with_no_result_is_not_counted_as_agreeing_or_not(log, outcome):
    br.verdict("s5", "failed", "FAILED a.py::t\n")
    box_line("s5", outcome)
    assert [l for l in lines(log) if l["event"] == "compare"][0]["agree"] is None


def test_show_puts_disagreements_first(log):
    br.verdict("a" * 40, "passed")
    box_line("a" * 40, "passed")
    br.verdict("b" * 40, "passed")
    box_line("b" * 40, "failed", ["x.py::t"])
    table = br.show().splitlines()
    assert "**NO**" in table[2] and "x.py::t" in table[2] and "yes" in table[3]


def test_verdict_cli_reads_failures_from_stdin(log, monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("FAILED a.py::t - x\n"))
    br.main(["verdict", "--sha", "s6", "--outcome", "failed"])
    assert lines(log)[0]["failing"] == ["a.py::t"]
