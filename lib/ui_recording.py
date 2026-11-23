#!/usr/bin/env python3
"""UI video recording and conversion: MOV to GIF and MP4 for PR evidence.
Driven by evidence_capture.capture_ios_simulator when a profile lists recordings."""
from __future__ import annotations
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

GIF_MAX_BYTES = 8 * 1024 * 1024
MP4_MAX_BYTES = 50 * 1024 * 1024


def convert_to_gif_and_mp4(
    mov_path: Path | str,
    out_dir: Path | str,
    name: str,
    *,
    run: Callable = subprocess.run,
) -> dict:
    """Convert a MOV file to GIF and MP4 for PR evidence.

    Returns {"gif": path|None, "mp4": path|None, "error": str|None}.
    Paths are relative to out_dir when successfully created; None when conversion
    skipped/failed due to size limits. Error is set on ffmpeg failure."""
    mov_path = Path(mov_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not shutil.which("ffmpeg"):
        return {"gif": None, "mp4": None, "error": "ffmpeg not found"}

    result = {"gif": None, "mp4": None, "error": None}

    gif_path = out_dir / f"{name}.gif"
    mp4_path = out_dir / f"{name}.mp4"

    # GIF: palette-based, 128 colors, bayer dither (from merge_motion_evidence.mjs)
    try:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(mov_path),
            "-filter_complex", "fps=20,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
            str(gif_path),
        ]
        run(cmd, check=True, capture_output=True, text=True)

        # Check size; downscale if needed
        if gif_path.stat().st_size > GIF_MAX_BYTES:
            gif_path.unlink()
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(mov_path),
                "-filter_complex", "fps=20,scale=iw/2:-1,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                str(gif_path),
            ]
            run(cmd, check=True, capture_output=True, text=True)
            if gif_path.stat().st_size > GIF_MAX_BYTES:
                gif_path.unlink()
                result["error"] = f"GIF exceeds {GIF_MAX_BYTES} bytes even after downscaling"
                return result

        result["gif"] = gif_path.name
    except subprocess.CalledProcessError as e:
        result["error"] = f"GIF conversion failed: {e.stderr or e.stdout or 'unknown error'}"[:300]
        gif_path.unlink(missing_ok=True)
        return result

    # MP4: simple downscale to 720p width, lanczos filter (from merge_motion_evidence.mjs)
    try:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(mov_path),
            "-vf", "fps=25,scale=720:-2:flags=lanczos",
            "-pix_fmt", "yuv420p",
            str(mp4_path),
        ]
        run(cmd, check=True, capture_output=True, text=True)

        if mp4_path.stat().st_size > MP4_MAX_BYTES:
            mp4_path.unlink()
            # Retry with more aggressive downscaling
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(mov_path),
                "-vf", "fps=20,scale=480:-2:flags=lanczos",
                "-pix_fmt", "yuv420p",
                str(mp4_path),
            ]
            run(cmd, check=True, capture_output=True, text=True)
            if mp4_path.stat().st_size > MP4_MAX_BYTES:
                mp4_path.unlink()
                result["error"] = f"MP4 exceeds {MP4_MAX_BYTES} bytes even after downscaling"
                return result

        result["mp4"] = mp4_path.name
    except subprocess.CalledProcessError as e:
        result["error"] = f"MP4 conversion failed: {e.stderr or e.stdout or 'unknown error'}"[:300]
        mp4_path.unlink(missing_ok=True)

    return result
