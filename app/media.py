"""Petits outils autour de ffmpeg."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import config


class RenderError(RuntimeError):
    pass


def run_ffmpeg(args: list[str], what: str = "ffmpeg", cwd: Path | None = None) -> None:
    cmd = [config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise RenderError(f"{what} a échoué : " + " | ".join(tail))


def probe_duration(path: Path) -> float:
    proc = subprocess.run(
        [config.FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        raise RenderError(f"Durée illisible pour {path.name}")


def x264(crf: int = 21, preset: str | None = None) -> list[str]:
    return ["-c:v", "libx264", "-preset", preset or config.X264_PRESET, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-r", str(config.FPS)]
