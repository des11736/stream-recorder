import re
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Lock

from .events import LogEvent
from .urls import mask_stream_url

_URL_PATTERN = re.compile(r"(?:rtmp|rtmps|rtsp|https?)://[^\s'\"<>]+", re.IGNORECASE)


def sanitize_log_text(text: str) -> str:
    """Mask stream credentials wherever an FFmpeg line prints a source URL."""
    return _URL_PATTERN.sub(lambda match: mask_stream_url(match.group(0)), text)


class EventLogger:
    """Write durable UTF-8 diagnostics and publish application events to the UI."""

    def __init__(self, log_dir: Path, queue: Queue[LogEvent]) -> None:
        self.log_dir = log_dir
        self.queue = queue
        self._lock = Lock()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.raw_path = self.log_dir / "ffmpeg-脱敏原始输出.log"

    @property
    def application_path(self) -> Path:
        return self.log_dir / f"应用日志-{datetime.now():%Y-%m-%d}.log"

    def log(self, event: LogEvent) -> None:
        timestamp = event.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = (
            f"[{timestamp}] [{event.severity.value}] [{event.task_id}] "
            f"[{event.category}] {event.message}\n"
        )
        with self._lock, self.application_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        self.queue.put(event)

    def raw(self, line: str) -> None:
        with self._lock, self.raw_path.open("a", encoding="utf-8") as handle:
            handle.write(sanitize_log_text(line).rstrip() + "\n")
