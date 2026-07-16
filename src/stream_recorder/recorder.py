import re
import subprocess
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic

from .event_logger import EventLogger
from .events import (
    LogEvent,
    build_pts_jump_event,
    parse_ffmpeg_line,
    parse_monitor_media_time,
)
from .ffmpeg_tools import build_anomaly_monitor_command, build_recorder_command
from .models import OutputFormat, Severity, StreamInfo, TaskConfig, TaskStatus
from .subprocess_options import hidden_console_kwargs


def retry_delays(max_retries: int) -> Iterator[int]:
    """Return the bounded exponential backoff used after interrupted streams."""
    yield from (2, 4, 8, 16, 30)[: max(0, min(max_retries, 5))]


def is_media_progress_line(line: str) -> bool:
    """Identify FFmpeg progress fields that prove media continues to arrive."""
    return line.startswith(("out_time_us=", "out_time_ms=", "out_time="))


def task_output_directory(output_root: Path, name: str, stamp: str | None = None) -> Path:
    """Create a deterministic, Windows-safe directory name for one recording."""
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._") or "未命名任务"
    safe_name = re.sub(r"\s*_\s*", "_", safe_name)
    timestamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_root / f"{safe_name}_{timestamp}"


def recording_target(config: TaskConfig, output_dir: Path) -> Path:
    """Return the primary file created for the configured recording format."""
    filename = "recording.mp4" if config.output_format is OutputFormat.MP4 else "index.m3u8"
    return output_dir / filename


class Recorder:
    """Run one HLS or MP4 writer and an optional anomaly-monitor process."""

    def __init__(
        self,
        config: TaskConfig,
        ffmpeg: Path,
        logger: EventLogger,
        output_dir: Path,
        on_status: Callable[[TaskStatus], None] | None = None,
        process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.config = config
        self.ffmpeg = ffmpeg
        self.logger = logger
        self.output_dir = output_dir
        self._on_status = on_status or (lambda _status: None)
        self._process_factory = process_factory
        self._stop_requested = Event()
        self._state_lock = Lock()
        self._status = TaskStatus.STOPPED
        self._recorder_process: subprocess.Popen | None = None
        self._monitor_process: subprocess.Popen | None = None
        self._last_media_at = 0.0
        self._last_frame_at = 0.0
        self._last_monitor_media_time: float | None = None
        self._no_frame_reported = False
        self._playlist_announced = False

    @property
    def status(self) -> TaskStatus:
        with self._state_lock:
            return self._status

    def _set_status(self, status: TaskStatus) -> None:
        with self._state_lock:
            self._status = status
        self._on_status(status)

    def _emit(self, severity: Severity, category: str, message: str) -> None:
        self.logger.log(
            LogEvent(
                severity=severity,
                task_id=self.config.task_id,
                category=category,
                message=message,
            )
        )

    def start(self, info: StreamInfo) -> None:
        if self.status in {TaskStatus.RECORDING, TaskStatus.RECONNECTING}:
            return
        self._stop_requested.clear()
        Thread(target=self._run, args=(info,), name=f"recorder-{self.config.task_id}", daemon=True).start()

    def _reset_attempt_state(self) -> None:
        self._last_media_at = monotonic()
        self._last_frame_at = monotonic()
        self._last_monitor_media_time = None
        self._no_frame_reported = False

    def stop(self) -> None:
        self._stop_requested.set()
        self._terminate_children()

    def _run(self, info: StreamInfo) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        retry_schedule = (0, *retry_delays(self.config.max_retries))

        for attempt, delay in enumerate(retry_schedule):
            if attempt:
                self._set_status(TaskStatus.RECONNECTING)
            if self._stop_requested.wait(delay):
                self._set_status(TaskStatus.STOPPED)
                return
            if attempt:
                self._emit(
                    Severity.WARNING,
                    "重连",
                    f"正在第 {attempt}/{self.config.max_retries} 次自动重连",
                )

            self._set_status(TaskStatus.RECORDING)
            self._reset_attempt_state()

            if self._run_once(info):
                self._set_status(TaskStatus.STOPPED)
                return

            if self._stop_requested.is_set():
                self._set_status(TaskStatus.STOPPED)
                return

            if self.config.enable_anomaly_detection:
                self._emit(Severity.ERROR, "断流", "收录进程意外结束；将尝试自动重连")

        self._set_status(TaskStatus.FAILED)
        if self.config.enable_anomaly_detection:
            self._emit(Severity.ERROR, "收录失败", "自动重连次数已用尽；请检查地址、网络和源端状态")

    def _run_once(self, info: StreamInfo) -> bool:
        command = build_recorder_command(self.ffmpeg, self.config, info, self.output_dir)
        target = recording_target(self.config, self.output_dir)
        try:
            self._recorder_process = self._process_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=self.output_dir,
                **hidden_console_kwargs(),
            )
        except OSError as error:
            self._emit(Severity.ERROR, "启动失败", f"无法启动 FFmpeg：{error}")
            return False

        self._emit(Severity.INFO, "收录", f"已开始收录，目标文件：{target}")
        self._start_reader_threads(self._recorder_process, monitor=False)
        if self.config.enable_anomaly_detection:
            self._start_anomaly_monitor()

        while self._recorder_process.poll() is None and not self._stop_requested.wait(0.25):
            now = monotonic()
            if now - self._last_media_at > 15:
                if self.config.enable_anomaly_detection:
                    self._emit(Severity.ERROR, "断流", "15 秒未接收到有效媒体数据；正在重连")
                self._recorder_process.terminate()
                break
            if self.config.enable_anomaly_detection and not self._no_frame_reported and now - self._last_frame_at > 20:
                self._no_frame_reported = True
                self._emit(Severity.WARNING, "无有效画面", "原始视频信号 20 秒未解出有效画面")
            if (
                self.config.output_format is OutputFormat.HLS
                and not self._playlist_announced
                and target.exists()
            ):
                self._playlist_announced = True
                self._emit(Severity.INFO, "HLS", "已生成 HLS 清单：index.m3u8")

        self._terminate_children()
        return self._stop_requested.is_set()

    def _start_anomaly_monitor(self) -> None:
        try:
            self._monitor_process = self._process_factory(
                build_anomaly_monitor_command(self.ffmpeg, self.config),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **hidden_console_kwargs(),
            )
        except OSError as error:
            self._emit(Severity.WARNING, "异常检测", f"无法启动异常检测：{error}")
            return
        self._start_reader_threads(self._monitor_process, monitor=True)

    def _start_reader_threads(self, process: subprocess.Popen, monitor: bool) -> None:
        if process.stdout is not None:
            Thread(
                target=self._read_stdout,
                args=(process.stdout,),
                name=f"progress-{self.config.task_id}",
                daemon=True,
            ).start()
        if process.stderr is not None:
            Thread(
                target=self._read_stderr,
                args=(process.stderr, monitor),
                name=f"stderr-{self.config.task_id}",
                daemon=True,
            ).start()

    def _read_stdout(self, stream) -> None:
        for line in stream:
            if is_media_progress_line(line):
                self._last_media_at = monotonic()

    def _read_stderr(self, stream, monitor: bool) -> None:
        for line in stream:
            self.logger.raw(line)
            if monitor and "frame=" in line:
                self._last_frame_at = monotonic()
            if monitor and self.config.enable_anomaly_detection:
                current_media_time = parse_monitor_media_time(line)
                if current_media_time is not None:
                    previous_media_time = self._last_monitor_media_time
                    self._last_monitor_media_time = current_media_time
                    if previous_media_time is not None:
                        event = build_pts_jump_event(
                            self.config.task_id,
                            previous_media_time,
                            current_media_time,
                        )
                        if event is not None:
                            self.logger.log(event)
            if self.config.enable_anomaly_detection:
                event = parse_ffmpeg_line(self.config.task_id, line)
                if event is not None:
                    self.logger.log(event)

    def _terminate_children(self) -> None:
        for process in (self._recorder_process, self._monitor_process):
            if process is not None and process.poll() is None:
                process.terminate()
