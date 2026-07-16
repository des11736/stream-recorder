import subprocess
from io import StringIO
from pathlib import Path

import stream_recorder.recorder as recorder_module
from stream_recorder.models import OutputFormat, StreamInfo, TaskConfig, TaskStatus
from stream_recorder.recorder import Recorder, is_media_progress_line, recording_target, retry_delays, task_output_directory
from stream_recorder.task_controller import TaskController


class FakeRecorder:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self, _stream_info) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class CapturingLogger:
    def __init__(self) -> None:
        self.raw_lines: list[str] = []
        self.events: list[object] = []

    def raw(self, line: str) -> None:
        self.raw_lines.append(line)

    def log(self, event: object) -> None:
        self.events.append(event)


def test_retry_delays_are_bounded() -> None:
    assert list(retry_delays(5)) == [2, 4, 8, 16, 30]
    assert list(retry_delays(2)) == [2, 4]


def test_recorder_marks_reconnecting_before_nonzero_backoff_wait(tmp_path: Path) -> None:
    statuses: list[TaskStatus] = []
    wait_states: list[tuple[int, TaskStatus | None]] = []

    class StopRequested:
        def wait(self, delay: int) -> bool:
            wait_states.append((delay, statuses[-1] if statuses else None))
            return False

        def is_set(self) -> bool:
            return False

    class FakeLogger:
        def log(self, _event: object) -> None:
            pass

    recorder = Recorder(
        config=TaskConfig(
            "task-1",
            "Camera",
            "http://example.com/live",
            tmp_path,
            enable_anomaly_detection=False,
            max_retries=1,
        ),
        ffmpeg=Path("ffmpeg.exe"),
        logger=FakeLogger(),
        output_dir=tmp_path / "output",
        on_status=statuses.append,
    )
    recorder._stop_requested = StopRequested()
    recorder._run_once = lambda _info: False

    recorder._run(StreamInfo("H.264", 1920, 1080, "25/1", "aac"))

    assert next(status for delay, status in wait_states if delay) is TaskStatus.RECONNECTING
    assert statuses == [
        TaskStatus.RECORDING,
        TaskStatus.RECONNECTING,
        TaskStatus.RECORDING,
        TaskStatus.FAILED,
    ]


def test_progress_lines_with_media_time_refresh_watchdog() -> None:
    assert is_media_progress_line("out_time_us=1200000")
    assert is_media_progress_line("out_time_ms=1200000")
    assert is_media_progress_line("out_time=00:00:01.20")
    assert not is_media_progress_line("progress=continue")


def test_monitor_pts_jump_emits_warning_without_changing_recorder_status(tmp_path: Path) -> None:
    logger = CapturingLogger()
    recorder = Recorder(
        TaskConfig("task-1", "Camera", "http://example.com/live", tmp_path),
        Path("ffmpeg.exe"),
        logger,
        tmp_path / "output",
    )
    stream = StringIO(
        "[info] frame= 2334 fps=1.0 time=00:38:54.00 bitrate=N/A\n"
        "[info] frame= 2364 fps=1.0 time=00:39:24.00 bitrate=N/A\n"
        "[info] frame= 2364 fps=1.0 time=00:39:24.00 bitrate=N/A\n"
    )

    recorder._read_stderr(stream, monitor=True)

    assert len(logger.events) == 1
    assert logger.events[0].category == "PTS 时间戳跳变"
    assert recorder.status is TaskStatus.STOPPED


def test_pts_jump_is_disabled_with_anomaly_detection(tmp_path: Path) -> None:
    logger = CapturingLogger()
    recorder = Recorder(
        TaskConfig(
            "task-1",
            "Camera",
            "http://example.com/live",
            tmp_path,
            enable_anomaly_detection=False,
        ),
        Path("ffmpeg.exe"),
        logger,
        tmp_path / "output",
    )

    recorder._read_stderr(
        StringIO(
            "[info] frame= 2334 fps=1.0 time=00:38:54.00 bitrate=N/A\n"
            "[info] frame= 2364 fps=1.0 time=00:39:24.00 bitrate=N/A\n"
        ),
        monitor=True,
    )

    assert logger.events == []


def test_pts_baseline_is_reset_for_each_recording_attempt(tmp_path: Path) -> None:
    recorder = Recorder(
        TaskConfig("task-1", "Camera", "http://example.com/live", tmp_path),
        Path("ffmpeg.exe"),
        CapturingLogger(),
        tmp_path / "output",
    )
    recorder._last_monitor_media_time = 2334.0

    recorder._reset_attempt_state()

    assert recorder._last_monitor_media_time is None


def test_task_output_directory_is_separate_and_safe(tmp_path: Path) -> None:
    output = task_output_directory(tmp_path, "前门 / 摄像头", "20260715_140621")

    assert output.parent == tmp_path
    assert output.name == "前门_摄像头_20260715_140621"


def test_recording_target_follows_selected_format(tmp_path: Path) -> None:
    hls = TaskConfig("hls", "HLS", "http://example.com/live", tmp_path)
    mp4 = TaskConfig(
        "mp4",
        "MP4",
        "http://example.com/live",
        tmp_path,
        output_format=OutputFormat.MP4,
    )

    assert recording_target(hls, tmp_path / "hls").name == "index.m3u8"
    assert recording_target(mp4, tmp_path / "mp4").name == "recording.mp4"


def test_stopping_one_task_does_not_stop_another() -> None:
    controller = TaskController()
    first, second = FakeRecorder(), FakeRecorder()
    controller.register("first", first, object())
    controller.register("second", second, object())

    controller.start("first")
    controller.start("second")
    controller.stop("first")

    assert first.started == 1 and first.stopped == 1
    assert second.started == 1 and second.stopped == 0


def test_recorder_and_anomaly_monitor_preserve_io_and_share_hidden_console_options(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    hidden_options = {"creationflags": 0x08000000}
    output_dir = tmp_path / "output"
    monkeypatch.setattr(recorder_module, "hidden_console_kwargs", lambda: hidden_options)

    class FakeProcess:
        stdout = None
        stderr = None

        def poll(self) -> int:
            return 0

    class FakeLogger:
        def log(self, _event: object) -> None:
            pass

    def process_factory(command: list[str], **kwargs: object) -> FakeProcess:
        calls.append((command, kwargs))
        return FakeProcess()

    recorder = Recorder(
        config=TaskConfig("task-1", "Camera", "http://example.com/live", tmp_path),
        ffmpeg=Path("ffmpeg.exe"),
        logger=FakeLogger(),
        output_dir=output_dir,
        process_factory=process_factory,
    )

    recorder._run_once(StreamInfo("H.264", 1920, 1080, "25/1", "aac"))

    assert len(calls) == 2
    recorder_command, recorder_kwargs = calls[0]
    monitor_command, monitor_kwargs = calls[1]
    assert recorder_command[recorder_command.index("-progress") + 1] == "pipe:1"
    assert monitor_command[monitor_command.index("-vf") + 1] == "fps=1"
    assert recorder_kwargs == {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "cwd": output_dir,
        **hidden_options,
    }
    assert monitor_kwargs == {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        **hidden_options,
    }
