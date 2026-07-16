import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from .models import OutputFormat, Protocol, StreamInfo, TaskConfig
from .subprocess_options import hidden_console_kwargs
from .urls import validate_stream_url


def parse_probe_json(payload: dict) -> StreamInfo:
    """Validate FFprobe JSON and return only the stream data needed by the app."""
    video = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if video is None:
        raise ValueError("输入流未检测到视频轨道")

    codec = str(video.get("codec_name", "")).lower()
    if codec == "h264":
        video_codec = "H.264"
    elif codec in {"hevc", "h265"}:
        video_codec = "H.265"
    else:
        raise ValueError(f"不支持的视频编码：{codec or '未知'}，仅支持 H.264 和 H.265")

    audio = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    return StreamInfo(
        video_codec=video_codec,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        frame_rate=str(video.get("avg_frame_rate", "0/0")),
        audio_codec=str(audio["codec_name"]).lower() if audio and audio.get("codec_name") else None,
    )


def build_probe_command(ffprobe: Path, source_url: str) -> list[str]:
    """Return an argument list that probes a network stream without a shell."""
    return [
        str(ffprobe),
        "-v",
        "error",
        "-rw_timeout",
        "15000000",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        source_url,
    ]


def run_probe(
    ffprobe: Path,
    source_url: str,
    timeout_seconds: int = 20,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> StreamInfo:
    """Probe one URL and raise a concise Chinese error if FFprobe cannot read it."""
    try:
        result = runner(
            build_probe_command(ffprobe, source_url),
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            **hidden_console_kwargs(),
        )
    except FileNotFoundError as error:
        raise RuntimeError("未找到内置 FFprobe，请重新安装程序") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("检测流地址超时，请检查网络、地址和源端状态") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip().splitlines()
        suffix = detail[-1] if detail else "未知连接错误"
        raise RuntimeError(f"无法读取流信号：{suffix}") from error

    try:
        return parse_probe_json(json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise RuntimeError("FFprobe 返回了无法解析的检测结果") from error


def _input_arguments(config: TaskConfig) -> list[str]:
    protocol = validate_stream_url(config.source_url)
    arguments = ["-rw_timeout", "15000000", "-fflags", "+genpts+discardcorrupt"]
    if protocol is Protocol.RTSP:
        arguments.extend(["-rtsp_transport", "tcp"])
    return [*arguments, "-i", config.source_url]


def build_recorder_command(
    ffmpeg: Path,
    config: TaskConfig,
    info: StreamInfo,
    output_dir: Path,
) -> list[str]:
    """Build stream-copy HLS or fragmented MP4 output safely for subprocess.Popen."""
    audio_codec = "copy" if info.audio_codec == "aac" else "aac"
    base = [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "repeat+level+warning",
        "-stats_period",
        "1",
        "-progress",
        "pipe:1",
        *_input_arguments(config),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        audio_codec,
    ]
    if config.output_format is OutputFormat.MP4:
        return [
            *base,
            "-f",
            "mp4",
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "recording.mp4",
        ]
    return [
        *base,
        "-f",
        "hls",
        "-hls_time",
        str(config.segment_seconds),
        "-hls_list_size",
        "0",
        "-hls_playlist_type",
        "event",
        "-hls_segment_type",
        "fmp4",
        "-hls_fmp4_init_filename",
        "init.mp4",
        "-hls_segment_filename",
        "segment_%012d.m4s",
        "-hls_start_number_source",
        "epoch",
        "-hls_flags",
        "independent_segments+temp_file+program_date_time+append_list",
        "index.m3u8",
    ]


def build_anomaly_monitor_command(ffmpeg: Path, config: TaskConfig) -> list[str]:
    """Build a low-frame-rate monitor used only to detect missing video frames."""
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "repeat+level+info",
        *_input_arguments(config),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "fps=1",
        "-f",
        "null",
        "-",
    ]
