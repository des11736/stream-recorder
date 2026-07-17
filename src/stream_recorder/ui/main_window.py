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
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .controls import ChevronComboBox, ChevronSpinBox
from ..duration import RecordingDuration, format_duration
from ..events import LogEvent
from ..models import HlsSegmentType, OutputFormat, TaskConfig, TaskStatus
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
        layout.setContentsMargins(28, 16, 28, 16)

        brand_mark = QLabel("▶")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(70, 70)
        layout.addWidget(brand_mark)
        layout.addSpacing(14)

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
        panel = QGroupBox("✚  新建收录任务")
        panel.setObjectName("capturePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

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

        self.segment_spin = ChevronSpinBox()
        self.segment_spin.setRange(2, 60)
        self.segment_spin.setValue(6)
        self.segment_spin.setSuffix(" 秒")
        self.segment_spin.setToolTip("仅 m3u8 收录使用此切片长度。")
        self.segment_label = QLabel("切片长度")

        self.format_combo = ChevronComboBox()
        self.format_combo.addItem("m3u8（HLS）", OutputFormat.HLS)
        self.format_combo.addItem("MP4", OutputFormat.MP4)
        self.format_combo.currentIndexChanged.connect(self._set_output_format)
        self.format_label = QLabel("收录格式")

        self.segment_type_combo = ChevronComboBox()
        self.segment_type_combo.addItem("m4s（fMP4）", HlsSegmentType.FMP4)
        self.segment_type_combo.addItem("ts（MPEG-TS）", HlsSegmentType.TS)
        self.segment_type_combo.setToolTip("仅 m3u8 收录使用此切片格式。")
        self.segment_type_label = QLabel("切片格式")

        self.anomaly_button = QPushButton("异常检测：开启")
        self.anomaly_button.setObjectName("detectionToggle")
        self.anomaly_button.setCheckable(True)
        self.anomaly_button.setChecked(True)
        self.anomaly_button.setToolTip("开启后检测丢帧/丢包、断流和无有效画面。")
        self.anomaly_button.toggled.connect(self._set_anomaly_detection_label)

        self.start_button = QPushButton("启动收录")
        self.start_button.setObjectName("startButton")
        self.start_button.clicked.connect(self._request_start)

        self.capture_top_grid = QGridLayout()
        self.capture_top_grid.setHorizontalSpacing(18)
        self.capture_top_grid.setVerticalSpacing(8)
        self.capture_top_grid.setColumnStretch(0, 3)
        self.capture_top_grid.setColumnStretch(1, 7)
        self.capture_top_grid.addWidget(QLabel("任务名称"), 0, 0)
        self.capture_top_grid.addWidget(QLabel("流地址"), 0, 1)
        self.capture_top_grid.addWidget(self.name_edit, 1, 0)
        self.capture_top_grid.addWidget(self.url_edit, 1, 1)

        output_host = QWidget()
        output_layout = QHBoxLayout(output_host)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(10)
        output_layout.addWidget(self.output_edit, stretch=1)
        output_layout.addWidget(self.output_button)

        self.capture_actions_host = QWidget()
        actions = QHBoxLayout(self.capture_actions_host)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        self.anomaly_button.setFixedSize(156, 46)
        self.start_button.setFixedSize(156, 46)
        actions.addWidget(self.anomaly_button)
        actions.addWidget(self.start_button)

        self.capture_bottom_grid = QGridLayout()
        self.capture_bottom_grid.setHorizontalSpacing(18)
        self.capture_bottom_grid.setVerticalSpacing(8)
        self.capture_bottom_grid.setColumnStretch(0, 4)
        self.capture_bottom_grid.setColumnStretch(1, 2)
        self.capture_bottom_grid.setColumnStretch(2, 2)
        self.capture_bottom_grid.setColumnStretch(3, 2)
        self.capture_bottom_grid.addWidget(QLabel("输出位置"), 0, 0)
        self.capture_bottom_grid.addWidget(self.segment_label, 0, 1)
        self.capture_bottom_grid.addWidget(self.segment_type_label, 0, 2)
        self.capture_bottom_grid.addWidget(self.format_label, 0, 3)
        self.capture_bottom_grid.addWidget(output_host, 1, 0)
        self.capture_bottom_grid.addWidget(self.segment_spin, 1, 1)
        self.capture_bottom_grid.addWidget(self.segment_type_combo, 1, 2)
        self.capture_bottom_grid.addWidget(self.format_combo, 1, 3)
        self.capture_bottom_grid.addWidget(self.capture_actions_host, 1, 4)

        layout.addLayout(self.capture_top_grid)
        layout.addLayout(self.capture_bottom_grid)
        return panel

    def _build_task_panel(self) -> QWidget:
        panel = QGroupBox("✚  运行任务")
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
        header.setStretchLastSection(False)
        header.setDefaultSectionSize(112)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(0, 150)
        self.task_table.setColumnWidth(5, 200)
        self.task_table.setColumnWidth(7, 120)
        layout.addWidget(self.task_table)
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QGroupBox("▣  实时中文日志")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 12)

        toolbar = QHBoxLayout()
        self.log_filter = ChevronComboBox()
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
            QMainWindow { background: #f6f9ff; color: #17223b; }
            QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #17223b; }
            QFrame#header { background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 #ffffff, stop: 1 #f3f7ff); border: 1px solid #dce7f7; border-radius: 14px; }
            QLabel#brandMark { background: qradialgradient(cx: 0.35, cy: 0.3, radius: 1, stop: 0 #eff6ff, stop: 0.55 #bcd6ff, stop: 1 #2563eb); border: 7px solid #dce9ff; border-radius: 35px; color: #ffffff; font-size: 25px; font-weight: 700; }
            QLabel#eyebrow { color: #3567f0; font-family: "Bahnschrift"; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
            QLabel#title { color: #12203d; font-size: 27px; font-weight: 700; }
            QLabel#engineBadge { color: #138a48; background: #f4fbf7; border: 1px solid #cfe8da; border-radius: 12px; padding: 9px 15px; font-family: "Bahnschrift"; font-weight: 700; }
            QGroupBox { background: #ffffff; border: 1px solid #dce7f7; border-radius: 14px; margin-top: 16px; padding-top: 17px; font-size: 16px; font-weight: 700; color: #17223b; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; color: #17223b; }
            QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background: #ffffff; border: 1px solid #d7e3f4; border-radius: 8px; padding: 10px 12px; color: #17223b; selection-background-color: #cfe0ff; }
            QComboBox { padding-right: 42px; }
            QComboBox::drop-down { width: 34px; border: none; border-left: 1px solid #e1eaf7; border-top-right-radius: 7px; border-bottom-right-radius: 7px; background: #f7faff; }
            QComboBox::drop-down:hover { background: #eaf2ff; }
            QComboBox::down-arrow { image: none; width: 9px; height: 7px; }
            QSpinBox { padding-right: 38px; }
            QSpinBox::up-button { width: 26px; border: none; border-left: 1px solid #e1eaf7; border-top-right-radius: 7px; background: #f7faff; }
            QSpinBox::down-button { width: 26px; border: none; border-top: 1px solid #e1eaf7; border-left: 1px solid #e1eaf7; border-bottom-right-radius: 7px; background: #f7faff; }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #eaf2ff; }
            QSpinBox::up-arrow, QSpinBox::down-arrow { image: none; width: 8px; height: 6px; }
            QLineEdit#urlEdit { border-color: #b9cff5; font-family: "Cascadia Mono"; font-size: 13px; }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #2563eb; }
            QPushButton { background: #ffffff; border: 1px solid #bcd0f2; border-radius: 8px; padding: 8px 13px; color: #1d3f7b; font-weight: 700; }
            QPushButton:hover { background: #eff5ff; border-color: #7da5ea; }
            QPushButton#startButton { background: #2563eb; color: #ffffff; border: 1px solid #2563eb; font-size: 14px; padding: 10px 18px; }
            QPushButton#startButton:hover { background: #1d4ed8; border-color: #1d4ed8; }
            QPushButton#secondaryButton, QPushButton#stopTaskButton { background: #ffffff; color: #365a94; border-color: #c8d8ef; }
            QPushButton#detectionToggle { background: #effcf4; border-color: #a9dfbd; color: #168447; }
            QPushButton#detectionToggle:hover { background: #dcf7e6; border-color: #72cb91; }
            QPushButton#detectionToggle:!checked { background: #fff7ed; border-color: #fdc98c; color: #ba6421; }
            QTableWidget { background: #ffffff; alternate-background-color: #f8fbff; border: 1px solid #dce7f7; border-radius: 8px; color: #1d2a43; gridline-color: #e2ebf7; }
            QHeaderView::section { background: #f4f8ff; color: #38517d; border: 0; border-bottom: 1px solid #dce7f7; padding: 10px 7px; font-family: "Microsoft YaHei UI"; font-size: 12px; font-weight: 700; }
            QTableWidget::item { padding: 0 7px; }
            QTableWidget::item:selected { background: #dbeafe; color: #17223b; }
            QPlainTextEdit { color: #263750; font-family: "Cascadia Mono"; font-size: 12px; background: #ffffff; border-color: #dce7f7; }
            QCheckBox { spacing: 7px; color: #36517d; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #aabdd8; border-radius: 4px; background: #ffffff; }
            QCheckBox::indicator:checked { background: #2563eb; border-color: #2563eb; }
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
        self.segment_type_label.setHidden(not is_hls)
        self.segment_type_combo.setHidden(not is_hls)
        format_column = 3 if is_hls else 1
        self.capture_bottom_grid.removeWidget(self.format_label)
        self.capture_bottom_grid.removeWidget(self.format_combo)
        self.capture_bottom_grid.addWidget(self.format_label, 0, format_column)
        self.capture_bottom_grid.addWidget(self.format_combo, 1, format_column)

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
        hls_segment_type = HlsSegmentType(self.segment_type_combo.currentData())
        config = TaskConfig(
            task_id=uuid4().hex,
            name=name,
            source_url=source_url,
            output_root=self.output_root,
            segment_seconds=segment_seconds,
            output_format=output_format,
            hls_segment_type=hls_segment_type,
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
        action_host = QWidget()
        action_host.setStyleSheet("background: transparent;")
        action_host.setAutoFillBackground(False)
        action_layout = QHBoxLayout(action_host)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stop_button = QPushButton("停止")
        stop_button.setObjectName("stopTaskButton")
        stop_button.setFixedSize(96, 30)
        stop_button.clicked.connect(lambda _checked=False, task_id=config.task_id: self.stop_requested.emit(task_id))
        action_layout.addWidget(stop_button)
        self.task_table.setCellWidget(row, 7, action_host)

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
