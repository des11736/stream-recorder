import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import stream_recorder.ffmpeg_tools as ffmpeg_tools
from stream_recorder.ffmpeg_tools import (
    build_anomaly_monitor_command,
    build_probe_command,
    build_recorder_command,
    parse_probe_json,
    run_probe,
)
from stream_recorder.models import OutputFormat, TaskConfig


def _config(tmp_path: Path, source_url: str = "rtsp://example.com/live") -> TaskConfig:
    return TaskConfig("task-1", "前门摄像头", source_url, tmp_path)


def test_h265_probe_builds_stream_copy_fmp4_hls_command(tmp_path: Path) -> None:
    info = parse_probe_json(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "25/1",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        }
    )

    command = build_recorder_command(Path("ffmpeg.exe"), _config(tmp_path), info, tmp_path / "output")

    assert info.video_codec == "H.265"
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "copy"
    assert command[command.index("-hls_segment_type") + 1] == "fmp4"
    assert command[command.index("-rtsp_transport") + 1] == "tcp"
    assert command[command.index("-hls_fmp4_init_filename") + 1] == "init.mp4"
    assert command[command.index("-hls_segment_filename") + 1] == "segment_%012d.m4s"
    assert command[-1] == "index.m3u8"


def test_non_aac_audio_is_transcoded_but_video_is_not(tmp_path: Path) -> None:
    info = parse_probe_json(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "avg_frame_rate": "30/1",
                },
                {"codec_type": "audio", "codec_name": "pcm_mulaw"},
            ]
        }
    )
    command = build_recorder_command(Path("ffmpeg.exe"), _config(tmp_path), info, tmp_path / "output")

    assert info.video_codec == "H.264"
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "aac"


def test_rejects_unsupported_video_codec() -> None:
    with pytest.raises(ValueError, match="H.264.*H.265"):
        parse_probe_json({"streams": [{"codec_type": "video", "codec_name": "vp9"}]})


def test_mp4_command_uses_fragmented_mp4_and_not_hls(tmp_path: Path) -> None:
    info = parse_probe_json(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "25/1",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        }
    )
    config = TaskConfig(
        "task-1",
        "前门摄像头",
        "rtsp://example.com/live",
        tmp_path,
        output_format=OutputFormat.MP4,
    )

    command = build_recorder_command(Path("ffmpeg.exe"), config, info, tmp_path / "output")

    assert command[command.index("-f") + 1] == "mp4"
    assert command[command.index("-movflags") + 1] == "frag_keyframe+empty_moov+default_base_moof"
    assert command[-1] == "recording.mp4"
    assert "-hls_time" not in command


def test_anomaly_monitor_uses_only_low_frame_rate_decode(tmp_path: Path) -> None:
    command = build_anomaly_monitor_command(Path("ffmpeg.exe"), _config(tmp_path, "http://example.com/live"))
    filtergraph = command[command.index("-vf") + 1]

    assert filtergraph == "fps=1"
    assert "blackdetect" not in filtergraph
    assert "freezedetect" not in filtergraph


def test_run_probe_preserves_subprocess_contract_and_passes_hidden_console_options(monkeypatch) -> None:
    received: dict[str, object] = {}
    hidden_options = {"creationflags": 0x08000000}
    ffprobe = Path("ffprobe.exe")
    source_url = "http://example.com/live"
    monkeypatch.setattr(ffmpeg_tools, "hidden_console_kwargs", lambda: hidden_options)

    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        received["command"] = command
        received.update(kwargs)
        return SimpleNamespace(
            stdout=(
                '{"streams": [{"codec_type": "video", "codec_name": "h264", '
                '"width": 1920, "height": 1080, "avg_frame_rate": "25/1"}]}'
            )
        )

    info = run_probe(ffprobe, source_url, runner=runner)

    assert info.video_codec == "H.264"
    assert received["command"] == build_probe_command(ffprobe, source_url)
    assert received["capture_output"] is True
    assert received["check"] is True
    assert received["encoding"] == "utf-8"
    assert received["errors"] == "replace"
    assert received["timeout"] == 20
    assert received["creationflags"] == hidden_options["creationflags"]


def test_run_probe_omits_creationflags_when_helper_returns_no_options(monkeypatch) -> None:
    received: dict[str, object] = {}
    monkeypatch.setattr(ffmpeg_tools, "hidden_console_kwargs", lambda: {})

    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        received["command"] = command
        received.update(kwargs)
        return SimpleNamespace(
            stdout=(
                '{"streams": [{"codec_type": "video", "codec_name": "h264", '
                '"width": 1920, "height": 1080, "avg_frame_rate": "25/1"}]}'
            )
        )

    run_probe(Path("ffprobe"), "http://example.com/live", runner=runner)

    assert "creationflags" not in received
