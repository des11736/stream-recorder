from pathlib import Path

from stream_recorder.resources import locate_ffmpeg_tools


def test_locate_ffmpeg_tools_prefers_embedded_pyinstaller_layout(tmp_path: Path) -> None:
    embedded = tmp_path / "ffmpeg"
    embedded.mkdir()
    (embedded / "ffmpeg.exe").touch()
    (embedded / "ffprobe.exe").touch()

    ffmpeg, ffprobe = locate_ffmpeg_tools(tmp_path)

    assert ffmpeg == embedded / "ffmpeg.exe"
    assert ffprobe == embedded / "ffprobe.exe"
