from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from queue import Empty, Queue
from typing import Callable
from uuid import uuid4

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..duration import RecordingDuration, format_duration
from ..events import LogEvent
from ..models import OutputFormat, TaskConfig, TaskStatus
from ..task_controller import TaskController
from ..urls import normalize_stream_url, validate_segment_seconds, validate_stream_url


LAST_STREAM_URL_KEY = "last_stream_url"


class MainWindow(QMainWindow):
    """Dense operational console focused on one-line task creation and live diagnosis."""

    start_requested = Signal(object)
    stop_requested = Signal(str)

    _LOG_LIMIT = 10_000
    _TABLE_COLUMNS = ("任务", "协议", "编码", "状态", "已收录", "输出目录", "最新事件", "操作", "任务 ID")

    def __init__(
        self,
        controller: TaskController,
        event_queue: Queue[LogEvent] | None = None,
        output_root: Path | None = None,
        *,
        settings: QSettings | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.event_queue = event_queue or Queue()
        self.output_root = output_root or (Path.home() / "Videos" / "流收录")
        self.settings = settings if settings is not None else QSettings("流收录程序", "流收录程序")
        self._clock = clock if clock is not None else time.monotonic
        self._events: deque[LogEvent] = deque(maxlen=self._LOG_LIMIT)
        self._task_rows: dict[str, int] = {}
        self._recording_durations: dict[str, RecordingDuration] = {}

        self.setWindowTitle("流收录程序")
        self.setMinimumSize(1080, 720)
        self.resize(1320, 860)
        self._build_ui()
        last_stream_url = self.settings.value(LAST_STREAM_URL_KEY)
        if isinstance(last_stream_url, str):
            self.url_edit.setText(last_stream_url)
        self._apply_console_theme()

        self._event_timer = QTimer(self)
        self._event_timer.timeout.connect(self._drain_events)
        self._event_timer.start(100)
        self._duration_timer = QTimer(self)
        self._duration_timer.timeout.connect(self._refresh_durations)
        self._duration_timer.start(1_000)

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(14)
        root_layout.addWidget(self._build_header())
        root_layout.addWidget(self._build_capture_panel())
        root_layout.addWidget(self._build_task_panel(), stretch=3)
        root_layout.addWidget(self._build_log_panel(), stretch=2)
        self.setCentralWidget(root)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 12, 18, 12)

        title_box = QVBoxLayout()
        eyebrow = QLabel("STREAM // CAPTURE")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("流收录控制台")
        title.setObjectName("title")
        title_box.addWidget(eyebrow)
        title_box.addWidget(title)
        layout.addLayout(title_box)
        layout.addStretch()

        self.engine_badge = QLabel("FFMPEG · 准备就绪")
        self.engine_badge.setObjectName("engineBadge")
        self.engine_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.engine_badge)
        return header

    def _build_capture_panel(self) -> QWidget:
        panel = QGroupBox("新建收录任务")
        panel.setObjectName("capturePanel")
        grid = QGridLayout(panel)
        self.capture_grid = grid
        grid.setContentsMargins(18, 18, 18, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：前门摄像头")
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("urlEdit")
        self.url_edit.setPlaceholderText("rtsp://、rtmp://、http:// 或 https:// 流地址")
        self.url_edit.returnPressed.connect(self._request_start)

        self.output_edit = QLineEdit(str(self.output_root))
        self.output_edit.setReadOnly(True)
        self.output_button = QPushButton("选择")
        self.output_button.setObjectName("secondaryButton")
        self.output_button.setMaximumWidth(72)
        self.output_button.clicked.connect(self._choose_output_root)

        self.segment_spin = QSpinBox()
        self.segment_spin.setRange(2, 60)
        self.segment_spin.setValue(6)
        self.segment_spin.setSuffix(" 秒")
        self.segment_spin.setToolTip("仅 m3u8 收录使用此切片长度。")
        self.segment_label = QLabel("切片长度")

        self.format_combo = QComboBox()
        self.format_combo.addItem("m3u8（HLS）", OutputFormat.HLS)
        self.format_combo.addItem("MP4", OutputFormat.MP4)
        self.format_combo.currentIndexChanged.connect(self._set_output_format)
        self.format_label = QLabel("收录格式")

        self.anomaly_button = QPushButton("异常检测：开启")
        self.anomaly_button.setObjectName("detectionToggle")
        self.anomaly_button.setCheckable(True)
        self.anomaly_button.setChecked(True)
        self.anomaly_button.setToolTip("开启后检测丢帧/丢包、断流和无有效画面。")
        self.anomaly_button.toggled.connect(self._set_anomaly_detection_label)

        self.start_button = QPushButton("启动收录")
        self.start_button.setObjectName("startButton")
        self.start_button.clicked.connect(self._request_start)

        grid.addWidget(QLabel("任务名称"), 0, 0)
        grid.addWidget(QLabel("流地址"), 0, 1, 1, 3)
        grid.addWidget(self.name_edit, 1, 0)
        grid.addWidget(self.url_edit, 1, 1, 1, 3)
        grid.addWidget(QLabel("输出位置"), 2, 0, 1, 2)
        grid.addWidget(self.segment_label, 2, 2)
        grid.addWidget(self.format_label, 2, 3)
        grid.addWidget(self.output_edit, 3, 0)
        grid.addWidget(self.output_button, 3, 1)
        grid.addWidget(self.segment_spin, 3, 2)
        grid.addWidget(self.format_combo, 3, 3)
        grid.addWidget(self.anomaly_button, 4, 0, 1, 3)
        grid.addWidget(self.start_button, 4, 3)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        return panel

    def _build_task_panel(self) -> QWidget:
        panel = QGroupBox("运行任务")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 12)
        self.task_table = QTableWidget(0, len(self._TABLE_COLUMNS))
        self.task_table.setHorizontalHeaderLabels(self._TABLE_COLUMNS)
        self.task_table.setColumnHidden(8, True)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.setAlternatingRowColors(True)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setShowGrid(False)
        header = self.task_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultSectionSize(112)
        self.task_table.setColumnWidth(0, 150)
        self.task_table.setColumnWidth(5, 200)
        self.task_table.setColumnWidth(6, 260)
        layout.addWidget(self.task_table)
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QGroupBox("实时中文日志")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 12)

        toolbar = QHBoxLayout()
        self.log_filter = QComboBox()
        self.log_filter.addItems(("全部事件", "信息", "警告", "错误"))
        self.log_filter.currentTextChanged.connect(self._render_logs)
        self.follow_check = QCheckBox("自动跟随")
        self.follow_check.setChecked(True)
        clear_button = QPushButton("清空界面")
        clear_button.setObjectName("secondaryButton")
        clear_button.clicked.connect(self._clear_log_view)
        toolbar.addWidget(QLabel("显示"))
        toolbar.addWidget(self.log_filter)
        toolbar.addStretch()
        toolbar.addWidget(self.follow_check)
        toolbar.addWidget(clear_button)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setMaximumBlockCount(self._LOG_LIMIT)
        layout.addLayout(toolbar)
        layout.addWidget(self.log_view)
        return panel

    def _apply_console_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #10181d; color: #e3e9e7; }
            QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #d7e0de; }
            QFrame#header { background: #162329; border: 1px solid #29444a; border-left: 4px solid #e9ad4d; }
            QLabel#eyebrow { color: #7aa9a5; font-family: "Bahnschrift"; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
            QLabel#title { color: #f5f0e6; font-size: 23px; font-weight: 700; }
            QLabel#engineBadge { color: #a6d6c0; background: #1c3a35; border: 1px solid #386e61; border-radius: 10px; padding: 6px 12px; font-family: "Bahnschrift"; font-weight: 600; }
            QGroupBox { background: #142026; border: 1px solid #294149; border-radius: 4px; margin-top: 13px; padding-top: 13px; font-weight: 700; color: #e9ad4d; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background: #0d151a; border: 1px solid #34505a; border-radius: 3px; padding: 7px 9px; color: #edf5f2; selection-background-color: #2f6b68; }
            QLineEdit#urlEdit { border-color: #5b8f8a; font-family: "Cascadia Mono"; font-size: 13px; }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #e9ad4d; }
            QPushButton { background: #263d45; border: 1px solid #42616a; border-radius: 3px; padding: 8px 13px; color: #eff4f2; font-weight: 600; }
            QPushButton:hover { background: #34535c; }
            QPushButton#startButton { background: #e9ad4d; color: #172026; border: 1px solid #ffd181; font-size: 14px; padding: 10px 18px; }
            QPushButton#startButton:hover { background: #f5c264; }
            QPushButton#secondaryButton { background: #1a2a31; }
            QPushButton#detectionToggle { background: #1c3a35; border-color: #386e61; color: #bde4d3; }
            QPushButton#detectionToggle:!checked { background: #2a2520; border-color: #6d5536; color: #d5c4a7; }
            QTableWidget { background: #10191e; alternate-background-color: #16242a; border: 0; color: #dce6e3; gridline-color: #263b43; }
            QHeaderView::section { background: #1c2c33; color: #92bbb5; border: 0; border-bottom: 1px solid #36525a; padding: 8px 6px; font-family: "Bahnschrift"; font-size: 11px; }
            QTableWidget::item:selected { background: #29494d; color: #ffffff; }
            QPlainTextEdit { color: #c8d5d1; font-family: "Cascadia Mono"; font-size: 12px; background: #0b1115; border-color: #263d45; }
            QCheckBox { spacing: 7px; }
            QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #54767a; background: #0d151a; }
            QCheckBox::indicator:checked { background: #e9ad4d; border-color: #ffd181; }
            """
        )

    def _choose_output_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择收录输出目录", self.output_edit.text())
        if path:
            self.output_root = Path(path)
            self.output_edit.setText(path)

    def _set_output_format(self, _index: int) -> None:
        is_hls = OutputFormat(self.format_combo.currentData()) is OutputFormat.HLS
        self.segment_label.setHidden(not is_hls)
        self.segment_spin.setHidden(not is_hls)
        format_column = 3 if is_hls else 2
        self.capture_grid.removeWidget(self.format_label)
        self.capture_grid.removeWidget(self.format_combo)
        self.capture_grid.addWidget(self.format_label, 2, format_column)
        self.capture_grid.addWidget(self.format_combo, 3, format_column)

    def _set_anomaly_detection_label(self, enabled: bool) -> None:
        self.anomaly_button.setText("异常检测：开启" if enabled else "异常检测：关闭")

    def _request_start(self) -> None:
        try:
            source_url = normalize_stream_url(self.url_edit.text())
            protocol = validate_stream_url(source_url)
            segment_seconds = validate_segment_seconds(self.segment_spin.value())
        except ValueError as error:
            self.show_error(str(error))
            return

        name = self.name_edit.text().strip() or f"流任务 {self.task_table.rowCount() + 1}"
        output_format = OutputFormat(self.format_combo.currentData())
        config = TaskConfig(
            task_id=uuid4().hex,
            name=name,
            source_url=source_url,
            output_root=self.output_root,
            segment_seconds=segment_seconds,
            output_format=output_format,
            enable_anomaly_detection=self.anomaly_button.isChecked(),
        )
        self.add_task_row(config, protocol.value.upper(), "检测中", TaskStatus.PROBING.value, "等待启动")
        self.start_requested.emit(config)
        self.settings.setValue(LAST_STREAM_URL_KEY, source_url)
        self.settings.sync()
        self.name_edit.clear()
        self.url_edit.setFocus()

    def add_task_row(
        self,
        config: TaskConfig,
        protocol: str,
        codec: str,
        status: str,
        event: str,
    ) -> None:
        row = self.task_table.rowCount()
        self._task_rows[config.task_id] = row
        self._recording_durations[config.task_id] = RecordingDuration()
        self.task_table.insertRow(row)
        values = (config.name, protocol, codec, status, "00:00:00", str(config.output_root), event, "", config.task_id)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 3:
                item.setForeground(QColor("#e9ad4d") if status != TaskStatus.RECORDING.value else QColor("#9fd9bd"))
            self.task_table.setItem(row, column, item)
        stop_button = QPushButton("停止")
        stop_button.setObjectName("secondaryButton")
        stop_button.clicked.connect(lambda _checked=False, task_id=config.task_id: self.stop_requested.emit(task_id))
        self.task_table.setCellWidget(row, 7, stop_button)

    def update_task(
        self,
        task_id: str,
        *,
        codec: str | None = None,
        status: str | None = None,
        event: str | None = None,
    ) -> None:
        row = self._task_rows.get(task_id)
        if row is None:
            return
        if codec is not None:
            self.task_table.item(row, 2).setText(codec)
        if status is not None:
            self.task_table.item(row, 3).setText(status)
            duration = self._recording_durations[task_id]
            now = self._clock()
            if status == TaskStatus.RECORDING.value:
                duration.resume(now)
            elif status in {
                TaskStatus.PROBING.value,
                TaskStatus.RECONNECTING.value,
                TaskStatus.STOPPED.value,
                TaskStatus.FAILED.value,
            }:
                duration.pause(now)
        if event is not None:
            self.task_table.item(row, 6).setText(event)

    def _refresh_durations(self) -> None:
        now = self._clock()
        for task_id, duration in self._recording_durations.items():
            row = self._task_rows.get(task_id)
            if row is not None:
                self.task_table.item(row, 4).setText(format_duration(duration.seconds(now)))

    def _drain_events(self) -> None:
        changed = False
        while True:
            try:
                event = self.event_queue.get_nowait()
            except Empty:
                break
            self._events.append(event)
            if event.category == "视频编码":
                self.update_task(event.task_id, codec=event.message, event="编码检测完成")
            elif event.category == "任务状态":
                self.update_task(event.task_id, status=event.message, event=event.message)
            else:
                self.update_task(event.task_id, event=event.message)
            changed = True
        if changed:
            self._render_logs()

    def _render_logs(self) -> None:
        selected = self.log_filter.currentText()
        lines = []
        for event in self._events:
            if selected != "全部事件" and event.severity.value != selected:
                continue
            lines.append(
                f"[{event.timestamp:%H:%M:%S}] [{event.severity.value}] "
                f"[{event.task_id}] [{event.category}] {event.message}"
            )
        self.log_view.setPlainText("\n".join(lines))
        if self.follow_check.isChecked():
            scrollbar = self.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _clear_log_view(self) -> None:
        self._events.clear()
        self.log_view.clear()

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "无法启动收录", message)
