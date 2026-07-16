import logging
import os
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from stream_recorder.ffmpeg_tools import build_recorder_command, run_probe
from stream_recorder.models import OutputFormat, TaskConfig


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args) -> None:
        logging.getLogger(__name__).debug("http request")


@pytest.fixture()
def ffmpeg_binary() -> Path:
    value = os.environ.get("FFMPEG_BINARY")
    if not value:
        pytest.skip("未设置 FFMPEG_BINARY，跳过真实 FFmpeg 集成测试")
    binary = Path(value)
    if not binary.is_file():
        pytest.skip(f"FFMPEG_BINARY 不存在：{binary}")
    return binary


@pytest.mark.integration
@pytest.mark.parametrize(
    ("encoder", "expected_codec", "output_format"),
    (
        ("libx264", "H.264", OutputFormat.HLS),
        ("libx265", "H.265", OutputFormat.HLS),
        ("libx264", "H.264", OutputFormat.MP4),
        ("libx265", "H.265", OutputFormat.MP4),
    ),
)
def test_http_stream_becomes_selected_recording_format(
    tmp_path: Path,
    ffmpeg_binary: Path,
    encoder: str,
    expected_codec: str,
    output_format: OutputFormat,
) -> None:
    source = tmp_path / f"source-{encoder}.mp4"
    generation = [
        str(ffmpeg_binary),
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=10",
        "-t",
        "2",
        "-c:v",
        encoder,
        "-threads",
        "1",
    ]
    if encoder == "libx265":
        generation.extend(["-x265-params", "log-level=error:pools=none:frame-threads=1"])
    generation.append(str(source))
    subprocess.run(generation, check=True, capture_output=True, timeout=60)

    handler = partial(QuietHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/{source.name}"
        ffprobe = ffmpeg_binary.with_name("ffprobe.exe")
        info = run_probe(ffprobe, url)
        output_dir = tmp_path / "hls"
        output_dir.mkdir()
        config = TaskConfig(
            "local-http",
            "本地 HTTP 流",
            url,
            tmp_path,
            segment_seconds=1,
            output_format=output_format,
        )
        command = build_recorder_command(ffmpeg_binary, config, info, output_dir)
        subprocess.run(command, check=True, capture_output=True, timeout=60, cwd=output_dir)

        assert info.video_codec == expected_codec
        if output_format is OutputFormat.HLS:
            playlist = output_dir / "index.m3u8"
            assert playlist.read_text(encoding="utf-8").startswith("#EXTM3U")
            assert (output_dir / "init.mp4").is_file()
            assert list(output_dir.glob("*.m4s"))
        else:
            assert (output_dir / "recording.mp4").stat().st_size > 0
    finally:
        server.shutdown()
        server.server_close()
