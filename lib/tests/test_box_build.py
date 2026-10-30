"""box_build: ticket builds on mac-mini-2012, each in a disposable VM (marvin #951, ADR 0069 amendment 2).

These try to break it: a secret reaching argv, a log or the result; the VM hanging, the box dropping off, the bot token
missing or rejected; two builds racing for the one slot; a macOS ticket routed to the box; a crash leaving the claim."""
from __future__ import annotations

import io
import json
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import box_build as bb
import dispatch_concurrency as dc

BOT = "ghp_" + "b" * 36
OAUTH = "sk-ant-oat01-" + "o" * 40
APIKEY = "sk-ant-api03-" + "k" * 40
SHA = "a" * 40
ON = {**dc.DEFAULTS, "box_builds": {**dc.DEFAULTS["box_builds"], "slots": 1}}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name, rel in (("RECORDS_DIR", "dispatch/box"), ("LANE_PATH", "dispatch/box-lane.json"),
                      ("LOG_PATH", "logs/box-builds.jsonl"), ("RUN_LOGS", "logs/box-builds"),
                      ("BILLING_LOG", "logs/builder-billing.jsonl"), ("BOX_LOCK", "cache/box-build.lock")):
        monkeypatch.setattr(bb, name, tmp_path / rel)
    for name, value in (("BOT_TOKEN", BOT), ("OAUTH_TOKEN", OAUTH), ("API_KEY", APIKEY)):
        f = tmp_path / f".{name.lower()}"
        f.write_text(value + "\n")
        monkeypatch.setattr(bb, name, f)
    return tmp_path


def ticket(n=7, labels=("ready-for-agent", "linux-ok"), title="Fix the stage log parser", body="lib/ticket_stages.py"):
    return {"number": n, "title": title, "body": body, "labels": [{"name": l} for l in labels]}


def route(t=None, settings=ON, profile={"linux_ok": True}, accepts=("test", "box-build"), online=("mac-mini-2012",),
          in_flight=(), tokens=True, repo="G-Eskayo/marvin"):
    reg = {"mac-mini-2012": {"tailscale_hostname": "mac-mini-2012", "accepts": list(accepts), "is_self": False}}
    return bb.routes(repo, t or ticket(), settings, load_profile=lambda r: profile, registry=lambda: reg,
                     online=lambda: set(online), in_flight=lambda: list(in_flight), has_tokens=lambda: tokens)


# ── routing ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_labelled_python_ticket_of_an_opted_in_project_goes_to_the_box():
    assert route() == (True, None)


@pytest.mark.parametrize("profile", [None, {}, {"linux_ok": False}, {"linux_ok": "true"}, {"linux_ok": 1}, "junk"])
def test_only_a_project_that_opted_in_with_a_real_true(profile):
    ok, why = route(profile=profile)
    assert not ok and "opted in" in why


def test_an_unlabelled_ticket_stays_on_the_macs():
    ok, why = route(ticket(labels=("ready-for-agent",)))
    assert not ok and "linux-ok" in why


@pytest.mark.parametrize("title,body,labels", [
    ("Add a SwiftUI settings pane", "", ()),
    ("Fix crash", "Repro in Xcode 26 then rerun xcodebuild", ()),
    ("launchd job for the sweep", "write a plist", ()),
    ("Keychain read", "uses the macOS keychain", ()),
    ("Dashboard button", "dashboard/src/App.jsx", ()),
    ("Fix", "edit Sources/App/Main.swift", ()),
    ("Fix", "nothing special", ("ui",)),
    ("Fix", "nothing special", ("MacOS",)),
    ("Fix the brain-map", "", ()),
    ("vitest flake", "", ()),
    ("iOS widget", "", ()),
])
def test_anything_that_smells_of_macos_stays_on_a_mac_even_when_labelled_linux_ok(title, body, labels):
    ok, why = route(ticket(title=title, body=body, labels=("linux-ok", *labels)))
    assert not ok and "Mac" in why


@pytest.mark.parametrize("text", ["Fix the iostat parser", "the mbrewer util", "scenarios.py", "biosphere", "jsonl"])
def test_words_that_only_contain_a_mac_word_do_not_block(text):
    assert route(ticket(title=text, body=text))[0]


def test_the_box_must_accept_box_build_work_in_the_registry():
    ok, why = route(accepts=("test", "bench"))
    assert not ok and "box-build" in why


def test_an_offline_box_or_unreadable_tailscale_is_no():
    assert not route(online=())[0]
    assert route(online=("gils-mac-mini",))[1].endswith("offline")


def test_one_build_at_a_time():
    ok, why = route(in_flight=[{"run_id": "x"}])
    assert not ok and "full" in why


@pytest.mark.parametrize("slots", [0, 2, -1, True, "1"])
def test_box_slots_are_off_or_one(slots):
    s, problems = dc.validate({"box_builds": {"slots": slots}})
    assert dc.box_slots(s) == (0 if slots != 0 else 0)
    if slots != 0:
        assert problems


def test_box_builds_are_off_by_default():
    assert dc.box_slots(dc.load(Path("/nonexistent"))) == 0
    assert not route(settings=dc.DEFAULTS)[0]


def test_no_tokens_on_this_mac_means_no_box_build():
    ok, why = route(tokens=False)
    assert not ok and "token" in why


def test_a_resting_lane_says_why_until_it_is_over(isolated):
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    bb.rest_lane("disk", "3 GB free", now=now)
    assert "3 GB free" in bb.lane_down(now + timedelta(minutes=59))
    assert bb.lane_down(now + timedelta(minutes=61)) is None
    bb.LANE_PATH.write_text("{corrupt")
    assert bb.lane_down(now) is None


def test_a_busy_refusal_never_rests_the_lane():
    bb.rest_lane("busy", "someone else")
    assert bb.lane_down() is None


def test_a_crashing_profile_reader_is_no_not_a_crash():
    def boom(r):
        raise OSError("disk gone")
    ok, why = bb.routes("G-Eskayo/marvin", ticket(), ON, load_profile=boom)
    assert not ok


def test_running_reaps_records_of_dead_runners(isolated):
    d = bb.RECORDS_DIR
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({"pid": os.getpid(), "ticket": 1, "repo": "G-Eskayo/marvin"}))
    (d / "b.json").write_text(json.dumps({"pid": 999_999_9, "ticket": 2}))
    (d / "c.json").write_text("{broken")
    assert [r["ticket"] for r in bb.running()] == [1]
    assert sorted(p.name for p in d.iterdir()) == ["a.json"]


# ── the plan-first login ────────────────────────────────────────────────────────────────────────────────────────

def test_the_plan_login_while_a_plan_slot_is_free():
    assert bb.choose_login(0, ON)[0] == "CLAUDE_CODE_OAUTH_TOKEN"


def test_the_api_key_only_beyond_the_plan_slots_with_credit_slots_and_a_ready_credit():
    with_credit = {**ON, "credit_slots": {"mac-mini-2012": 1}}
    assert bb.choose_login(1, ON, credit_ready=lambda: True)[2] == "plan"            # no credit slots on the box
    assert bb.choose_login(1, with_credit, credit_ready=lambda: False)[2] == "plan"  # credit not ready
    assert bb.choose_login(1, with_credit, credit_ready=lambda: True)[0] == "ANTHROPIC_API_KEY"

    def boom():
        raise RuntimeError("unreadable")
    assert bb.choose_login(1, with_credit, credit_ready=boom)[2] == "plan"


# ── the Mac side: secrets, outcomes, settling ───────────────────────────────────────────────────────────────────

class FakeSSH:
    def __init__(self, stdout="", returncode=0, raises=None):
        self.stdout, self.returncode, self.raises, self.calls = stdout, returncode, raises, []

    def __call__(self, cmd, input=None, **kw):
        self.calls.append((cmd, input))
        if self.raises:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="")


def box_says(**result):
    return "lots of build output\n" + bb.RESULT_PREFIX + json.dumps(result) + "\n"


def run_box(ssh, **kw):
    settled, failures, labelled = [], [], []
    r = bb.run("G-Eskayo/marvin#7", "abc123def456", settings=ON, ssh=ssh, sha=SHA,
               settle=lambda n, outcome, findings, **k: settled.append((n, outcome, findings, k)) or outcome,
               record_failure=lambda n, reason, **k: failures.append(reason),
               label_pr=lambda url, result: labelled.append(url), **kw)
    return r, settled, failures, labelled


PR = "https://github.com/G-Eskayo/marvin/pull/999"


def test_the_secrets_go_only_through_stdin_never_the_command_line():
    ssh = FakeSSH(box_says(outcome={"raised": True, "pr_url": PR, "reason": None, "findings": []}))
    run_box(ssh)
    cmd, stdin = ssh.calls[0]
    flat = " ".join(cmd)
    assert BOT not in flat and OAUTH not in flat and APIKEY not in flat
    assert stdin == f"{BOT}\n{OAUTH}\n"
    assert "--login CLAUDE_CODE_OAUTH_TOKEN" in flat and "\"$HOME/.agents/lib/box_build.py\" vm 'G-Eskayo/marvin#7'" in flat


@pytest.mark.parametrize("path", ["$(reboot)", "/tmp/x; id", "~/x y", "/tmp/`id`", 'x"y'])
def test_a_box_engine_path_that_could_run_a_command_is_refused(path):
    ssh = FakeSSH()
    _, settled, _, _ = run_box(ssh, box_agents=path)
    assert ssh.calls == [] and not settled[0][1]["raised"]


def test_a_raised_pr_settles_as_raised_with_the_box_claim_and_is_labelled():
    r, settled, failures, labelled = run_box(FakeSSH(box_says(
        outcome={"raised": True, "pr_url": PR, "reason": None, "findings": []}, vm_wall_s=1200, vm_peak_rss_mb=3000)))
    assert settled[0][1]["raised"] and settled[0][3]["claim_label"] == "mac-mini-2012"
    assert settled[0][3]["run_id"] == "abc123def456"
    assert labelled == [PR] and failures == []
    assert bb.lane_down() is None


def test_a_secret_echoed_by_the_build_never_reaches_the_saved_log_or_the_jsonl(isolated):
    out = f"debug: token is {BOT} and {OAUTH}\n" + bb.RESULT_PREFIX + json.dumps(
        {"outcome": {"raised": False, "pr_url": None, "reason": f"failed with {BOT}", "findings": []}})
    run_box(FakeSSH(out))
    for f in [*bb.RUN_LOGS.glob("*"), bb.LOG_PATH]:
        text = f.read_text()
        assert BOT not in text and OAUTH not in text, f


def test_a_build_failure_is_the_tickets_and_settles_like_any_failed_run():
    _, settled, failures, labelled = run_box(FakeSSH(box_says(
        outcome={"raised": False, "pr_url": None, "reason": "tests failed", "findings": ["fix x"]})))
    n, outcome, findings, _ = settled[0]
    assert outcome == {"raised": False, "pr_url": None, "reason": "tests failed"} and findings == ["fix x"]
    assert failures == [] and labelled == [], "settle feeds the breaker for a ticket failure, not the box runner"


@pytest.mark.parametrize("ssh,why", [
    (FakeSSH(raises=subprocess.TimeoutExpired("ssh", 10)), "didn't answer"),
    (FakeSSH("", returncode=255), "dropped off"),
    (FakeSSH("", returncode=124), "timed out on the box"),
    (FakeSSH("half a line", returncode=1), "without a result"),
    (FakeSSH(box_says(vm_ok=False, vm_error="command timed out")), "command timed out"),
    (FakeSSH(box_says(outcome={"raised": True, "pr_url": "javascript:alert(1)"})), "no PR link"),
    (FakeSSH(bb.RESULT_PREFIX + "{not json"), "without a result"),
])
def test_a_hung_crashed_or_vanished_box_build_releases_without_a_strike_feeds_the_breaker_and_rests_the_lane(ssh, why):
    _, settled, failures, labelled = run_box(ssh)
    outcome = settled[0][1]
    assert outcome["timed_out"] and not outcome["raised"] and why in outcome["reason"]
    assert failures and why in failures[0], "the same box failure across tickets must trip the breaker (#881)"
    assert "rests until" in bb.lane_down() and labelled == []


@pytest.mark.parametrize("refused,rests", [("busy", False), ("memory", True), ("disk", True), ("no-image", True),
                                           ("bot-token-rejected", True), ("engine-sha", True)])
def test_a_refusal_releases_with_no_strike_no_comment_no_breaker(refused, rests):
    _, settled, failures, _ = run_box(FakeSSH(box_says(refused=refused, why="because")))
    outcome = settled[0][1]
    assert outcome["env_missing"] and not outcome["raised"] and failures == []
    assert (bb.lane_down() is not None) == rests


def test_an_unknown_refusal_counts_as_the_boxs_failure_and_feeds_the_breaker():
    _, settled, failures, _ = run_box(FakeSSH(box_says(refused="something-new")))
    assert settled[0][1]["timed_out"] and failures


def test_a_missing_bot_token_never_calls_the_box_and_still_settles(isolated):
    bb.BOT_TOKEN.write_text("")
    ssh = FakeSSH()
    _, settled, failures, _ = run_box(ssh)
    assert ssh.calls == [] and settled[0][1]["env_missing"] and "bot token" in settled[0][1]["reason"]
    assert bb.lane_down()


def test_a_token_file_with_two_lines_counts_as_missing(isolated):
    bb.BOT_TOKEN.write_text(f"{BOT}\nexport EVIL=1\n")
    ssh = FakeSSH()
    run_box(ssh)
    assert ssh.calls == []


def test_a_crash_in_the_runner_still_settles_and_removes_its_record(isolated, monkeypatch):
    monkeypatch.setattr(bb, "choose_login", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _, settled, failures, _ = run_box(FakeSSH())
    assert settled and settled[0][1]["timed_out"] and "crashed" in settled[0][1]["reason"]
    assert not list(bb.RECORDS_DIR.glob("*.json"))


def test_a_settle_that_crashes_is_reported_not_raised():
    def bad_settle(*a, **k):
        raise RuntimeError("gh down")
    r = bb.run("G-Eskayo/marvin#7", "abc123def456", settings=ON, ssh=FakeSSH(box_says(outcome={"raised": False})),
               sha=SHA, settle=bad_settle, record_failure=lambda *a, **k: None, label_pr=lambda *a: None)
    assert "settle_error" in r


def test_the_record_exists_while_the_box_works_and_is_gone_after(isolated):
    seen = []

    def ssh(cmd, input=None, **kw):
        seen.extend(json.loads(p.read_text())["ticket"] for p in bb.RECORDS_DIR.glob("*.json"))
        return SimpleNamespace(returncode=0, stdout=box_says(outcome={"raised": False}), stderr="")
    run_box(ssh)
    assert seen == [7] and not list(bb.RECORDS_DIR.glob("*.json"))


@pytest.mark.parametrize("run_id", ["", "../../x", "ABC", "a b"])
def test_a_bad_run_id_never_reaches_the_box(run_id):
    ssh = FakeSSH()
    settled = []
    bb.run("G-Eskayo/marvin#7", run_id, settings=ON, ssh=ssh, sha=SHA,
           settle=lambda n, o, f, **k: settled.append(o) or o, record_failure=lambda *a, **k: None)
    assert ssh.calls == [] and settled and not settled[0]["raised"]


def test_the_plan_choice_is_logged_without_the_key(isolated):
    run_box(FakeSSH(box_says(outcome={"raised": False})))
    line = json.loads(bb.BILLING_LOG.read_text().splitlines()[-1])
    assert line["mode"] == "plan" and line["task"] == "box-abc123def456" and OAUTH not in bb.BILLING_LOG.read_text()


# ── the box side ────────────────────────────────────────────────────────────────────────────────────────────────

class FakeVM:
    def __init__(self, output="", ok=True, error="", golden=True, runs_dir=None):
        self.output, self.ok, self.error, self.calls, self.swept = output, ok, error, [], 0
        self._golden = golden
        self.RUNS_DIR = runs_dir or Path("/nonexistent")

    def golden_path(self, image):
        return Path(__file__) if self._golden else Path("/nonexistent/marvin-build.qcow2")

    def sweep(self):
        self.swept += 1
        return ["run-marvin-build-0badf00d"]

    def run(self, image, command, **kw):
        self.calls.append((image, command, kw))
        return SimpleNamespace(ok=self.ok, output=self.output, error=self.error, exit_code=0 if self.ok else 1)


def vm_outcome(**o):
    return "build log\n" + bb.OUTCOME_PREFIX + json.dumps({"raised": True, "pr_url": PR, "reason": None, **o}) + "\n"


class NoSampler:
    peak_used = min_avail = peak_rss = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def box(vm=None, stdin=f"{BOT}\n{OAUTH}\n", login="CLAUDE_CODE_OAUTH_TOKEN", avail=12000, free=100.0, **kw):
    return bb.box_vm("G-Eskayo/marvin#7", SHA, "abc123def456", login, timeout=3600, memory_mb=6144, vcpus=4,
                     min_disk_gb=15, reserve_mb=3072, stdin=io.StringIO(stdin), vm=vm or FakeVM(vm_outcome()),
                     meminfo=lambda: {"MemTotal": 16000, "MemAvailable": avail}, disk_free_gb=lambda: free,
                     sampler=NoSampler(), **kw)


def test_the_box_runs_the_build_image_with_both_secrets_as_names_only():
    vm = FakeVM(vm_outcome())
    r = box(vm)
    image, command, kw = vm.calls[0]
    assert image == "marvin-build" and kw["secrets"] == {"GH_TOKEN": BOT, "CLAUDE_CODE_OAUTH_TOKEN": OAUTH}
    assert BOT not in command and OAUTH not in command
    assert r["outcome"]["raised"] and r["swept"] == ["run-marvin-build-0badf00d"]


def test_the_vm_output_is_scrubbed_before_it_leaves_the_box():
    r = box(FakeVM(f"oops {BOT} {OAUTH}\n" + vm_outcome(), error=f"bad {BOT}", ok=False))
    assert BOT not in json.dumps(r) and OAUTH not in json.dumps(r)


def test_two_builds_racing_for_the_slot_one_is_refused_busy(isolated):
    gate, results = threading.Event(), []

    class SlowVM(FakeVM):
        def run(self, *a, **k):
            gate.wait(5)
            return super().run(*a, **k)

    t = threading.Thread(target=lambda: results.append(box(SlowVM(vm_outcome()))))
    t.start()
    import time
    for _ in range(100):
        if bb.BOX_LOCK.exists():
            break
        time.sleep(0.01)
    time.sleep(0.05)
    second = box(FakeVM(vm_outcome()))
    gate.set()
    t.join()
    assert second["refused"] == "busy" and results[0]["outcome"]["raised"]
    assert box(FakeVM(vm_outcome()))["outcome"]["raised"], "the slot frees when the first ends"


@pytest.mark.parametrize("stdin", ["", f"{BOT}\n", f"\n{OAUTH}\n"])
def test_a_missing_secret_on_stdin_is_refused_before_any_vm(stdin):
    vm = FakeVM()
    assert box(vm, stdin=stdin)["refused"] == "no-secret" and vm.calls == []


def test_an_unknown_login_name_is_refused():
    vm = FakeVM()
    assert box(vm, login="PATH")["refused"] == "no-secret" and vm.calls == []


def test_no_room_in_memory_or_disk_or_no_image_is_refused_before_any_vm():
    for kw, kind in (({"avail": 8000}, "memory"), ({"free": 3.0}, "disk"), ({"vm": FakeVM(golden=False)}, "no-image")):
        vm = kw.get("vm") or FakeVM()
        r = box(**{**kw, "vm": vm})
        assert r["refused"] == kind and vm.calls == [], kind


def test_a_rejected_bot_token_inside_the_vm_is_a_refusal_not_a_ticket_failure():
    r = box(FakeVM("x\n" + bb.REFUSED_PREFIX + "bot-token-rejected\n"))
    assert r["refused"] == "bot-token-rejected"


@pytest.mark.parametrize("ref,sha,run_id", [
    ("G-Eskayo/marvin#7; rm -rf ~", SHA, "abc123"),
    ("G-Eskayo/marvin#7", "$(reboot)" + "a" * 31, "abc123"),
    ("G-Eskayo/marvin#7", SHA, "abc123;id"),
    ("G-Eskayo/marvin#0", SHA, "abc123"),
])
def test_nothing_unchecked_reaches_the_vm_shell(ref, sha, run_id):
    with pytest.raises(ValueError):
        bb.vm_command(ref, sha, run_id)


def test_the_vm_command_pushes_as_the_bot_and_checks_the_token_first():
    cmd = bb.vm_command("G-Eskayo/marvin#7", SHA, "abc123def456")
    assert cmd.index("gh api user") < cmd.index("run_ticket.py --build-only")
    assert "credential.helper" in cmd and "users.noreply.github.com" in cmd and f"checkout -q --detach {SHA}" in cmd


def test_a_vm_that_ended_without_an_outcome_line_gives_no_outcome():
    r = box(FakeVM("Traceback ...", ok=False, error="command exited 1"))
    assert "outcome" not in r and r["vm_error"] == "command exited 1"
    outcome, _, kind, _ = bb.classify(0, bb.RESULT_PREFIX + json.dumps(r))
    assert kind == "infra" and outcome["timed_out"]


def test_the_sampler_keeps_the_peaks():
    readings = iter([{"MemTotal": 16000, "MemAvailable": a} for a in (12000, 7000, 9000, 9000)])
    s = bb.Sampler(every=0.001, meminfo=lambda: next(readings, {"MemTotal": 16000, "MemAvailable": 9000}),
                   vm_rss=lambda: 3000)
    s.sample()
    s.sample()
    s.sample()
    assert s.peak_used == 9000 and s.min_avail == 7000 and s.peak_rss == 3000


# ── the dispatching Mac going away (found live 2026-10-30: the box kept building after the Mac's runner died) ─────

def test_ssh_holding_stdin_writes_the_secrets_and_keeps_stdin_open_until_the_end():
    import sys
    child = ("import sys, select\n"
             "a, b = sys.stdin.readline().strip(), sys.stdin.readline().strip()\n"
             "r, _, _ = select.select([sys.stdin], [], [], 0.5)\n"
             "print(a, b, 'closed' if r and not sys.stdin.read(1) else 'open')\n")
    r = bb.ssh_holding_stdin([sys.executable, "-c", child], input="one\ntwo\n", timeout=20)
    assert r.returncode == 0 and r.stdout.strip() == "one two open"


def test_ssh_holding_stdin_kills_a_hung_child_on_timeout():
    import sys
    with pytest.raises(subprocess.TimeoutExpired):
        bb.ssh_holding_stdin([sys.executable, "-c", "import time; time.sleep(30)"], input="x\n", timeout=0.5)


def test_the_box_tears_down_when_its_stdin_closes():
    r, w = os.pipe()
    killed = threading.Event()
    with os.fdopen(r) as rf:
        t = bb._watch_for_hangup(rf, kill=lambda pid, sig: killed.set())
        assert not killed.wait(0.3), "an open link must not stop the build"
        os.close(w)
        assert killed.wait(5), "EOF means the Mac is gone: stop and clean up"
        t.join(2)


def test_a_stopped_mac_runner_settles_as_the_boxs_failure_and_removes_its_record(isolated):
    def ssh(cmd, input=None, **kw):
        raise bb._Stopped("signal 15")
    _, settled, failures, _ = run_box(ssh)
    assert settled[0][1]["timed_out"] and "stopped" in settled[0][1]["reason"] and failures
    assert not list(bb.RECORDS_DIR.glob("*.json"))


def test_the_vm_ignores_only_the_tests_that_need_the_private_claude_folder():
    cmd = bb.vm_command("G-Eskayo/marvin#7", SHA, "abc123def456")
    assert "PYTEST_ADDOPTS='-n 4 --ignore=lib/tests/test_find_file.py';" in cmd
    assert "PYTEST_ADDOPTS='-n 6 " in bb.vm_command("G-Eskayo/marvin#7", SHA, "abc123def456", workers=6)
    for bad in (0, 9, True, "4; id"):
        with pytest.raises(ValueError):
            bb.vm_command("G-Eskayo/marvin#7", SHA, "abc123def456", workers=bad)
