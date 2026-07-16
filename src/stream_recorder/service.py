from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from queue import Queue
from threading import Thread

from .event_logger import EventLogger
from .events import LogEvent
from .ffmpeg_tools import run_probe
from .models import Severity, StreamInfo, TaskConfig, TaskStatus
from .recorder import Recorder, task_output_directory
from .task_controller import TaskController


class RecordingService:
    """Bridge UI requests to background probing and independent recorder instances."""

    def __init__(
        self,
        event_queue: Queue[LogEvent],
        ffmpeg: Path,
        ffprobe: Path,
        *,
        probe: Callable[[Path, str], StreamInfo] = run_probe,
        recorder_factory: Callable[..., Recorder] = Recorder,
    ) -> None:
        self.event_queue = event_queue
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.probe = probe
        self.recorder_factory = recorder_factory
        self.controller = TaskController()

    def start(self, config: TaskConfig) -> Thread:
        """Start probing in the background so a slow network never freezes Qt."""
        worker = Thread(
            target=self._create_and_start,
            args=(config,),
            name=f"probe-{config.task_id}",
            daemon=True,
        )
        worker.start()
        return worker

    def stop(self, task_id: str) -> None:
        self.controller.stop(task_id)

    def stop_all(self) -> None:
        self.controller.stop_all()

    def _create_and_start(self, config: TaskConfig) -> None:
        output_dir = task_output_directory(config.output_root, config.name)
        logger = EventLogger(output_dir / "logs", self.event_queue)
        logger.log(
            LogEvent(
                severity=Severity.INFO,
                task_id=config.task_id,
                category="任务状态",
                message=TaskStatus.PROBING.value,
            )
        )
        logger.log(
            LogEvent(
                severity=Severity.INFO,
                task_id=config.task_id,
                category="流检测",
                message="正在检测输入流的编码、分辨率和音频",
            )
        )

        try:
            stream_info = self.probe(self.ffprobe, config.source_url)
        except (RuntimeError, ValueError) as error:
            logger.log(
                LogEvent(
                    severity=Severity.ERROR,
                    task_id=config.task_id,
                    category="检测失败",
                    message=f"无法启动收录：{error}",
                )
            )
            logger.log(
                LogEvent(
                    severity=Severity.ERROR,
                    task_id=config.task_id,
                    category="任务状态",
                    message=TaskStatus.FAILED.value,
                )
            )
            return

        logger.log(
            LogEvent(
                severity=Severity.INFO,
                task_id=config.task_id,
                category="视频编码",
                message=stream_info.video_codec,
            )
        )
        logger.log(
            LogEvent(
                severity=Severity.INFO,
                task_id=config.task_id,
                category="流检测",
                message=(
                    f"检测成功：{stream_info.video_codec} / {stream_info.width}×{stream_info.height} "
                    f"/ {stream_info.frame_rate} fps"
                ),
            )
        )

        def on_status(status: TaskStatus) -> None:
            logger.log(
                LogEvent(
                    severity=Severity.ERROR if status is TaskStatus.FAILED else Severity.INFO,
                    task_id=config.task_id,
                    category="任务状态",
                    message=status.value,
                )
            )

        recorder = self.recorder_factory(config, self.ffmpeg, logger, output_dir, on_status)
        self.controller.register(config.task_id, recorder, stream_info)
        recorder.start(stream_info)
