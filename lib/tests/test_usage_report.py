"""lib/usage_report.py: this machine's tool and token usage plus the other machine's, read over ssh, in one JSON for the Metrics tab."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import usage_report as ur  # noqa: E402

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def doc(machine, age_min, **extra):
    return {"machine": machine, "generated_at": (NOW - timedelta(minutes=age_min)).isoformat(), **extra}


class Peers:
    """A fake ssh: answers `cat <path>` from a dict, records scans."""
    def __init__(self, files, reachable=True):
        self.files, self.reachable, self.calls = files, reachable, []

    def __call__(self, host, command, timeout=20):
        self.calls.append((host, command))
        if not self.reachable:
            raise OSError("unreachable")
        if command.startswith("cat "):
            name = command.split("/")[-1]
            if name in self.files:
                return json.dumps(self.files[name])
            raise FileNotFoundError(name)
        return ""  # a scan command


def setup(monkeypatch, tmp_path, local_tools=None, local_tokens=None, peers=None):
    tools, tokens = tmp_path / "tool-usage.json", tmp_path / "token-usage.json"
    if local_tools is not None:
        tools.write_text(json.dumps(local_tools))
    if local_tokens is not None:
        tokens.write_text(json.dumps(local_tokens))
    monkeypatch.setattr(ur, "TOOL_PATH", tools)
    monkeypatch.setattr(ur, "TOKEN_PATH", tokens)
    monkeypatch.setattr(ur, "this_machine", lambda: "mac-mini-1")
    monkeypatch.setattr(ur, "peer_machines", lambda: peers or {"macbook-pro-1": "c02f52gpq05ps-macbook-pro"})
    monkeypatch.setattr(ur, "refresh_local", lambda: None)   # never scan real transcripts in a test


def test_reports_this_machine_and_the_peer_side_by_side(monkeypatch, tmp_path):
    ssh = Peers({"tool-usage.json": doc("macbook-pro-1", 5, tools=[{"name": "Bash"}]),
                 "token-usage.json": doc("macbook-pro-1", 5, totals={"output": 9})})
    setup(monkeypatch, tmp_path, doc("mac-mini-1", 1, tools=[]), doc("mac-mini-1", 1, totals={"output": 5}))
    r = ur.report(now=NOW, ssh=ssh)
    by = {m["machine"]: m for m in r["machines"]}
    assert set(by) == {"mac-mini-1", "macbook-pro-1"}
    assert by["mac-mini-1"]["this"] is True and by["macbook-pro-1"]["this"] is False
    assert by["macbook-pro-1"]["tokens"]["totals"]["output"] == 9 and by["macbook-pro-1"]["reachable"] is True


def test_an_unreachable_peer_is_reported_not_hidden_and_does_not_fail_the_report(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, doc("mac-mini-1", 1, tools=[]), doc("mac-mini-1", 1, totals={}))
    r = ur.report(now=NOW, ssh=Peers({}, reachable=False))
    peer = next(m for m in r["machines"] if m["machine"] == "macbook-pro-1")
    assert peer["reachable"] is False and peer["tools"] is None and peer["tokens"] is None
    assert next(m for m in r["machines"] if m["this"])["tokens"] is not None


def test_a_stale_peer_scan_is_refreshed_over_ssh_when_the_peer_answers(monkeypatch, tmp_path):
    ssh = Peers({"tool-usage.json": doc("macbook-pro-1", 300, tools=[]), "token-usage.json": doc("macbook-pro-1", 300, totals={})})
    setup(monkeypatch, tmp_path, doc("mac-mini-1", 1, tools=[]), doc("mac-mini-1", 1, totals={}))
    ur.report(now=NOW, ssh=ssh)
    assert any("usage_report.py scan" in c for _h, c in ssh.calls)


def test_a_fresh_peer_scan_is_left_alone(monkeypatch, tmp_path):
    ssh = Peers({"tool-usage.json": doc("macbook-pro-1", 10, tools=[]), "token-usage.json": doc("macbook-pro-1", 10, totals={})})
    setup(monkeypatch, tmp_path, doc("mac-mini-1", 1, tools=[]), doc("mac-mini-1", 1, totals={}))
    ur.report(now=NOW, ssh=ssh)
    assert not any("usage_report.py scan" in c for _h, c in ssh.calls)


def test_a_missing_local_file_means_none_not_a_crash(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    r = ur.report(now=NOW, ssh=Peers({}, reachable=False))
    assert next(m for m in r["machines"] if m["this"])["tools"] is None


def test_a_peer_that_answers_but_has_no_scan_yet_is_reachable_and_gets_asked_to_scan(monkeypatch, tmp_path):
    ssh = Peers({})   # answers, but both files are missing
    setup(monkeypatch, tmp_path, doc("mac-mini-1", 1, tools=[]), doc("mac-mini-1", 1, totals={}))
    r = ur.report(now=NOW, ssh=ssh)
    peer = next(m for m in r["machines"] if not m["this"])
    assert peer["reachable"] is True and peer["tools"] is None
    assert any("usage_report.py scan" in c for _h, c in ssh.calls)


def test_each_machine_carries_its_github_use(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, doc("mac-mini-1", 1), doc("mac-mini-1", 1))
    monkeypatch.setattr(ur, "local_github", lambda: {"machine": "mac-mini-1", "hours": [], "top": []})

    class WithGithub(Peers):
        def __call__(self, host, command, timeout=20):
            if "github_usage.py" in command:
                self.calls.append((host, command))
                return json.dumps({"machine": "macbook-pro-1", "hours": [{"total": 3}], "top": []})
            return super().__call__(host, command, timeout)

    r = ur.report(now=NOW, ssh=WithGithub({"tool-usage.json": doc("macbook-pro-1", 5), "token-usage.json": doc("macbook-pro-1", 5)}))
    by = {m["machine"]: m for m in r["machines"]}
    assert by["mac-mini-1"]["github"]["machine"] == "mac-mini-1"
    assert by["macbook-pro-1"]["github"]["hours"][0]["total"] == 3


def test_a_peer_without_the_github_summary_still_reports(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, doc("mac-mini-1", 1), doc("mac-mini-1", 1))
    monkeypatch.setattr(ur, "local_github", lambda: None)
    r = ur.report(now=NOW, ssh=Peers({"tool-usage.json": doc("macbook-pro-1", 5), "token-usage.json": doc("macbook-pro-1", 5)}))
    assert all(m["github"] is None for m in r["machines"])


# ── Test 6-8: launches reporting ──────────────────────────────────────────

def test_local_launches_calls_marvin_launcher_spend_report(monkeypatch, tmp_path):
    """Test 6: local_launches delegates to marvin_launcher.spend_report()."""
    def mock_spend_report(log_path=None, days=30, now=None):
        return {"digest": 0.3, "research-colony": 0.15, None: 0.0}

    # Patch at the module level where it's imported and used
    import marvin_launcher
    monkeypatch.setattr(marvin_launcher, "spend_report", mock_spend_report)

    launches_data = ur.local_launches()
    assert launches_data.get("digest") == 0.3
    assert launches_data.get("research-colony") == 0.15


def test_peer_launches_reads_from_remote_over_ssh():
    """Test 7: _peer_launches calls spend_report on a remote machine."""
    class MockSSH:
        def __call__(self, host, command, timeout=20):
            if "spend_report" in command or "marvin_launcher" in command:
                # Return JSON-encoded launch spend data
                return json.dumps({"digest": 0.5, "self-review": 0.25})
            raise ValueError(f"unexpected command: {command}")

    launches_data = ur._peer_launches("remote-host", ssh=MockSSH())
    assert launches_data.get("digest") == 0.5
    assert launches_data.get("self-review") == 0.25


def test_report_includes_launches_per_machine(monkeypatch, tmp_path):
    """Test 8: report() includes launches in each machine's dict."""
    setup(monkeypatch, tmp_path, doc("mac-mini-1", 1), doc("mac-mini-1", 1))

    class MockSSH(Peers):
        def __init__(self):
            super().__init__({"tool-usage.json": doc("macbook-pro-1", 5), "token-usage.json": doc("macbook-pro-1", 5)})

        def __call__(self, host, command, timeout=20):
            if "marvin_launcher" in command:
                return json.dumps({"digest": 0.3, "self-review": 0.1})
            return super().__call__(host, command, timeout)

    def mock_local_launches():
        return {"digest": 0.2, "research-colony": 0.1, None: 0.05}

    monkeypatch.setattr(ur, "local_launches", mock_local_launches)
    r = ur.report(now=NOW, ssh=MockSSH())

    by_machine = {m["machine"]: m for m in r["machines"]}
    assert "launches" in by_machine["mac-mini-1"]
    assert by_machine["mac-mini-1"]["launches"]["digest"] == 0.2
    assert "launches" in by_machine["macbook-pro-1"]
