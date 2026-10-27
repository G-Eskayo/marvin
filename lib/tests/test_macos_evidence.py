"""marvin #727: Mac apps carry images too. The pipeline builds the app and runs each scene with -MarvinScreenshot,
the app draws itself into a PNG and quits (the contract in config/onboarding/macos-screenshot/)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evidence_capture as ec  # noqa: E402
import project_profile as pp  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
XCODE = {"project_dir": "App", "prepare": [["xcodegen", "generate"]], "project": "MarvinVoice.xcodeproj",
         "scheme": "MarvinVoice", "scenes": [{"name": "menu", "args": ["-MarvinScene", "menu"]},
                                             {"name": "pill", "args": ["-MarvinScene", "pill"]}]}
SWIFTPM = {"swiftpm_product": "KillerSudoku", "scenes": [{"name": "board", "args": []}]}


class FakeRun:
    """xcodebuild 'builds' an .app into the derived-data folder it was given, swift build a binary into .build/debug;
    the app writes `writes` to the -MarvinScreenshot path (None: writes nothing)."""

    def __init__(self, writes=PNG, fail_on=None):
        self.calls, self.writes, self.fail_on = [], writes, fail_on

    def __call__(self, cmd, cwd=None, **kw):
        self.calls.append((list(cmd), str(cwd) if cwd else None, kw))
        if self.fail_on and self.fail_on in cmd[0]:
            raise subprocess.CalledProcessError(65, cmd, output="", stderr="error: something broke")
        if cmd[0] == "xcodebuild":
            dd = Path(cmd[cmd.index("-derivedDataPath") + 1])
            (dd / "Build/Products/Debug/MARVIN Voice.app/Contents/MacOS").mkdir(parents=True, exist_ok=True)
            (dd / "Build/Products/Debug/MARVIN Voice.app/Contents/MacOS/MARVIN Voice").write_text("")
        if cmd[:2] == ["swift", "build"]:
            (Path(cwd) / ".build/debug").mkdir(parents=True, exist_ok=True)
            (Path(cwd) / ".build/debug/KillerSudoku").write_text("")
        if "-MarvinScreenshot" in cmd and self.writes is not None:
            Path(cmd[cmd.index("-MarvinScreenshot") + 1]).write_bytes(self.writes)
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _app_runs(run):
    return [(c, kw) for c, _, kw in run.calls if "-MarvinScreenshot" in c]


def test_every_scene_is_captured_in_light_and_dark_into_the_worktree(tmp_path):
    run = FakeRun()
    shots = ec.capture_macos_app(tmp_path, XCODE, run=run)
    assert [s["caption"] for s in shots] == ["menu, light", "pill, light", "menu, dark", "pill, dark"]
    for s in shots:
        assert not Path(s["path"]).is_absolute() and (tmp_path / s["path"]).read_bytes() == PNG
    cmds = [c for c, _, _ in run.calls]
    assert ["xcodegen", "generate"] in cmds
    build = next(c for c in cmds if c[0] == "xcodebuild")
    assert "platform=macOS" in build and "CODE_SIGN_IDENTITY=-" in build
    first, kw = _app_runs(run)[0]
    assert first[0].endswith("MARVIN Voice.app/Contents/MacOS/MARVIN Voice")
    assert first[1:3] == ["-MarvinScene", "menu"] and first[first.index("-MarvinAppearance") + 1] == "light"
    assert kw.get("timeout"), "a hung app must not hang the pipeline"


def test_a_swiftpm_app_is_built_with_swift_build_and_run_from_build_debug(tmp_path):
    run = FakeRun()
    shots = ec.capture_macos_app(tmp_path, SWIFTPM, run=run)
    assert len(shots) == 2
    assert ["swift", "build", "--product", "KillerSudoku"] in [c for c, _, _ in run.calls]
    assert _app_runs(run)[0][0][0] == str(tmp_path / ".build/debug/KillerSudoku")


def test_an_app_that_ignores_the_contract_is_named_plainly(tmp_path):
    with pytest.raises(RuntimeError, match="-MarvinScreenshot"):
        ec.capture_macos_app(tmp_path, SWIFTPM, run=FakeRun(writes=None))


def test_a_file_that_is_not_a_png_is_refused(tmp_path):
    # An app that writes an error message or an empty file must not reach the PR as a "screenshot".
    with pytest.raises(RuntimeError, match="not a PNG"):
        ec.capture_macos_app(tmp_path, SWIFTPM, run=FakeRun(writes=b""))


def test_a_hung_app_is_reported_not_waited_on_forever(tmp_path):
    def run(cmd, cwd=None, **kw):
        if "-MarvinScreenshot" in cmd:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return FakeRun()(cmd, cwd, **kw)
    with pytest.raises(RuntimeError, match="did not finish"):
        ec.capture_macos_app(tmp_path, SWIFTPM, run=run)


def test_a_failed_build_raises_with_the_reason(tmp_path):
    with pytest.raises(RuntimeError, match="something broke"):
        ec.capture_macos_app(tmp_path, XCODE, run=FakeRun(fail_on="xcodebuild"))


@pytest.mark.parametrize("bad", [{}, {**SWIFTPM, "scenes": []}, {"scenes": [{"name": "a"}]},
                                 {**XCODE, "scheme": ""}, {**SWIFTPM, "scenes": [{"name": "../escape"}]}])
def test_an_incomplete_or_unsafe_config_is_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        ec.capture_macos_app(tmp_path, bad, run=FakeRun())


def _repo_with_change(path, rel):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base"], cwd=path, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "work"], cwd=path, check=True)
    (path / rel).parent.mkdir(parents=True, exist_ok=True)
    (path / rel).write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "c"], cwd=path, check=True)


def _profile(**dev):
    return pp._validate({"repo": "G-Eskayo/marvin-voice", "verify": [{"id": "t", "command": ["true"]}],
                         "evidence": {"ui_paths": ["App/Sources/**"], "dev": dev}}, "test")


def test_the_measurer_captures_a_mac_app_on_a_ui_change(tmp_path, monkeypatch):
    _repo_with_change(tmp_path, "App/Sources/MarvinVoiceApp.swift")
    monkeypatch.setattr(ec, "capture_macos_app", lambda wt, cfg, **kw: [{"path": "docs/evidence/w/menu-light.png", "caption": "menu, light"}])
    _, dev = pp.Measurer(_profile(macos_app=XCODE), runner=lambda *a: (0, ""), have=lambda *a: True).evidence(tmp_path)
    assert dev["na"] is False and dev["screenshots"][0]["caption"] == "menu, light"
    assert "macOS" in dev["description"]


def test_a_mac_capture_failure_is_reported_not_raised(tmp_path, monkeypatch):
    _repo_with_change(tmp_path, "App/Sources/MarvinVoiceApp.swift")
    def boom(*a, **k):
        raise RuntimeError("the app did not write a screenshot")
    monkeypatch.setattr(ec, "capture_macos_app", boom)
    _, dev = pp.Measurer(_profile(macos_app=XCODE), runner=lambda *a: (0, ""), have=lambda *a: True).evidence(tmp_path)
    assert dev["na"] is False and "did not write" in dev["error"]


def test_the_executor_is_told_how_to_reach_a_screen_when_mac_capture_is_on():
    notes = pp.playbook_notes({"repo": "G-Eskayo/x", "playbook": "ios-app", "playbook_variant": "macos",
                               "evidence": {"dev": {"macos_app": SWIFTPM}}})
    assert "-MarvinScreenshot" in notes and "don't capture" not in notes


HELPER = Path(__file__).resolve().parents[2] / "config/onboarding/macos-screenshot/MarvinScreenshot.swift"


@pytest.mark.skipif(not shutil.which("swift") or sys.platform != "darwin", reason="needs Swift on a Mac")
def test_the_reference_helper_really_draws_a_swiftui_app_into_a_png(tmp_path):
    """No fakes: a real SwiftPM app using the helper we hand to projects, built and captured by the real pipeline code."""
    (tmp_path / "Sources/Demo").mkdir(parents=True)
    (tmp_path / "Package.swift").write_text(
        '// swift-tools-version:5.9\nimport PackageDescription\n'
        'let package = Package(name: "Demo", platforms: [.macOS(.v14)], targets: [.executableTarget(name: "Demo")])\n')
    shutil.copy(HELPER, tmp_path / "Sources/Demo/MarvinScreenshot.swift")
    (tmp_path / "Sources/Demo/main.swift").write_text(
        'import AppKit\nimport SwiftUI\n'
        'let scene = UserDefaults.standard.string(forKey: "MarvinScene") ?? "main"\n'
        'MainActor.assumeIsolated {\n'
        '    MarvinScreenshot.runIfRequested { Text("scene: \\(scene)").padding(40).frame(width: 240, height: 120) }\n'
        '}\n'
        'print("normal launch")\n')
    cfg = {"swiftpm_product": "Demo", "scenes": [{"name": "main", "args": ["-MarvinScene", "main"]}], "timeout_s": 600}
    shots = ec.capture_macos_app(tmp_path, cfg)
    assert [s["caption"] for s in shots] == ["main, light", "main, dark"]
    light, dark = [(tmp_path / s["path"]).read_bytes() for s in shots]
    assert light[:8] == PNG[:8] and dark[:8] == PNG[:8]
    assert light != dark, "dark appearance must actually change the drawing"


def _derived_dirs(run):
    return [Path(c[c.index("-derivedDataPath") + 1]) for c, _, _ in run.calls if c[0] == "xcodebuild"]


def test_the_build_folder_is_removed_after_capture(tmp_path):
    # Each Xcode build is ~1 GB; left behind they filled the Mini's disk until the merge gate's disk check refused (2026-10-27).
    run = FakeRun()
    ec.capture_macos_app(tmp_path, XCODE, run=run)
    assert _derived_dirs(run) and not any(d.exists() for d in _derived_dirs(run))


def test_the_build_folder_is_removed_when_capture_fails_too(tmp_path):
    run = FakeRun(writes=None)
    with pytest.raises(RuntimeError):
        ec.capture_macos_app(tmp_path, XCODE, run=run)
    assert not any(d.exists() for d in _derived_dirs(run))
