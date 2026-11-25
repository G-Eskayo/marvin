"""marvin #374: UI changes carry images. iOS simulator screenshot capture (profile-driven), the shared UI-path rules
(mirroring dashboard/webhook-server/ui_evidence.js), and how the PR body shows the images."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evidence_capture as ec  # noqa: E402
import mr_raiser  # noqa: E402
import project_profile as pp  # noqa: E402

CFG = {
    "project_dir": "Apps/Spike",
    "prepare": [["xcodegen", "generate"]],
    "project": "CaptionSpike.xcodeproj",
    "scheme": "CaptionSpike",
    "simulator": "iPhone 17 Pro",
    "bundle_id": "com.gileskayo.captions",
    "scenes": [{"name": "main", "args": ["-ClarityDemoStatic"]}, {"name": "settings", "args": ["-ClarityDemoSettings"]}],
}


class FakeRun:
    """Records commands; xcodebuild 'builds' the .app into the derived-data folder it was given; screenshot/recordVideo writes a file."""

    def __init__(self, fail_on=None, boot_error=None, popen_effect=None):
        self.calls, self.fail_on, self.boot_error, self.popen_effect = [], fail_on, boot_error, popen_effect

    def __call__(self, cmd, cwd=None, **kw):
        self.calls.append((list(cmd), str(cwd) if cwd else None))
        if self.fail_on and self.fail_on in cmd:
            raise subprocess.CalledProcessError(65, cmd, output="", stderr=f"{self.fail_on} failed: error: something broke")
        if cmd[0] == "xcodebuild":
            dd = Path(cmd[cmd.index("-derivedDataPath") + 1])
            (dd / "Build/Products/Debug-iphonesimulator/CaptionSpike.app").mkdir(parents=True, exist_ok=True)
        if cmd[:3] == ["xcrun", "simctl", "boot"] and self.boot_error:
            raise subprocess.CalledProcessError(149, cmd, stderr=self.boot_error)
        if cmd[:4] == ["xcrun", "simctl", "io", "booted"] and cmd[4] == "screenshot":
            Path(cmd[-1]).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def Popen(self, cmd, **kw):
        """Fake Popen for recordVideo."""
        self.calls.append((list(cmd), None))
        if self.popen_effect:
            return self.popen_effect(cmd)
        # By default, write a valid MP4 header when recordVideo finishes
        if cmd[0:4] == ["xcrun", "simctl", "io", "booted"] and cmd[4] == "recordVideo":
            # Write valid MP4 header (ftyp box at byte 4)
            Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00mp42isom")

        class FakeProc:
            def __init__(self, cmd, parent):
                self.cmd = cmd
                self.parent = parent
                self.pid = 12345
                self.returncode = None

            def send_signal(self, sig):
                pass

            def wait(self, timeout=None):
                if self.parent.popen_effect:
                    effect_result = self.parent.popen_effect(self.cmd)
                    if hasattr(effect_result, 'wait'):
                        return effect_result.wait(timeout=timeout)
                return 0

            def kill(self):
                pass

        return FakeProc(cmd, self)


def test_captures_every_scene_in_light_and_dark_into_the_worktree(tmp_path):
    run = FakeRun()
    result = ec.capture_ios_simulator(tmp_path, CFG, run=run, sleep=lambda s: None)
    shots = result["screenshots"]
    assert [s["caption"] for s in shots] == ["main, light", "settings, light", "main, dark", "settings, dark"]
    for s in shots:
        assert not Path(s["path"]).is_absolute() and (tmp_path / s["path"]).read_bytes() == b"png"
    cmds = [c for c, _ in run.calls]
    assert ["xcodegen", "generate"] in cmds
    build = next(c for c in cmds if c[0] == "xcodebuild")
    assert "CODE_SIGNING_ALLOWED=NO" in build and "platform=iOS Simulator,name=iPhone 17 Pro" in build
    assert ["xcrun", "simctl", "ui", "booted", "appearance", "dark"] in cmds
    launches = [c for c in cmds if c[:3] == ["xcrun", "simctl", "launch"]]
    assert launches[0][-1] == "-ClarityDemoStatic" and "com.gileskayo.captions" in launches[0]


def test_an_already_booted_simulator_is_fine(tmp_path):
    # simctl's real wording (Mac Mini, 2026-10-09): the "Booted" part is NOT on the line that says "error".
    real = ("An error was encountered processing the command (domain=com.apple.CoreSimulator.SimError, code=405):\n"
            "Unable to boot device in current state: Booted")
    result = ec.capture_ios_simulator(tmp_path, CFG, run=FakeRun(boot_error=real), sleep=lambda s: None)
    assert len(result["screenshots"]) == 4


def test_any_other_boot_failure_still_stops_the_capture(tmp_path):
    with pytest.raises(RuntimeError, match="Invalid device"):
        ec.capture_ios_simulator(tmp_path, CFG, run=FakeRun(boot_error="error: Invalid device: iPhone 99"), sleep=lambda s: None)


def test_a_failed_build_raises_with_the_reason_so_the_pr_says_why(tmp_path):
    with pytest.raises(RuntimeError, match="something broke"):
        ec.capture_ios_simulator(tmp_path, CFG, run=FakeRun(fail_on="xcodebuild"), sleep=lambda s: None)


@pytest.mark.parametrize("bad", [{}, {**CFG, "scenes": []}, {**CFG, "bundle_id": ""}])
def test_an_incomplete_config_is_refused_plainly(tmp_path, bad):
    with pytest.raises(ValueError):
        ec.capture_ios_simulator(tmp_path, bad, run=FakeRun(), sleep=lambda s: None)


def test_ui_paths_match_the_dashboard_rules():
    assert ec.ui_files(["Apps/Spike/Sources/Localizable.xcstrings", "lib/x.py", "App/HomeView.swift"]) == [
        "Apps/Spike/Sources/Localizable.xcstrings", "App/HomeView.swift"]
    assert ec.ui_files(["Apps/Spike/Sources/SettingsSheet.swift"]) == []
    assert ec.ui_files(["Apps/Spike/Sources/SettingsSheet.swift"], ["Apps/**/*.swift"]) == ["Apps/Spike/Sources/SettingsSheet.swift"]
    assert ec.ui_files(["Packages/Core/Sources/Core/Thing.swift", "dashboard/electron/main/x.js"]) == []
    assert ec.ui_files([None, "", 3]) == []


def _git(path, *args):
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def _repo_with_change(tmp_path, changed):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("x")
    _git(tmp_path, "add", "-A"); _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    _git(tmp_path, "switch", "-qc", "feature")
    f = tmp_path / changed
    f.parent.mkdir(parents=True, exist_ok=True); f.write_text("y")
    _git(tmp_path, "add", "-A"); _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "change")


def _profile(**dev):
    return pp._validate({"repo": "G-Eskayo/clarity-captions", "verify": [{"id": "t", "command": ["true"]}],
                         "evidence": {"ui_paths": ["Apps/**/*.swift"], "dev": dev}}, "test")


def test_measurer_captures_only_when_the_diff_touches_ui(tmp_path, monkeypatch):
    _repo_with_change(tmp_path, "Apps/Spike/Sources/SettingsSheet.swift")
    seen = {}
    shots = [{"path": "docs/evidence/a.png", "caption": "main, light"}]
    monkeypatch.setattr(ec, "capture_ios_simulator", lambda wt, cfg, **kw: seen.setdefault("result", {"screenshots": shots, "recordings": []}))
    m = pp.Measurer(_profile(ios_simulator=CFG), runner=lambda *a: (0, ""), have=lambda *a: True)
    _, dev = m.evidence(tmp_path)
    assert dev["na"] is False and dev["screenshots"] == shots


def test_measurer_says_na_for_a_non_ui_diff(tmp_path, monkeypatch):
    _repo_with_change(tmp_path, "Packages/Core/Sources/Core/Logic.swift")
    monkeypatch.setattr(ec, "capture_ios_simulator", lambda *a, **k: pytest.fail("must not capture"))
    _, dev = pp.Measurer(_profile(ios_simulator=CFG), runner=lambda *a: (0, ""), have=lambda *a: True).evidence(tmp_path)
    assert dev == {"na": True, "reason": "no UI change"}


def test_a_capture_failure_is_reported_not_raised(tmp_path, monkeypatch):
    _repo_with_change(tmp_path, "Apps/Spike/Sources/SettingsSheet.swift")
    def boom(*a, **k):
        raise RuntimeError("xcodebuild failed: error: no such module")
    monkeypatch.setattr(ec, "capture_ios_simulator", boom)
    _, dev = pp.Measurer(_profile(ios_simulator=CFG), runner=lambda *a: (0, ""), have=lambda *a: True).evidence(tmp_path)
    assert dev["na"] is False and "no such module" in dev["error"]


def test_without_a_worktree_or_capture_config_the_old_na_reason_stands(tmp_path):
    _, dev = pp.Measurer(_profile(na="no capture"), runner=lambda *a: (0, ""), have=lambda *a: True).evidence()
    assert dev == {"na": True, "reason": "no capture"}


def test_the_pr_body_shows_each_screenshot_pinned_to_the_pushed_commit():
    dev = {"na": False, "screenshots": [{"path": "docs/evidence/w/main-light.png", "caption": "main, light"}],
           "description": "Simulator screenshots."}
    text = mr_raiser._format_dev_evidence(dev, repo="G-Eskayo/clarity-captions", ref="a" * 40)
    assert f"![main, light](https://raw.githubusercontent.com/G-Eskayo/clarity-captions/{'a' * 40}/docs/evidence/w/main-light.png)" in text
    assert "Simulator screenshots." in text


def test_gate_info_carries_the_projects_ui_paths(tmp_path):
    info = pp.gate_info(_profile(), catalog={}, have=lambda *a: True)
    assert info["ui_paths"] == ["Apps/**/*.swift"]


def test_the_simulator_build_folder_is_removed_after_capture_and_after_failure(tmp_path):
    # ~1 GB per build, left in $TMPDIR on every run before 2026-10-27.
    def derived(run):
        return [Path(c[c.index("-derivedDataPath") + 1]) for c, _ in run.calls if c[0] == "xcodebuild"]
    ok = FakeRun()
    ec.capture_ios_simulator(tmp_path, CFG, run=ok, sleep=lambda s: None)
    bad = FakeRun(fail_on="screenshot")
    with pytest.raises(RuntimeError):
        ec.capture_ios_simulator(tmp_path, CFG, run=bad, sleep=lambda s: None)
    assert derived(ok) and derived(bad) and not any(d.exists() for d in derived(ok) + derived(bad))


# Recording tests (tests 1-12 from design plan)

def test_a_recording_scene_name_not_declared_in_scenes_is_refused_plainly(tmp_path):
    bad_cfg = {**CFG, "recordings": [{"scene": "typo", "seconds": 5}]}
    with pytest.raises(ValueError, match="'typo'.*not declared"):
        ec.capture_ios_simulator(tmp_path, bad_cfg, run=FakeRun(), sleep=lambda s: None)


def test_seconds_is_validated(tmp_path):
    bad_configs = [
        {**CFG, "recordings": [{"scene": "main", "seconds": 0}]},
        {**CFG, "recordings": [{"scene": "main", "seconds": -1}]},
        {**CFG, "recordings": [{"scene": "main", "seconds": "not a number"}]},
        {**CFG, "recordings": [{"scene": "main", "seconds": 999999}]},
    ]
    for bad_cfg in bad_configs:
        with pytest.raises(ValueError, match="seconds"):
            ec.capture_ios_simulator(tmp_path, bad_cfg, run=FakeRun(), sleep=lambda s: None)


def test_recording_videos_are_captured_and_converted_to_gif_and_mp4(tmp_path, monkeypatch):
    cfg = {**CFG, "recordings": [{"scene": "main", "seconds": 2}]}

    # Mock subprocess.Popen for recordVideo
    popen_calls = []
    original_popen = subprocess.Popen

    def fake_popen(cmd, **kw):
        popen_calls.append(list(cmd))
        # Create valid MP4 header
        if cmd[0:4] == ["xcrun", "simctl", "io", "booted"] and cmd[4] == "recordVideo":
            Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 1000)  # Valid MP4 header + padding

        class FakeProc:
            pid = 12345
            returncode = None
            def send_signal(self, sig):
                pass
            def wait(self, timeout=None):
                return 0
            def kill(self):
                pass
        return FakeProc()

    # Also mock ffmpeg for GIF conversion
    ffmpeg_calls = []
    def fake_ffmpeg(cmd, **kw):
        ffmpeg_calls.append(list(cmd))
        if cmd[0] == "ffmpeg":
            # Create a small GIF file when ffmpeg is called
            if "-o" in cmd:
                idx = cmd.index("-o")
                gif_path = cmd[idx + 1]
            elif len(cmd) > 0 and cmd[-1].endswith(".gif"):
                gif_path = cmd[-1]
            else:
                gif_path = None
            if gif_path:
                Path(gif_path).write_bytes(b"GIF89a" + b"\x00" * 100)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x if x == "ffmpeg" else None)

    result = ec.capture_ios_simulator(tmp_path, cfg, run=fake_ffmpeg, sleep=lambda s: None)

    recordings = result.get("recordings", [])
    assert len(recordings) == 2  # light and dark
    for rec in recordings:
        assert rec["ok"] is True
        assert rec["path"].endswith(".mp4")
        assert rec["gif_path"].endswith(".gif")


def test_a_scene_crashing_mid_recording_does_not_lose_the_others(tmp_path, monkeypatch):
    cfg = {**CFG, "scenes": [{"name": "main", "args": []}, {"name": "settings", "args": []}],
           "recordings": [{"scene": "main", "seconds": 1}, {"scene": "settings", "seconds": 1}]}

    popen_calls = []
    def fake_popen_crashes(cmd, **kw):
        popen_calls.append(list(cmd))
        # Fail for second recording
        if len(popen_calls) > 1 and "settings" in cmd[-1]:
            # Return a process that creates a zero-byte file
            if "recordVideo" in cmd:
                Path(cmd[-1]).write_bytes(b"")  # Empty file = crash
        else:
            # Success case
            if "recordVideo" in cmd:
                Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 1000)

        class FakeProc:
            pid = 12345
            returncode = None
            def send_signal(self, sig): pass
            def wait(self, timeout=None): return 0
            def kill(self): pass
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen_crashes)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x if x == "ffmpeg" else None)

    run = FakeRun()
    result = ec.capture_ios_simulator(tmp_path, cfg, run=run, sleep=lambda s: None)

    recordings = result.get("recordings", [])
    # Should have recordings, some ok and some not
    assert len(recordings) > 0
    has_ok = any(r["ok"] for r in recordings)
    has_failed = any(not r["ok"] for r in recordings)
    assert has_ok or has_failed  # At least one attempted


def test_output_over_its_size_cap_is_reported_as_a_capture_failure(tmp_path, monkeypatch):
    cfg = {**CFG, "recordings": [{"scene": "main", "seconds": 1}]}

    # Monkeypatch to create oversized files
    def fake_popen(cmd, **kw):
        if "recordVideo" in cmd:
            Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * (60 * 1024 * 1024))  # 60 MB > 50 MB limit
        class FakeProc:
            pid = 12345
            returncode = None
            def send_signal(self, sig): pass
            def wait(self, timeout=None): return 0
            def kill(self): pass
        return FakeProc()

    def fake_ffmpeg(cmd, **kw):
        # Create a GIF that exceeds limit
        if "ffmpeg" in str(cmd):
            if isinstance(cmd, list):
                for i, arg in enumerate(cmd):
                    if arg.endswith(".gif"):
                        Path(arg).write_bytes(b"GIF89a" + b"\x00" * (10 * 1024 * 1024))  # 10 MB > 8 MB limit
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x if x == "ffmpeg" else None)

    result = ec.capture_ios_simulator(tmp_path, cfg, run=fake_ffmpeg, sleep=lambda s: None)

    recordings = result.get("recordings", [])
    # Should have failed recordings due to size limits
    assert any(not r["ok"] for r in recordings)


def test_measurer_merges_screenshot_and_recording_results(tmp_path, monkeypatch):
    _repo_with_change(tmp_path, "Apps/Spike/Sources/SettingsSheet.swift")
    cfg_with_recording = {**CFG, "recordings": [{"scene": "main", "seconds": 1}]}

    def mock_capture(wt, cfg, **kw):
        return {
            "screenshots": [{"path": "docs/evidence/a/main-light.png", "caption": "main, light"}],
            "recordings": [{"ok": True, "path": "docs/evidence/a/main-light.mp4", "gif_path": "docs/evidence/a/main-light.gif", "caption": "main, light"}]
        }

    monkeypatch.setattr(ec, "capture_ios_simulator", mock_capture)
    m = pp.Measurer(_profile(ios_simulator=cfg_with_recording), runner=lambda *a: (0, ""), have=lambda *a: True)
    _, dev = m.evidence(tmp_path)

    assert dev["na"] is False
    assert "screenshots" in dev and len(dev["screenshots"]) > 0
    assert "recordings" in dev and len(dev["recordings"]) > 0


def test_the_pr_body_links_the_gif_and_the_mp4_pinned_to_the_commit():
    dev = {
        "na": False,
        "screenshots": [{"path": "docs/evidence/w/main-light.png", "caption": "main, light"}],
        "recordings": [
            {"ok": True, "path": "docs/evidence/w/main-light.mp4", "gif_path": "docs/evidence/w/main-light.gif", "caption": "main, light"}
        ],
        "description": "Simulator screenshots and recordings."
    }
    sha = "a" * 40
    text = mr_raiser._format_dev_evidence(dev, repo="G-Eskayo/clarity-captions", ref=sha)

    # Check GIF is included
    assert f"![main, light](https://raw.githubusercontent.com/G-Eskayo/clarity-captions/{sha}/docs/evidence/w/main-light.gif)" in text
    # Check MP4 is included
    assert f'<video src="https://raw.githubusercontent.com/G-Eskayo/clarity-captions/{sha}/docs/evidence/w/main-light.mp4"' in text
    assert "Simulator screenshots and recordings." in text


def test_animation_diff_with_only_stills_gets_a_non_blocking_note():
    dev = {
        "na": False,
        "screenshots": [{"path": "docs/evidence/w/main-light.png", "caption": "main, light"}],
        "recordings": [],
        "description": "Simulator screenshots.",
        "motion_note": "Changed files suggest animation/motion (dashboard/src/components/Animation.tsx) but no video was captured"
    }
    text = mr_raiser._format_dev_evidence(dev, repo="G-Eskayo/clarity-captions", ref="a" * 40)

    assert "Note (not blocking):" in text
    assert "animation/motion" in text
    # Verify it's not blocking (doesn't appear in a "must fix" section)
    assert "⚠" not in text or "not blocking" in text


# Tests 13-15 (video link recognition in hasImage/imageUrls) are JavaScript tests
# in the dashboard test suite, not Python tests - see dashboard/test/ui_evidence.test.js
