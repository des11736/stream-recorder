import os
from datetime import datetime
from queue import Queue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, QSize
from PySide6.QtWidgets import QApplication

from stream_recorder.events import LogEvent
from stream_recorder.models import HlsSegmentType, OutputFormat, Severity, TaskStatus
from stream_recorder.task_controller import TaskController
from stream_recorder.ui.main_window import MainWindow


def test_main_window_prioritizes_address_entry_and_realtime_logs(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    event_queue: Queue[LogEvent] = Queue()
    window = MainWindow(TaskController(), event_queue, tmp_path)

    assert window.windowTitle() == "流收录程序"
    assert "rtsp://" in window.url_edit.placeholderText()
    assert window.start_button.text() == "启动收录"
    assert window.output_edit.text() == str(tmp_path)
    assert window.output_button.text() == "选择"
    assert window.output_button.maximumWidth() <= 72
    assert OutputFormat(window.format_combo.currentData()) is OutputFormat.HLS
    assert window.anomaly_button.isCheckable() and window.anomaly_button.isChecked()
    assert not hasattr(window, "transport_combo")
    assert not hasattr(window, "analysis_check")
    assert window.task_table.columnCount() == 9
    assert window.log_view.isReadOnly()
    assert window.segment_label.text() == "切片长度"
    assert not window.segment_label.isHidden()
    assert not window.segment_spin.isHidden()
    assert window.segment_type_label.text() == "切片格式"
    assert not window.segment_type_label.isHidden()
    assert not window.segment_type_combo.isHidden()
    assert window.capture_top_grid.columnStretch(0) == 3
    assert window.capture_top_grid.columnStretch(1) == 7
    assert _grid_position(window.capture_top_grid, window.name_edit) == (1, 0, 1, 1)
    assert _grid_position(window.capture_top_grid, window.url_edit) == (1, 1, 1, 1)
    assert _grid_position(window.capture_bottom_grid, window.segment_type_label) == (0, 2, 1, 1)
    assert _grid_position(window.capture_bottom_grid, window.segment_type_combo) == (1, 2, 1, 1)
    assert _grid_position(window.capture_bottom_grid, window.format_label) == (0, 3, 1, 1)
    assert _grid_position(window.capture_bottom_grid, window.format_combo) == (1, 3, 1, 1)
    assert _grid_position(window.capture_bottom_grid, window.capture_actions_host) == (1, 4, 1, 1)
    assert window.anomaly_button.minimumSize() == QSize(156, 46)
    assert window.start_button.minimumSize() == QSize(156, 46)
    assert window.anomaly_button.maximumSize() == QSize(156, 46)
    assert window.start_button.maximumSize() == QSize(156, 46)
    assert type(window.format_combo).__name__ == "ChevronComboBox"
    assert type(window.log_filter).__name__ == "ChevronComboBox"
    assert type(window.segment_spin).__name__ == "ChevronSpinBox"
    assert type(window.segment_type_combo).__name__ == "ChevronComboBox"
    style = window.styleSheet()
    assert "QMainWindow { background: #f6f9ff" in style
    assert "QPushButton#startButton { background: #2563eb" in style
    assert "QGroupBox { background: #ffffff" in style
    assert "QComboBox::drop-down { width: 34px;" in style
    assert "QSpinBox::up-button { width: 26px;" in style

    window.format_combo.setCurrentIndex(1)

    assert window.segment_label.isHidden()
    assert window.segment_spin.isHidden()
    assert window.segment_type_label.isHidden()
    assert window.segment_type_combo.isHidden()
    assert _grid_position(window.capture_bottom_grid, window.format_label) == (0, 1, 1, 1)
    assert _grid_position(window.capture_bottom_grid, window.format_combo) == (1, 1, 1, 1)

    window.format_combo.setCurrentIndex(0)

    assert not window.segment_label.isHidden()
    assert not window.segment_spin.isHidden()
    assert not window.segment_type_label.isHidden()
    assert not window.segment_type_combo.isHidden()
    assert _grid_position(window.capture_bottom_grid, window.format_label) == (0, 3, 1, 1)
    assert _grid_position(window.capture_bottom_grid, window.format_combo) == (1, 3, 1, 1)


def _grid_position(grid, widget) -> tuple[int, int, int, int]:
    return grid.getItemPosition(grid.indexOf(widget))


def test_task_request_carries_selected_format_and_anomaly_toggle(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    event_queue: Queue[LogEvent] = Queue()
    window = MainWindow(TaskController(), event_queue, tmp_path, settings=_ini_settings(tmp_path))
    captured = []
    window.start_requested.connect(captured.append)
    window.url_edit.setText("http://example.com/live")
    window.format_combo.setCurrentIndex(1)
    window.anomaly_button.setChecked(False)

    window._request_start()

    assert len(captured) == 1
    assert captured[0].output_format is OutputFormat.MP4
    assert not captured[0].enable_anomaly_detection


def test_task_request_carries_selected_hls_segment_type(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    event_queue: Queue[LogEvent] = Queue()
    window = MainWindow(TaskController(), event_queue, tmp_path, settings=_ini_settings(tmp_path))
    captured = []
    window.start_requested.connect(captured.append)
    window.url_edit.setText("http://example.com/live")
    window.segment_type_combo.setCurrentIndex(1)

    window._request_start()

    assert len(captured) == 1
    assert captured[0].output_format is OutputFormat.HLS
    assert captured[0].hls_segment_type is HlsSegmentType.TS


def test_realtime_event_is_rendered_with_chinese_category(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    event_queue: Queue[LogEvent] = Queue()
    window = MainWindow(TaskController(), event_queue, tmp_path)
    event_queue.put(
        LogEvent(
            datetime(2026, 7, 15, 14, 7, 9),
            Severity.WARNING,
            "cam-1",
            "接收端丢帧/丢包",
            "检测到接收端丢帧或丢包",
        )
    )

    window._drain_events()

    assert "接收端丢帧/丢包" in window.log_view.toPlainText()
    assert "检测到接收端丢帧或丢包" in window.log_view.toPlainText()


def test_successful_task_creation_persists_address_and_restores_it(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = _ini_settings(tmp_path)
    window = MainWindow(TaskController(), Queue(), tmp_path, settings=settings)
    address = "https://example.com/live/playlist.m3u8?token=abc"
    window.url_edit.setText(address)

    window._request_start()

    restored = MainWindow(TaskController(), Queue(), tmp_path, settings=_ini_settings(tmp_path))
    assert restored.url_edit.text() == address


def test_task_request_persists_normalized_address_after_start_signal(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = _ini_settings(tmp_path)
    remembered_address = "rtsp://camera.example.com/previous"
    settings.setValue("last_stream_url", remembered_address)
    settings.sync()
    window = MainWindow(TaskController(), Queue(), tmp_path, settings=settings)
    settings_seen_during_emit = []
    window.start_requested.connect(
        lambda _config: settings_seen_during_emit.append(_ini_settings(tmp_path).value("last_stream_url"))
    )
    window.url_edit.setText("  rmtp://camera.example.com/live  ")

    window._request_start()

    assert settings_seen_during_emit == [remembered_address]
    assert _ini_settings(tmp_path).value("last_stream_url") == "rtmp://camera.example.com/live"


def test_invalid_address_does_not_replace_remembered_address(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = _ini_settings(tmp_path)
    remembered_address = "rtsp://camera.example.com/live"
    settings.setValue("last_stream_url", remembered_address)
    settings.sync()
    window = MainWindow(TaskController(), Queue(), tmp_path, settings=settings)
    errors = []
    window.show_error = errors.append
    window.url_edit.setText("not a stream url")

    window._request_start()

    assert errors
    assert settings.value("last_stream_url") == remembered_address


@pytest.mark.parametrize("terminal_status", [TaskStatus.STOPPED, TaskStatus.FAILED])
def test_recording_duration_accumulates_only_while_recording(tmp_path, terminal_status: TaskStatus) -> None:
    app = QApplication.instance() or QApplication([])
    event_queue: Queue[LogEvent] = Queue()
    clock = [100.0]
    window = MainWindow(
        TaskController(),
        event_queue,
        tmp_path,
        settings=_ini_settings(tmp_path),
        clock=lambda: clock[0],
    )
    task_id = _create_task(window)

    _send_task_status(window, event_queue, task_id, TaskStatus.RECORDING)
    clock[0] += 5
    window._refresh_durations()
    assert _duration_text(window, task_id) == "00:00:05"

    _send_task_status(window, event_queue, task_id, TaskStatus.RECONNECTING)
    clock[0] += 12
    window._refresh_durations()
    assert _duration_text(window, task_id) == "00:00:05"

    _send_task_status(window, event_queue, task_id, TaskStatus.RECORDING)
    clock[0] += 3
    window._refresh_durations()
    assert _duration_text(window, task_id) == "00:00:08"

    _send_task_status(window, event_queue, task_id, terminal_status)
    clock[0] += 20
    window._refresh_durations()
    assert _duration_text(window, task_id) == "00:00:08"


def test_each_task_tracks_its_own_recording_duration(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    event_queue: Queue[LogEvent] = Queue()
    clock = [100.0]
    window = MainWindow(
        TaskController(),
        event_queue,
        tmp_path,
        settings=_ini_settings(tmp_path),
        clock=lambda: clock[0],
    )
    first_task_id = _create_task(window, "http://example.com/first")
    second_task_id = _create_task(window, "http://example.com/second")

    _send_task_status(window, event_queue, first_task_id, TaskStatus.RECORDING)
    clock[0] += 2
    _send_task_status(window, event_queue, second_task_id, TaskStatus.RECORDING)
    clock[0] += 3
    window._refresh_durations()

    assert _duration_text(window, first_task_id) == "00:00:05"
    assert _duration_text(window, second_task_id) == "00:00:03"


def _ini_settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def _create_task(window: MainWindow, address: str = "http://example.com/live") -> str:
    captured = []
    window.start_requested.connect(captured.append)
    window.url_edit.setText(address)
    window._request_start()
    return captured[-1].task_id


def _send_task_status(
    window: MainWindow,
    event_queue: Queue[LogEvent],
    task_id: str,
    status: TaskStatus,
) -> None:
    event_queue.put(LogEvent(task_id=task_id, category="任务状态", message=status.value))
    window._drain_events()


def _duration_text(window: MainWindow, task_id: str) -> str:
    row = window._task_rows[task_id]
    return window.task_table.item(row, 4).text()
