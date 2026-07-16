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
