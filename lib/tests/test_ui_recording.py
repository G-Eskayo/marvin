"""Video recording conversion: MOV to GIF/MP4 for PR evidence."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui_recording as ur  # noqa: E402


class FakeRun:
    """Mock subprocess.run: records commands, creates output files."""

    def __init__(self, mov_size=5_000_000, fail_on=None, gif_size=None, mp4_size=None):
        self.calls = []
        self.mov_size = mov_size
        self.fail_on = fail_on
        self.gif_size = gif_size if gif_size is not None else 2_000_000
        self.mp4_size = mp4_size if mp4_size is not None else 8_000_000

    def __call__(self, cmd, check=False, capture_output=False, text=False):
        self.calls.append(cmd)
        if self.fail_on and (self.fail_on in cmd or any(self.fail_on in str(arg) for arg in cmd)):
            e = subprocess.CalledProcessError(1, cmd)
            e.stderr = f"{self.fail_on} failed"
            e.stdout = ""
            raise e

        # Create output file when ffmpeg writes to it
        for i, arg in enumerate(cmd):
            if arg.endswith('.gif'):
                Path(arg).write_bytes(b'GIF' + b'\x00' * (self.gif_size - 3))
            elif arg.endswith('.mp4'):
                Path(arg).write_bytes(b'MP4' + b'\x00' * (self.mp4_size - 3))

        if capture_output:
            return type('R', (), {'stdout': '', 'stderr': 'mock output'})()
        return type('R', (), {})() if check else None


def test_conversion_success_creates_both_files(tmp_path):
    """Happy path: creates both GIF and MP4."""
    mov = tmp_path / "scene.mov"
    mov.write_bytes(b"MOV" + b"\x00" * 1000)
    run = FakeRun()
    result = ur.convert_to_gif_and_mp4(mov, tmp_path, "scene", run=run)
    assert result["gif"] == "scene.gif" and result["mp4"] == "scene.mp4"
    assert result["error"] is None
    assert (tmp_path / "scene.gif").exists() and (tmp_path / "scene.mp4").exists()


def test_missing_ffmpeg(tmp_path, monkeypatch):
    """When ffmpeg is not available."""
    mov = tmp_path / "scene.mov"
    mov.write_bytes(b"MOV")

    import shutil
    monkeypatch.setattr(shutil, "which", lambda x: None if x == "ffmpeg" else shutil.which(x))

    result = ur.convert_to_gif_and_mp4(mov, tmp_path, "scene", run=FakeRun())
    assert result["error"] == "ffmpeg not found"
    assert result["gif"] is None and result["mp4"] is None


def test_gif_conversion_failure(tmp_path):
    """When GIF conversion fails (ffmpeg error)."""
    mov = tmp_path / "scene.mov"
    mov.write_bytes(b"MOV")
    run = FakeRun(fail_on="palettegen")

    result = ur.convert_to_gif_and_mp4(mov, tmp_path, "scene", run=run)
    assert "GIF conversion failed" in result["error"]
    assert result["gif"] is None


def test_mp4_conversion_failure(tmp_path):
    """When MP4 conversion fails (ffmpeg error)."""
    mov = tmp_path / "scene.mov"
    mov.write_bytes(b"MOV")

    class PartialFailRun(FakeRun):
        def __call__(self, cmd, **kw):
            if 'scale=720:-2' in ' '.join(cmd):
                e = subprocess.CalledProcessError(1, cmd)
                e.stderr = "ffmpeg failed on MP4"
                e.stdout = ""
                raise e
            return super().__call__(cmd, **kw)

    run = PartialFailRun()
    result = ur.convert_to_gif_and_mp4(mov, tmp_path, "scene", run=run)
    assert result["gif"] == "scene.gif"
    assert "MP4 conversion failed" in result["error"]
    assert result["mp4"] is None
