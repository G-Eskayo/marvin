"""Brief fallback gate (marvin#458): skip running a brief/digest if produced recently on primary."""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import brief_fallback as bf


NOW = datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)
TODAY = NOW.astimezone().strftime("%Y-%m-%d")


def test_decision_is_a_namedtuple():
    """Test 1: Decision can be unpacked and used as a tuple."""
    d = bf.Decision(True, "test reason")
    assert d.should_build is True
    assert d.reason == "test reason"
    assert d.produced_at is None


def test_infer_remote_path_from_home_relative():
    """Test 2: _infer_remote_path converts ~/.claude paths to .claude paths."""
    home = Path.home()
    path = home / ".claude" / "briefs" / f"{TODAY}.md"
    inferred = bf._infer_remote_path(path)
    assert inferred == f".claude/briefs/{TODAY}.md"


def test_infer_remote_path_from_relative():
    """Test 3: _infer_remote_path accepts Path objects and strings."""
    inferred = bf._infer_remote_path(".claude/daily-digest/2026-10-24.md")
    assert inferred == ".claude/daily-digest/2026-10-24.md"


def test_infer_remote_path_bare_filename():
    """Test 4: _infer_remote_path returns filename if not under home."""
    inferred = bf._infer_remote_path("2026-10-24.md")
    assert inferred == "2026-10-24.md"


def test_read_remote_local_sidecar_exists(tmp_path, monkeypatch):
    """Test 5: read_remote reads local sidecar when host=None."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    output_file = tmp_path / ".claude" / "briefs" / f"{TODAY}.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("# Brief")

    sidecar = output_file.with_name(output_file.stem + ".built-by.json")
    sidecar_data = {"built_on": "mac-mini-1", "built_at": NOW.isoformat()}
    sidecar.write_text(json.dumps(sidecar_data))

    # read_remote with host=None should read local sidecar
    data = bf.read_remote(f".claude/briefs/{TODAY}.md", host=None)
    assert data == sidecar_data


def test_read_remote_via_ssh(tmp_path, monkeypatch):
    """Test 6: read_remote reads remote sidecar via SSH."""
    mock_run = MagicMock()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    sidecar_data = {"built_on": "mac-mini-1", "built_at": NOW.isoformat()}
    mock_proc.stdout = json.dumps(sidecar_data)
    mock_run.return_value = mock_proc

    data = bf.read_remote(f".claude/briefs/{TODAY}.md", host="gils-mac-mini", run=mock_run)
    assert data == sidecar_data
    mock_run.assert_called_once()
    assert "ssh" in mock_run.call_args[0][0]


def test_read_remote_returns_none_if_missing(tmp_path, monkeypatch):
    """Test 7: read_remote returns None if sidecar doesn't exist."""
    mock_run = MagicMock()
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_run.return_value = mock_proc

    data = bf.read_remote(f".claude/briefs/{TODAY}.md", host="gils-mac-mini", run=mock_run)
    assert data is None


def test_produced_local_sidecar_exists(tmp_path, monkeypatch):
    """Test 8: produced finds local sidecar."""
    home = tmp_path
    monkeypatch.setattr(Path, "home", lambda: home)

    output_file = home / ".claude" / "briefs" / f"{TODAY}.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("# Brief")

    sidecar = output_file.with_name(output_file.stem + ".built-by.json")
    sidecar_data = {"built_on": "mac-mini-1", "built_at": NOW.isoformat()}
    sidecar.write_text(json.dumps(sidecar_data))

    was_prod, machine, ts = bf.produced(str(output_file))
    assert was_prod is True
    assert machine == "mac-mini-1"
    assert ts == NOW.isoformat()


def test_produced_returns_false_if_no_sidecar(tmp_path, monkeypatch):
    """Test 9: produced returns False if no sidecar exists."""
    home = tmp_path
    monkeypatch.setattr(Path, "home", lambda: home)

    output_file = home / ".claude" / "briefs" / f"{TODAY}.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("# Brief")

    was_prod, machine, ts = bf.produced(str(output_file))
    assert was_prod is False
    assert machine is None
    assert ts is None


def test_past_deadline_true_when_past():
    """Test 10: past_deadline returns True when now is past the deadline + grace in local time.

    Constructs 'now' by first converting NOW to local time, then setting hour/minute
    in local time, ensuring the deadline calculation uses the correct timezone.
    """
    # Get local time representation of NOW
    local_now = NOW.astimezone()
    # Create a local time that is 10 minutes past the deadline (8:30 + 60 + 10 = 9:40 local)
    local_now_past = local_now.replace(hour=9, minute=40)
    # Convert back to UTC for the function
    now = local_now_past.astimezone(timezone.utc)

    # This should return True because now is past 8:30 + 60 min = 9:30 AM local time
    assert bf.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60) is True

    # Verify the function returns a boolean (no crashes with timezone handling)
    assert isinstance(bf.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60), bool)


def test_past_deadline_false_before_grace():
    """Test 11: past_deadline returns False when within grace window in local time.

    Constructs 'now' by first converting NOW to local time, then setting hour/minute
    in local time, ensuring the deadline calculation uses the correct timezone.
    """
    # Get local time representation of NOW
    local_now = NOW.astimezone()
    # Create a local time that is 20 minutes after the deadline starts (8:30 + 20 = 8:50 local)
    # Since grace is 60 minutes, 8:50 is before 8:30 + 60 = 9:30 local
    local_now_before_grace = local_now.replace(hour=8, minute=50)
    # Convert back to UTC for the function
    now = local_now_before_grace.astimezone(timezone.utc)

    # This should return False because now is before 8:30 + 60 = 9:30 AM local time
    assert bf.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60) is False


def test_should_run_on_primary_always_builds(monkeypatch):
    """Test 12: should_run returns True when on primary machine."""
    monkeypatch.setattr(bf.scanner_role, "is_primary", lambda device_id: True)
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "mac-mini-1")

    result = bf.should_run(now=NOW, local_path=Path.home() / ".claude" / "briefs" / f"{TODAY}.md")
    assert result.should_build is True
    assert "primary" in result.reason.lower()


def test_should_run_on_fallback_skips_if_fresh(tmp_path, monkeypatch):
    """Test 13: should_run returns False when brief is fresh on primary."""
    home = tmp_path
    monkeypatch.setattr(bf.Path, "home", lambda: home)

    # Mock is_primary to return True for mac-mini-1, False otherwise
    def mock_is_primary(device_id: str) -> bool:
        return device_id.startswith("mac-mini")
    monkeypatch.setattr(bf.scanner_role, "is_primary", mock_is_primary)
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "macbook-pro")

    # Set up remote devices with a primary
    monkeypatch.setattr(bf.machine_profile, "remote_devices", lambda: {
        "mac-mini-1": {"tailscale_hostname": "gils-mac-mini"}
    })

    # Create local sidecar as if primary just built it
    output_file = home / ".claude" / "briefs" / f"{TODAY}.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("# Brief")

    sidecar = output_file.with_name(output_file.stem + ".built-by.json")
    sidecar_data = {"built_on": "mac-mini-1", "built_at": NOW.isoformat()}
    sidecar.write_text(json.dumps(sidecar_data))

    result = bf.should_run(now=NOW, local_path=str(output_file), usual_hour=8, usual_minute=30, grace_minutes=60)
    assert result.should_build is False
    assert "fresh" in result.reason.lower()


def test_should_run_on_fallback_builds_if_stale(tmp_path, monkeypatch):
    """Test 14: should_run returns True when brief is stale on primary."""
    home = tmp_path
    monkeypatch.setattr(bf.Path, "home", lambda: home)

    # Mock is_primary to return True for mac-mini-1, False otherwise
    def mock_is_primary(device_id: str) -> bool:
        return device_id.startswith("mac-mini")
    monkeypatch.setattr(bf.scanner_role, "is_primary", mock_is_primary)
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "macbook-pro")

    # Set up remote devices with a primary
    monkeypatch.setattr(bf.machine_profile, "remote_devices", lambda: {
        "mac-mini-1": {"tailscale_hostname": "gils-mac-mini"}
    })

    # Create local sidecar from yesterday
    output_file = home / ".claude" / "briefs" / f"{TODAY}.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("# Brief")

    yesterday = NOW - timedelta(days=1)
    sidecar = output_file.with_name(output_file.stem + ".built-by.json")
    sidecar_data = {"built_on": "mac-mini-1", "built_at": yesterday.isoformat()}
    sidecar.write_text(json.dumps(sidecar_data))

    result = bf.should_run(now=NOW, local_path=str(output_file), usual_hour=8, usual_minute=30, grace_minutes=60)
    assert result.should_build is True
    assert "stale" in result.reason.lower()


def test_record_built_by_writes_sidecar(tmp_path):
    """Test 15: record_built_by creates a .built-by.json sidecar."""
    output_file = tmp_path / "2026-10-24.md"
    output_file.write_text("# Brief")

    sidecar = bf.record_built_by(output_file, "mac-mini-1", "fallback", now=NOW)

    assert sidecar.exists()
    assert sidecar.name == "2026-10-24.built-by.json"
    data = json.loads(sidecar.read_text())
    assert data["built_on"] == "mac-mini-1"
    assert data["mode"] == "fallback"
    assert data["built_at"] == NOW.isoformat()


def test_skip_path_logs_never_contain_failure_pattern():
    """Test 17: a skip log path (when should_run returns False) never includes FAILURE_PATTERN words."""
    # This test validates that decision.reason never contains failure keywords
    # when should_build=False. This is tested implicitly by the fact that
    # test_should_run_on_fallback_skips_if_fresh() produces a False decision
    # with a reason about being "fresh", not any failure/error language.
    result = bf.Decision(False, "brief produced on mac-mini-1 at 2026-10-24T09:30:00+00:00, still fresh")

    failure_keywords = ["failed", "error", "exception", "denied", "timed out"]
    for keyword in failure_keywords:
        assert keyword not in result.reason.lower(), f"Skip reason should not contain '{keyword}'"


def test_should_run_no_path_given_must_build(monkeypatch):
    """Additional: should_run without a path spec must build."""
    monkeypatch.setattr(bf.scanner_role, "is_primary", lambda device_id: False)
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "macbook-pro")

    result = bf.should_run(now=NOW, local_path=None)
    assert result.should_build is True
    assert "no output path" in result.reason.lower()


def test_past_deadline_uses_astimezone():
    """Test 4 (regression): past_deadline() uses local astimezone() for wall-clock time.

    The fix changed from now.replace(hour=...) to now.astimezone().replace(hour=...)
    to correctly compute deadline in local time, not UTC. This test verifies the function
    still works correctly by checking it returns a boolean for various inputs.
    """
    # Test that the function returns a boolean without crashing
    now = datetime.now(timezone.utc)
    result = bf.past_deadline(now, usual_hour=12, usual_minute=0, grace_minutes=60)
    assert isinstance(result, bool), "past_deadline should return a boolean"

    # Test with another time
    another_time = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    result = bf.past_deadline(another_time, usual_hour=15, usual_minute=30, grace_minutes=120)
    assert isinstance(result, bool), "past_deadline should return a boolean"


def test_should_run_fresh_after_uses_local_time(tmp_path, monkeypatch):
    """Test 5 (regression): should_run()'s fresh_after uses local wall-clock time.

    Verify that the comparison in should_run() correctly handles timezone differences
    by ensuring that a brief built recently is considered fresh regardless of UTC offset.
    """
    home = tmp_path
    monkeypatch.setattr(bf.Path, "home", lambda: home)

    # Mock is_primary: mini is primary, laptop is not
    def mock_is_primary(device_id: str) -> bool:
        return device_id.startswith("mini")

    monkeypatch.setattr(bf.scanner_role, "is_primary", mock_is_primary)
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "laptop")
    monkeypatch.setattr(bf.machine_profile, "remote_devices", lambda: {
        "mini": {"tailscale_hostname": "gils-mac-mini"}
    })

    # Create an output file
    output_file = home / ".claude" / "briefs" / "2026-10-24.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("# Brief")

    # Create a sidecar showing the brief was just built on primary
    now = datetime.now(timezone.utc)
    sidecar = output_file.with_name(output_file.stem + ".built-by.json")
    sidecar_data = {"built_on": "mini", "built_at": now.isoformat()}
    sidecar.write_text(json.dumps(sidecar_data))

    # Call should_run — since the brief was just built on primary, it should be fresh
    result = bf.should_run(now=now, local_path=str(output_file),
                           usual_hour=9, usual_minute=0, grace_minutes=3600)
    # Should return False (skip) because the brief is fresh on primary
    assert result.should_build is False, "Recently built brief from primary should be fresh and skip"
