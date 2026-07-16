from pathlib import Path
from queue import Queue

from stream_recorder.models import StreamInfo, TaskConfig, TaskStatus
from stream_recorder.service import RecordingService


class FakeRecorder:
    def __init__(self, _config, _ffmpeg, _logger, output_dir, on_status) -> None:
        self.output_dir = output_dir
        self.on_status = on_status
        self.started_with = None
        self.stopped = False

    def start(self, stream_info) -> None:
        self.started_with = stream_info
        self.on_status(TaskStatus.RECORDING)

    def stop(self) -> None:
        self.stopped = True


def test_service_probes_then_starts_an_independent_recorder(tmp_path: Path) -> None:
    created: list[FakeRecorder] = []
    stream_info = StreamInfo("H.265", 1920, 1080, "25/1", "aac")

    def recorder_factory(*args):
        recorder = FakeRecorder(*args)
        created.append(recorder)
        return recorder

    service = RecordingService(
        Queue(),
        Path("ffmpeg.exe"),
        Path("ffprobe.exe"),
        probe=lambda _binary, _url: stream_info,
        recorder_factory=recorder_factory,
    )
    config = TaskConfig("camera-a", "前门摄像头", "rtsp://example.com/live", tmp_path)

    worker = service.start(config)
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert len(created) == 1
    assert created[0].started_with == stream_info
    assert created[0].output_dir.parent == tmp_path
    assert service.controller.recorders["camera-a"] is created[0]


def test_service_reports_probe_failure_as_chinese_event(tmp_path: Path) -> None:
    queue = Queue()
    service = RecordingService(
        queue,
        Path("ffmpeg.exe"),
        Path("ffprobe.exe"),
        probe=lambda _binary, _url: (_ for _ in ()).throw(RuntimeError("连接超时")),
    )
    config = TaskConfig("camera-b", "后门摄像头", "rtmp://example.com/live", tmp_path)

    worker = service.start(config)
    worker.join(timeout=1)

    events = list(queue.queue)
    assert any(event.category == "检测失败" and "连接超时" in event.message for event in events)
