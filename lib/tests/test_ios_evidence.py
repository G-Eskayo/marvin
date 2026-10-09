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
    """Records commands; xcodebuild 'builds' the .app into the derived-data folder it was given; screenshot writes a file."""

    def __init__(self, fail_on=None, boot_error=None):
        self.calls, self.fail_on, self.boot_error = [], fail_on, boot_error

    def __call__(self, cmd, cwd=None, **kw):
        self.calls.append((list(cmd), str(cwd) if cwd else None))
        if self.fail_on and self.fail_on in cmd:
            raise subprocess.CalledProcessError(65, cmd, output="", stderr=f"{self.fail_on} failed: error: something broke")
        if cmd[0] == "xcodebuild":
            dd = Path(cmd[cmd.index("-derivedDataPath") + 1])
            (dd / "Build/Products/Debug-iphonesimulator/CaptionSpike.app").mkdir(parents=True, exist_ok=True)
        if cmd[:3] == ["xcrun", "simctl", "boot"] and self.boot_error:
            raise subprocess.CalledProcessError(149, cmd, stderr=self.boot_error)
        if cmd[:4] == ["xcrun", "simctl", "io", "booted"]:
            Path(cmd[-1]).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_captures_every_scene_in_light_and_dark_into_the_worktree(tmp_path):
    run = FakeRun()
    shots = ec.capture_ios_simulator(tmp_path, CFG, run=run, sleep=lambda s: None)
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
    shots = ec.capture_ios_simulator(tmp_path, CFG, run=FakeRun(boot_error=real), sleep=lambda s: None)
    assert len(shots) == 4


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
    monkeypatch.setattr(ec, "capture_ios_simulator", lambda wt, cfg, **kw: seen.setdefault("shots", [{"path": "docs/evidence/a.png", "caption": "main, light"}]))
    m = pp.Measurer(_profile(ios_simulator=CFG), runner=lambda *a: (0, ""), have=lambda *a: True)
    _, dev = m.evidence(tmp_path)
    assert dev["na"] is False and dev["screenshots"] == seen["shots"]


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


def test_the_pr_body_shows_each_screenshot_from_the_pushed_branch():
    dev = {"na": False, "screenshots": [{"path": "docs/evidence/w/main-light.png", "caption": "main, light"}],
           "description": "Simulator screenshots."}
    text = mr_raiser._format_dev_evidence(dev, repo="G-Eskayo/clarity-captions", branch="pipeline/g-eskayo/clarity-captions#7")
    assert "![main, light](https://github.com/G-Eskayo/clarity-captions/blob/pipeline/g-eskayo/clarity-captions%237/docs/evidence/w/main-light.png?raw=true)" in text
    assert "Simulator screenshots." in text


def test_gate_info_carries_the_projects_ui_paths(tmp_path):
    info = pp.gate_info(_profile(), catalog={}, have=lambda *a: True)
    assert info["ui_paths"] == ["Apps/**/*.swift"]
