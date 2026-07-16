from datetime import datetime
from queue import Queue

from stream_recorder.event_logger import EventLogger
from stream_recorder.events import LogEvent, parse_ffmpeg_line
from stream_recorder.models import Severity


def test_packet_drop_becomes_chinese_warning() -> None:
    event = parse_ffmpeg_line("cam-1", "[rtsp] RTP: dropping old packet received too late")

    assert event is not None
    assert event.severity is Severity.WARNING
    assert event.category == "接收端丢帧/丢包"
    assert "丢帧" in event.message


def test_black_and_freeze_lines_are_ignored_but_disconnect_is_reported() -> None:
    black = parse_ffmpeg_line("cam-1", "black_start:12.0 black_end:23.1 black_duration:11.1")
    freeze = parse_ffmpeg_line("cam-1", "freeze_start:30.0 freeze_end:46.2 freeze_duration:16.2")
    disconnect = parse_ffmpeg_line("cam-1", "Connection timed out")

    assert black is None
    assert freeze is None
    assert disconnect is not None and disconnect.severity is Severity.ERROR


def test_event_logger_writes_utf8_event_and_publishes_it(tmp_path) -> None:
    queue: Queue[LogEvent] = Queue()
    logger = EventLogger(tmp_path, queue)
    event = LogEvent(datetime(2026, 7, 15, 14, 7, 9), Severity.ERROR, "cam-1", "断流", "流信号中断")

    logger.log(event)
    logger.raw("rtsp://alice:secret@example.com/live?token=secret")

    assert queue.get_nowait() == event
    application_log = next(tmp_path.glob("应用日志-*.log"))
    raw_log = (tmp_path / "ffmpeg-脱敏原始输出.log").read_text(encoding="utf-8")
    assert "流信号中断" in application_log.read_text(encoding="utf-8")
    assert "secret" not in raw_log
    assert "alice:***" in raw_log and "token=***" in raw_log
