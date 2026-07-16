import os
import shutil
import sys
from pathlib import Path


def application_root() -> Path:
    """Return PyInstaller's extraction root when bundled, otherwise the project root."""
    extracted = getattr(sys, "_MEIPASS", None)
    if extracted:
        return Path(extracted)
    return Path(__file__).resolve().parents[2]


def locate_ffmpeg_tools(root: Path | None = None) -> tuple[Path, Path]:
    """Find the packaged executables before considering developer-machine fallbacks."""
    base = root or application_root()
    for directory in (base / "ffmpeg", base / "bundled" / "ffmpeg"):
        ffmpeg = directory / "ffmpeg.exe"
        ffprobe = directory / "ffprobe.exe"
        if ffmpeg.is_file() and ffprobe.is_file():
            return ffmpeg, ffprobe

    configured_ffmpeg = os.environ.get("STREAM_RECORDER_FFMPEG")
    if configured_ffmpeg:
        ffmpeg = Path(configured_ffmpeg)
        ffprobe = ffmpeg.with_name("ffprobe.exe")
        if ffmpeg.is_file() and ffprobe.is_file():
            return ffmpeg, ffprobe

    path_ffmpeg = shutil.which("ffmpeg")
    path_ffprobe = shutil.which("ffprobe")
    if path_ffmpeg and path_ffprobe:
        return Path(path_ffmpeg), Path(path_ffprobe)
    raise RuntimeError("未找到内置 FFmpeg/FFprobe。请重新安装完整程序包。")
