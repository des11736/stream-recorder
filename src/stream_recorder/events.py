import re
from dataclasses import dataclass, field
from datetime import datetime

from .models import Severity


@dataclass(frozen=True)
class LogEvent:
    timestamp: datetime = field(default_factory=datetime.now)
    severity: Severity = Severity.INFO
    task_id: str = ""
    category: str = ""
    message: str = ""


MONITOR_PTS_JUMP_THRESHOLD_SECONDS = 10.0
_MONITOR_MEDIA_TIME = re.compile(
    r"\bframe=\s*\d+.*?\btime=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)"
)


def parse_monitor_media_time(line: str) -> float | None:
    """Extract the media timestamp from one FFmpeg video-monitor status line."""
    match = _MONITOR_MEDIA_TIME.search(line)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _format_monitor_media_time(seconds: float) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, second_part = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{second_part:05.2f}"


def build_pts_jump_event(
    task_id: str, previous_seconds: float, current_seconds: float
) -> LogEvent | None:
    """Return a warning when consecutive monitor timestamps jump forward."""
    jump_seconds = current_seconds - previous_seconds
    if jump_seconds < MONITOR_PTS_JUMP_THRESHOLD_SECONDS:
        return None
    return LogEvent(
        severity=Severity.WARNING,
        task_id=task_id,
        category="PTS 时间戳跳变",
        message=(
            f"原始视频时间从 {_format_monitor_media_time(previous_seconds)} 跳至 "
            f"{_format_monitor_media_time(current_seconds)}（前跳 {jump_seconds:.2f} 秒）；"
            "上游流可能丢失画面或时间戳异常，收录继续。"
        ),
    )


def parse_ffmpeg_line(task_id: str, line: str) -> LogEvent | None:
    """Translate actionable FFmpeg diagnostics into a concise Chinese event."""
    lowered = line.lower()
    if any(
        token in lowered
        for token in (
            "dropping old packet",
            "max delay reached",
            "discarding packet",
            "non-monotonous dts",
            "invalid dts",
        )
    ):
        return LogEvent(
            severity=Severity.WARNING,
            task_id=task_id,
            category="接收端丢帧/丢包",
            message="检测到接收端丢帧或丢包；建议检查网络带宽、抖动和源端码率",
        )

    if any(
        token in lowered
        for token in (
            "connection timed out",
            "connection refused",
            "broken pipe",
            "connection reset",
            "end of file",
        )
    ):
        return LogEvent(
            severity=Severity.ERROR,
            task_id=task_id,
            category="断流",
            message="流连接中断或超时；程序将按策略自动重连",
        )

    if "output file is empty" in lowered or "no packets were received" in lowered:
        return LogEvent(
            severity=Severity.WARNING,
            task_id=task_id,
            category="无有效画面",
            message="原始视频信号未输出有效画面；请检查摄像机、地址和源端状态",
        )

    return None
