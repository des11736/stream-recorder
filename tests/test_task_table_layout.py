from __future__ import annotations

import os
from pathlib import Path
from queue import Queue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QHeaderView, QPushButton

from stream_recorder.models import OutputFormat, TaskConfig, TaskStatus
from stream_recorder.task_controller import TaskController
from stream_recorder.ui.main_window import MainWindow


def _window(tmp_path: Path) -> MainWindow:
    QApplication.instance() or QApplication([])
    return MainWindow(TaskController(), Queue(), tmp_path)


def test_task_table_keeps_operation_column_fixed_and_event_column_stretched(tmp_path) -> None:
    window = _window(tmp_path)
    header = window.task_table.horizontalHeader()

    assert not header.stretchLastSection()
    assert header.sectionResizeMode(6) is QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(7) is QHeaderView.ResizeMode.Fixed
    assert window.task_table.columnWidth(7) == 120


def test_task_row_uses_compact_transparent_stop_button_container(tmp_path) -> None:
    window = _window(tmp_path)
    task_id = "task-1"
    config = TaskConfig(
        task_id=task_id,
        name="任务 1",
        source_url="rtmp://example.com/live",
        output_root=tmp_path,
        segment_seconds=6,
        output_format=OutputFormat.HLS,
        enable_anomaly_detection=True,
    )
    window.add_task_row(config, "RTMP", "H.264", TaskStatus.RECORDING.value, "正在收录")
    action_host = window.task_table.cellWidget(0, 7)
    action_layout = action_host.layout()
    stop_button = action_host.findChild(QPushButton, "stopTaskButton")
    requested = []
    window.stop_requested.connect(requested.append)

    assert action_host.styleSheet() == "background: transparent;"
    assert not action_host.autoFillBackground()
    assert action_layout.contentsMargins().left() == 0
    assert action_layout.contentsMargins().top() == 0
    assert action_layout.contentsMargins().right() == 0
    assert action_layout.contentsMargins().bottom() == 0
    assert action_layout.alignment() & Qt.AlignmentFlag.AlignCenter
    assert stop_button.minimumSize() == QSize(96, 30)
    assert stop_button.maximumSize() == QSize(96, 30)

    stop_button.click()

    assert requested == [task_id]
