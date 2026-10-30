"""ADR 0069 amendment (marvin #930): test and bench work sent to mac-mini-2012 gets a timeout and, when the box stalls
or can't be reached, reruns once on the less busy Mac with the fallback logged. quarantine and security never fall
back: a Mac must never run untrusted code.

The world here is three registry entries and a fake network: which hosts Tailscale says are online, what each
dispatch-state file says, and what each machine does when a script is run on it. The dispatch logic under test is
the real one."""
import json
import os
import subprocess
import time

import pytest

import task_dispatch as td

MINI = {"tailscale_hostname": "gils-mac-mini", "kind": "desktop", "os": "macos", "accepts": ["general", "macos"]}
MBP = {"tailscale_hostname": "mbp", "kind": "laptop", "os": "macos", "accepts": ["general", "macos"]}
BOX = {"tailscale_hostname": "mac-mini-2012", "kind": "desktop", "os": "linux",
       "accepts": ["security", "quarantine", "test", "bench"]}


class World:
    """Who is online, who is busy, what each machine's load reads, and what happens when work runs on it."""

    def __init__(self, monkeypatch, tmp_path, *, self_id="macbook-pro-1"):
        self.online = {"gils-mac-mini", "mbp", "mac-mini-2012"}
        self.busy = set()
        self.load = {"mac-mini-1": (1.0, 10, 0), "macbook-pro-1": (1.0, 8, 0)}   # (1-min load, cores, runs)
        self.behaviour = {}   # device -> callable(timeout) -> DispatchResult
        self.ran = []         # (device, timeout) in order
        self.self_id = self_id
        devices = {"mac-mini-1": MINI, "macbook-pro-1": MBP, "mac-mini-2012": BOX}

        def candidates():
            return {d: {**info, "is_self": d == self_id, **({"tailscale_hostname": None} if d == self_id else {})}
                    for d, info in devices.items()}

        monkeypatch.setattr(td, "_candidates", candidates)
        monkeypatch.setattr(td, "registry_id", lambda: self_id)
        monkeypatch.setattr(td, "_tailscale_online_hosts", lambda: set(self.online))
        host_of = {info["tailscale_hostname"]: d for d, info in devices.items()}
        monkeypatch.setattr(td, "_read_remote_dispatch_state", lambda host: {"busy": host_of[host] in self.busy})
        monkeypatch.setattr(td, "_read_local_dispatch_state", lambda: {"busy": self_id in self.busy})
        monkeypatch.setattr(td, "machine_load", lambda device_id, info: self.load.get(device_id))

        def run_remote(host, script, mode, timeout, device_id, remote_os="macos"):
            self.ran.append((device_id, timeout))
            return self.behaviour.get(device_id, lambda t: td.DispatchResult(ok=True, device_id=device_id, output="ok"))(timeout)

        def run_local(script, mode, timeout):
            self.ran.append((self_id, timeout))
            return self.behaviour.get(self_id, lambda t: td.DispatchResult(ok=True, device_id=self_id, output="ok"))(timeout)

        monkeypatch.setattr(td, "_run_remote", run_remote)
        monkeypatch.setattr(td, "_run_local", run_local)
        import memory_guard
        monkeypatch.setattr(memory_guard, "guard", lambda *a, **k: {"ok": True, "queued": False, "message": ""})
        self.log = tmp_path / "dispatch-fallback.jsonl"
        monkeypatch.setattr(td, "FALLBACK_LOG", self.log)
        monkeypatch.setattr(td, "FALLBACK_RUNS_DIR", tmp_path / "fallback-runs")

    def lines(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []


def hangs(device):
    return lambda t: td.DispatchResult(ok=False, device_id=device, error=f"timed out after {t}s", timed_out=True)


def drops(device):
    return lambda t: td.DispatchResult(ok=False, device_id=device, error="exit 255: Connection reset", unreachable=True)


@pytest.fixture
def world(monkeypatch, tmp_path):
    return World(monkeypatch, tmp_path)


# ── test and bench: fall back ────────────────────────────────────────────────────────────────────────────────

def test_a_healthy_box_runs_test_work_and_nothing_falls_back(world):
    r = td.dispatch("pytest lib -n 8", need="test", timeout=480)
    assert r.ok and r.device_id == "mac-mini-2012"
    assert world.ran == [("mac-mini-2012", 480)]
    assert world.lines() == []


def test_a_box_hanging_past_its_timeout_reruns_the_same_job_once_on_the_less_busy_mac(world):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    world.load = {"mac-mini-1": (9.0, 10, 1), "macbook-pro-1": (1.0, 8, 0)}   # the Mini is busier
    r = td.dispatch("pytest lib -n 8", need="test", timeout=480)
    assert r.ok and r.device_id == "macbook-pro-1"
    assert r.fell_back_from == "mac-mini-2012"
    assert world.ran == [("mac-mini-2012", 480), ("macbook-pro-1", 480)]
    (line,) = world.lines()
    assert line["need"] == "test" and line["from"] == "mac-mini-2012" and line["to"] == "macbook-pro-1"
    assert line["reason"] == "timeout" and line["outcome"] == "ok"


def test_a_box_that_drops_off_mid_run_falls_back(world):
    world.behaviour["mac-mini-2012"] = drops("mac-mini-2012")
    r = td.dispatch("vitest", need="bench", timeout=120)
    assert r.ok and r.fell_back_from == "mac-mini-2012"
    assert world.lines()[0]["reason"] == "unreachable"


def test_a_box_offline_at_dispatch_sends_test_work_straight_to_a_mac_and_says_so(world):
    world.online.discard("mac-mini-2012")
    r = td.dispatch("pytest", need="test", timeout=480)
    assert r.ok and r.device_id in ("mac-mini-1", "macbook-pro-1")
    assert [d for d, _ in world.ran] == [r.device_id]           # nothing was tried on the box
    assert world.lines()[0]["reason"] == "unavailable"


def test_a_box_whose_tests_fail_is_a_real_result_not_a_stall(world):
    # A box result that disagrees with what a Mac would say must stand: no quiet rerun until something passes.
    world.behaviour["mac-mini-2012"] = lambda t: td.DispatchResult(ok=False, device_id="mac-mini-2012", error="exit 1: 2 failed")
    r = td.dispatch("pytest", need="test", timeout=480)
    assert not r.ok and r.device_id == "mac-mini-2012" and "2 failed" in r.error
    assert world.ran == [("mac-mini-2012", 480)]
    assert world.lines() == []


def test_the_fallback_is_attempted_once_and_a_failing_mac_run_is_reported_not_retried(world):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    world.behaviour["mac-mini-1"] = hangs("mac-mini-1")
    world.load = {"mac-mini-1": (0.5, 10, 0), "macbook-pro-1": (6.0, 8, 0)}
    r = td.dispatch("pytest", need="test", timeout=480)
    assert not r.ok and r.device_id == "mac-mini-1" and r.fell_back_from == "mac-mini-2012"
    assert [d for d, _ in world.ran] == ["mac-mini-2012", "mac-mini-1"]
    assert world.lines()[0]["outcome"] == "failed"


# ── the less busy Mac ────────────────────────────────────────────────────────────────────────────────────────

def test_a_busy_fallback_mac_is_passed_over_for_the_other(world):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    world.busy.add("mac-mini-1")                                   # a build holds the Mini
    world.load = {"mac-mini-1": (2.0, 10, 1), "macbook-pro-1": (1.0, 8, 0)}
    assert td.dispatch("pytest", need="test", timeout=480).device_id == "macbook-pro-1"


def test_both_macs_busy_still_runs_on_the_lighter_one_rather_than_dropping_the_job(world):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    world.busy |= {"mac-mini-1", "macbook-pro-1"}
    world.load = {"mac-mini-1": (12.0, 10, 2), "macbook-pro-1": (3.0, 8, 1)}
    r = td.dispatch("pytest", need="test", timeout=480)
    assert r.ok and r.device_id == "macbook-pro-1"


def test_unknown_load_or_a_tie_goes_to_the_mini(world):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    world.load = {"macbook-pro-1": (0.1, 8, 0)}                    # the Mini's load can't be read
    assert td.dispatch("pytest", need="test", timeout=480).device_id == "mac-mini-1"
    world.ran.clear()
    world.load = {"mac-mini-1": (2.0, 10, 0), "macbook-pro-1": (1.5, 8, 0)}   # 0.20 vs 0.19: within the margin
    assert td.dispatch("pytest", need="test", timeout=480).device_id == "mac-mini-1"


def test_an_offline_mac_is_never_the_fallback(world):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    world.self_id = "macbook-pro-1"
    world.online.discard("gils-mac-mini")
    world.load = {"mac-mini-1": (0.0, 10, 0), "macbook-pro-1": (7.0, 8, 3)}
    assert td.dispatch("pytest", need="test", timeout=480).device_id == "macbook-pro-1"


def test_load_score_counts_runs_already_taken_on_that_mac():
    assert td.load_score((2.0, 8, 0)) == pytest.approx(0.25)
    assert td.load_score((2.0, 8, 2)) == pytest.approx(2.25)
    assert td.load_score(None) is None
    assert td.load_score((2.0, 0, 0)) is None                     # a nonsense core count is "unknown", not a crash


# ── quarantine and security: never ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("need", ["quarantine", "security", "QUARANTINE ", "Security"])
def test_untrusted_work_never_reaches_a_mac_when_the_box_is_down(world, need):
    world.online.discard("mac-mini-2012")
    r = td.dispatch("run-untrusted.sh", need=need, timeout=300)
    assert not r.ok and "no machine" in r.error
    assert world.ran == [] and world.lines() == []


@pytest.mark.parametrize("need", ["quarantine", "security"])
@pytest.mark.parametrize("stall", [hangs, drops])
def test_untrusted_work_that_stalls_on_the_box_fails_loudly_and_stays_there(world, need, stall):
    world.behaviour["mac-mini-2012"] = stall("mac-mini-2012")
    r = td.dispatch("run-untrusted.sh", need=need, timeout=300)
    assert not r.ok and r.device_id == "mac-mini-2012" and r.fell_back_from is None
    assert world.ran == [("mac-mini-2012", 300)]
    assert world.lines() == []


def test_untrusted_work_named_at_a_mac_is_still_refused(world):
    r = td.dispatch("run-untrusted.sh", need="quarantine", target="mac-mini-1")
    assert not r.ok and world.ran == []


def test_only_test_and_bench_may_fall_back():
    assert td.FALLBACK_NEEDS == frozenset({"test", "bench"})


def test_general_work_is_untouched_by_the_amendment(world):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    world.behaviour["macbook-pro-1"] = hangs("macbook-pro-1")
    r = td.dispatch("echo hi", timeout=30)
    assert not r.ok and r.fell_back_from is None
    assert [d for d, _ in world.ran] == ["macbook-pro-1"]


def test_a_caller_can_turn_the_fallback_off(world):
    # The merge gate's extra box runner: the Mac is already running the verdict, a fallback would only double it.
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    r = td.dispatch("pytest", need="test", timeout=480, fallback=False)
    assert not r.ok and r.timed_out and world.ran == [("mac-mini-2012", 480)]


# ── a fallback storm ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_fallback_storm_is_capped_and_the_overflow_fails_loudly(world, tmp_path):
    # Many box jobs time out together: no more than FALLBACK_CAP of them may be rerunning on the Macs at once.
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    runs = tmp_path / "fallback-runs"
    runs.mkdir()
    sleepers = [subprocess.Popen(["sleep", "30"]) for _ in range(td.FALLBACK_CAP)]
    try:
        for p in sleepers:
            (runs / f"{p.pid}.json").write_text(json.dumps({"pid": p.pid}))
        r = td.dispatch("pytest", need="test", timeout=480)
        assert not r.ok and "fallback" in r.error and str(td.FALLBACK_CAP) in r.error
        assert [d for d, _ in world.ran] == ["mac-mini-2012"]
        assert world.lines()[-1]["outcome"] == "capped"
    finally:
        for p in sleepers:
            p.kill()
            p.wait()


def test_a_dead_fallback_record_does_not_count_against_the_cap(world, tmp_path):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    runs = tmp_path / "fallback-runs"
    runs.mkdir()
    dead = subprocess.Popen(["true"])
    dead.wait()
    for i in range(td.FALLBACK_CAP + 3):
        (runs / f"stale{i}.json").write_text(json.dumps({"pid": dead.pid}))
    (runs / "garbage.json").write_text("{not json")
    assert td.dispatch("pytest", need="test", timeout=480).ok


def test_a_finished_fallback_releases_its_slot(world, tmp_path):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    for _ in range(td.FALLBACK_CAP + 2):
        assert td.dispatch("pytest", need="test", timeout=480).ok
    assert list((tmp_path / "fallback-runs").glob("*.json")) == []


def test_a_crashing_fallback_run_still_releases_its_slot(world, tmp_path):
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")

    def boom(t):
        raise RuntimeError("ssh exploded")
    world.behaviour["mac-mini-1"] = boom
    world.load = {"mac-mini-1": (0.0, 10, 0), "macbook-pro-1": (5.0, 8, 0)}
    with pytest.raises(RuntimeError):
        td.dispatch("pytest", need="test", timeout=480)
    assert list((tmp_path / "fallback-runs").glob("*.json")) == []


# ── the run on the box is really stopped at the timeout ──────────────────────────────────────────────────────

def test_a_linux_remote_run_is_wrapped_in_a_kill_after_timeout_and_ssh_waits_a_little_longer():
    remote, ssh_wait = td._remote_invocation("/tmp/dispatch-x.sh", 480, "linux")
    assert remote == "timeout -k 15 480 /tmp/dispatch-x.sh"
    assert ssh_wait > 480 + 15
    remote, ssh_wait = td._remote_invocation("/tmp/dispatch-x.sh", 480, "macos")
    assert remote == "/tmp/dispatch-x.sh" and ssh_wait == 480    # a Mac has no GNU timeout: unchanged


def test_exit_codes_are_read_as_stall_or_result():
    assert td._classify_remote_exit(124) == "timeout"          # GNU timeout fired
    assert td._classify_remote_exit(137) == "timeout"          # ... and had to SIGKILL
    assert td._classify_remote_exit(255) == "unreachable"      # ssh could not connect or lost the link
    assert td._classify_remote_exit(1) is None                 # the job's own failure
    assert td._classify_remote_exit(2) is None


def test_the_wrapper_clears_its_task_record_and_busy_flag_when_terminated(tmp_path):
    # GNU timeout sends SIGTERM to the run's process group. The wrapper must still clean up, or the box looks busy for
    # ever and every later test job falls back. bash runs its EXIT trap on SIGTERM (checked on macOS bash 3.2 and the
    # box's bash 5 under GNU timeout, #930); this guards that.
    script = td._build_wrapper_script("sleep 30", "abc12345", "label", "box")
    f = tmp_path / "w.sh"
    f.write_text(script)
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    p = subprocess.Popen(["/bin/bash", str(f)], env=env, start_new_session=True)
    record = tmp_path / ".claude" / "dispatch" / "tasks" / "abc12345.json"
    for _ in range(100):
        if record.exists():
            break
        time.sleep(0.05)
    assert record.exists()
    os.killpg(p.pid, 15)
    p.wait(timeout=10)
    assert not record.exists()
    assert '"busy": false' in (tmp_path / ".claude" / "dispatch-state.json").read_text()


# ── async test work still gets its fallback ──────────────────────────────────────────────────────────────────

def test_async_test_work_runs_as_a_detached_sync_dispatch_so_its_fallback_can_fire(world, monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(td.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)) or None)
    monkeypatch.setattr(td, "ASYNC_LOG_DIR", tmp_path / "logs")
    r = td.dispatch("pytest lib -n 8", need="test", mode="async", timeout=480)
    assert r.ok and world.ran == []
    (argv, kw), = started
    assert "--async" not in argv and argv[argv.index("--needs") + 1] == "test"
    assert argv[argv.index("--timeout") + 1] == "480" and "pytest lib -n 8" in argv
    assert kw["start_new_session"] is True


def test_async_quarantine_work_is_not_detached_that_way(world, monkeypatch):
    monkeypatch.setattr(td.subprocess, "Popen", lambda *a, **k: pytest.fail("no detached rerun for untrusted work"))
    r = td.dispatch("x", need="quarantine", mode="async", timeout=300)
    assert r.ok and world.ran == [("mac-mini-2012", 300)]


def test_tagged_work_never_runs_the_builders_credit_probe():
    # builder_auth.sh can send a 1-token API call when a Mac's plan slots are full; a test job falling back to a busy
    # Mac must spend nothing (no paid tokens for test/bench/quarantine/security work).
    for need in ("test", "bench", "quarantine", "security"):
        assert "builder_auth" not in td._build_wrapper_script("true", "abc", "l", "mac-mini-1", need=need)
    assert "marvin_builder_auth abc" in td._build_wrapper_script("true", "abc", "l", "mac-mini-1")
    assert "marvin_builder_auth abc" in td._build_wrapper_script("true", "abc", "l", "mac-mini-1", need="general")


def test_a_fallback_run_is_built_as_tagged_work(world, monkeypatch):
    seen = []
    real = td._build_wrapper_script
    monkeypatch.setattr(td, "_build_wrapper_script", lambda *a, **k: seen.append(k.get("need")) or real(*a, **k))
    world.behaviour["mac-mini-2012"] = hangs("mac-mini-2012")
    assert td.dispatch("pytest", need="test", timeout=480).ok
    assert seen == ["test", "test"]
