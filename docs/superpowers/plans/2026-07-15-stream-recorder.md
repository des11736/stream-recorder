# 流收录程序 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 交付一个内置 FFmpeg 8.1.2 的 Windows 单文件 EXE，使用户可同时把 RTMP、RTSP、HTTP/HTTPS 的 H.264/H.265 流收录为 HLS m3u8，并实时显示详细中文日志。

**Architecture:** Python/PySide6 管理本机界面、任务状态和日志；每个收录任务独立运行 FFprobe 预检、FFmpeg HLS 收录和可选画面分析进程。

**Tech Stack:** Python 3.10+, PySide6, pytest, PyInstaller, FFmpeg/FFprobe 8.1.2。

## Global Constraints

- Windows 10/11 x64；交付物为 PyInstaller one-file EXE。
- 内置 FFmpeg 和 FFprobe 8.1.2；启动时验证版本。
- 输入仅支持 RTMP/RTMPS、RTSP、HTTP/HTTPS；rmtp:// 自动改为 rtmp://。
- 视频仅支持 h264 与 hevc，且始终使用 -c:v copy。
- HLS 输出为每任务独立的 index.m3u8 和 fMP4 分片，默认分片时长 6 秒。
- 所有可见日志均为 UTF-8 中文，URL 密码、token 与签名必须脱敏。
- 当前目录不是 Git 仓库；不初始化仓库或创建提交。

---

## File Structure

- Create: pyproject.toml — 项目元数据和开发依赖。
- Create: src/stream_recorder/models.py — 枚举和数据类。
- Create: src/stream_recorder/urls.py — 协议处理、校验与 URL 脱敏。
- Create: src/stream_recorder/config_store.py — 用户配置的 JSON 存储。
- Create: src/stream_recorder/ffmpeg_tools.py — FFprobe 和 FFmpeg 参数构建。
- Create: src/stream_recorder/events.py — FFmpeg 输出的中文事件映射。
- Create: src/stream_recorder/event_logger.py — 实时队列及 UTF-8 日志。
- Create: src/stream_recorder/recorder.py — 任务收录、看门狗、重连和画面分析。
- Create: src/stream_recorder/task_controller.py — 多任务管理。
- Create: src/stream_recorder/ui/main_window.py — 界面、任务表和日志视图。
- Create: src/stream_recorder/main.py — 应用启动与关闭。
- Create: tests/test_urls.py, tests/test_ffmpeg_tools.py, tests/test_events.py, tests/test_recorder.py, tests/test_ui.py。
- Create: tests/integration/test_hls_output.py, scripts/fetch_ffmpeg.ps1, scripts/build.ps1, README.md。

## Task 1: 建立模型、地址处理和本地配置

**Files:**

- Create: pyproject.toml
- Create: src/stream_recorder/__init__.py
- Create: src/stream_recorder/models.py
- Create: src/stream_recorder/urls.py
- Create: src/stream_recorder/config_store.py
- Create: tests/test_urls.py

**Interfaces:**

- Produces: Protocol, TaskStatus, Severity, TaskConfig, StreamInfo。
- Produces: normalize_stream_url(url: str) -> str, validate_stream_url(url: str) -> Protocol, mask_stream_url(url: str) -> str。
- Produces: JsonConfigStore.load() -> dict and JsonConfigStore.save(data: dict) -> None。

- [ ] **Step 1: Write the failing test**

~~~python
from stream_recorder.models import Protocol
from stream_recorder.urls import mask_stream_url, normalize_stream_url, validate_stream_url


def test_rmtp_is_normalized_and_credentials_are_masked() -> None:
    url = normalize_stream_url("rmtp://alice:secret@example.com/live?token=abc")
    assert url == "rtmp://alice:secret@example.com/live?token=abc"
    assert validate_stream_url(url) is Protocol.RTMP
    assert mask_stream_url(url) == "rtmp://alice:***@example.com/live?token=***"


def test_rejects_file_and_empty_urls() -> None:
    for url in ("", "file:///C:/video.mp4", "ftp://example.com/live"):
        try:
            validate_stream_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{url} should be rejected")
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest tests/test_urls.py -v  
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

~~~python
# src/stream_recorder/models.py
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class Protocol(str, Enum):
    RTMP = "rtmp"
    RTSP = "rtsp"
    HTTP = "http"


class TaskStatus(str, Enum):
    STOPPED = "已停止"
    PROBING = "正在检测"
    RECORDING = "收录中"
    RECONNECTING = "正在重连"
    FAILED = "失败"


class Severity(str, Enum):
    INFO = "信息"
    WARNING = "警告"
    ERROR = "错误"


@dataclass(frozen=True)
class StreamInfo:
    video_codec: str
    width: int
    height: int
    frame_rate: str
    audio_codec: str | None


@dataclass(frozen=True)
class TaskConfig:
    task_id: str
    name: str
    source_url: str
    output_root: Path
    segment_seconds: int = 6
    rtsp_transport: str = "tcp"
    enable_frame_analysis: bool = True
    max_retries: int = 5

    def to_json(self) -> dict:
        data = asdict(self)
        data["output_root"] = str(self.output_root)
        return data
~~~

~~~python
# src/stream_recorder/urls.py
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .models import Protocol

_SCHEMES = {"rtmp": Protocol.RTMP, "rtmps": Protocol.RTMP, "rtsp": Protocol.RTSP,
            "http": Protocol.HTTP, "https": Protocol.HTTP}


def normalize_stream_url(url: str) -> str:
    value = url.strip()
    if value.lower().startswith("rmtp://"):
        return "rtmp://" + value[7:]
    return value


def validate_stream_url(url: str) -> Protocol:
    parts = urlsplit(normalize_stream_url(url))
    if not parts.hostname or parts.scheme.lower() not in _SCHEMES:
        raise ValueError("只支持有效的 RTMP、RTSP、HTTP 或 HTTPS 流地址")
    return _SCHEMES[parts.scheme.lower()]


def mask_stream_url(url: str) -> str:
    parts = urlsplit(normalize_stream_url(url))
    host = parts.hostname or ""
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    if parts.username:
        netloc = f"{parts.username}:***@{netloc}"
    query = urlencode([(key, "***" if key.lower() in {"token", "signature", "sig", "key"}
                         else value) for key, value in parse_qsl(parts.query, keep_blank_values=True)])
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))
~~~

~~~python
# src/stream_recorder/config_store.py
import json
from pathlib import Path


class JsonConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            return {"tasks": [], "output_root": str(Path.home() / "Videos" / "流收录")}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
~~~

- [ ] **Step 4: Run test to verify it passes**

Run: python -m pytest tests/test_urls.py -v  
Expected: PASS with two tests.

## Task 2: FFprobe 预检和 HLS 命令构建

**Files:**

- Create: src/stream_recorder/ffmpeg_tools.py
- Create: tests/test_ffmpeg_tools.py

**Interfaces:**

- Consumes: TaskConfig, StreamInfo, Protocol。
- Produces: parse_probe_json(payload: dict) -> StreamInfo。
- Produces: build_recorder_command(ffmpeg: Path, config: TaskConfig, info: StreamInfo, output_dir: Path) -> list[str]。
- Produces: build_analyzer_command(ffmpeg: Path, config: TaskConfig) -> list[str]。

- [ ] **Step 1: Write the failing test**

~~~python
from pathlib import Path
from stream_recorder.ffmpeg_tools import build_recorder_command, parse_probe_json
from stream_recorder.models import TaskConfig


def test_builds_h265_fmp4_hls_command(tmp_path: Path) -> None:
    info = parse_probe_json({"streams": [
        {"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080,
         "avg_frame_rate": "25/1"},
        {"codec_type": "audio", "codec_name": "aac"},
    ]})
    config = TaskConfig("one", "摄像头", "rtsp://example.com/live", tmp_path)
    command = build_recorder_command(Path("ffmpeg.exe"), config, info, tmp_path / "out")
    assert info.video_codec == "H.265"
    assert ["-c:v", "copy"] == command[command.index("-c:v"):command.index("-c:v") + 2]
    assert command[command.index("-hls_segment_type") + 1] == "fmp4"
    assert command[-1].endswith("index.m3u8")
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest tests/test_ffmpeg_tools.py -v  
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

~~~python
from pathlib import Path
from .models import Protocol, StreamInfo, TaskConfig
from .urls import validate_stream_url


def parse_probe_json(payload: dict) -> StreamInfo:
    video = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("输入流未检测到视频轨道")
    codec = str(video.get("codec_name", "")).lower()
    if codec == "h264":
        display_codec = "H.264"
    elif codec in {"hevc", "h265"}:
        display_codec = "H.265"
    else:
        raise ValueError(f"不支持的视频编码：{codec or '未知'}，仅支持 H.264 和 H.265")
    audio = next((item for item in payload.get("streams", []) if item.get("codec_type") == "audio"), None)
    return StreamInfo(display_codec, int(video.get("width", 0)), int(video.get("height", 0)),
                      str(video.get("avg_frame_rate", "0/0")), audio.get("codec_name") if audio else None)


def _input_arguments(config: TaskConfig) -> list[str]:
    protocol = validate_stream_url(config.source_url)
    args = ["-rw_timeout", "15000000", "-fflags", "+genpts+discardcorrupt"]
    if protocol is Protocol.RTSP and config.rtsp_transport in {"tcp", "udp"}:
        args += ["-rtsp_transport", config.rtsp_transport]
    return args + ["-i", config.source_url]


def build_recorder_command(ffmpeg: Path, config: TaskConfig, info: StreamInfo, output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_codec = "copy" if info.audio_codec == "aac" else "aac"
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "repeat+level+warning",
            "-stats_period", "1", "-progress", "pipe:1", *_input_arguments(config),
            "-map", "0:v:0", "-map", "0:a?", "-c:v", "copy", "-c:a", audio_codec,
            "-f", "hls", "-hls_time", str(config.segment_seconds), "-hls_list_size", "0",
            "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(output_dir / "segment_%012d.m4s"),
            "-hls_start_number_source", "epoch",
            "-hls_flags", "independent_segments+temp_file+program_date_time+append_list",
            str(output_dir / "index.m3u8")]


def build_analyzer_command(ffmpeg: Path, config: TaskConfig) -> list[str]:
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "repeat+level+info",
            *_input_arguments(config), "-map", "0:v:0", "-an", "-vf",
            "fps=1,blackdetect=d=10:pic_th=0.98:pix_th=0.10,freezedetect=n=-60dB:d=15",
            "-f", "null", "-"]
~~~

- [ ] **Step 4: Run test to verify it passes**

Run: python -m pytest tests/test_ffmpeg_tools.py -v  
Expected: PASS; H.265, copy mode and fMP4 HLS output are asserted.

## Task 3: 中文事件解析、脱敏原始输出与日志队列

**Files:**

- Create: src/stream_recorder/events.py
- Create: src/stream_recorder/event_logger.py
- Create: tests/test_events.py

**Interfaces:**

- Produces: LogEvent(timestamp, severity, task_id, category, message)。
- Produces: parse_ffmpeg_line(task_id: str, line: str) -> LogEvent | None。
- Produces: EventLogger.log(event: LogEvent) -> None 和 EventLogger.raw(line: str) -> None。

- [ ] **Step 1: Write the failing test**

~~~python
from stream_recorder.events import parse_ffmpeg_line
from stream_recorder.models import Severity


def test_packet_drop_and_black_screen_are_chinese_events() -> None:
    drop = parse_ffmpeg_line("cam-1", "[rtsp] RTP: dropping old packet received too late")
    black = parse_ffmpeg_line("cam-1", "black_start:12.0 black_end:23.1 black_duration:11.1")
    assert drop is not None and drop.severity is Severity.WARNING
    assert drop.category == "接收端丢帧/丢包" and "丢帧" in drop.message
    assert black is not None and black.category == "黑屏" and "11.1" in black.message
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest tests/test_events.py -v  
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

~~~python
# src/stream_recorder/events.py
from dataclasses import dataclass
from datetime import datetime
import re
from .models import Severity


@dataclass(frozen=True)
class LogEvent:
    timestamp: datetime
    severity: Severity
    task_id: str
    category: str
    message: str


def parse_ffmpeg_line(task_id: str, line: str) -> LogEvent | None:
    lower = line.lower()
    if any(token in lower for token in ("dropping old packet", "max delay reached", "discarding packet")):
        return LogEvent(datetime.now(), Severity.WARNING, task_id, "接收端丢帧/丢包",
                        "检测到接收端丢帧或丢包；建议检查网络带宽、抖动和源端码率")
    black = re.search(r"black_duration:([0-9.]+)", line)
    if black:
        return LogEvent(datetime.now(), Severity.WARNING, task_id, "黑屏",
                        f"原始视频画面持续黑屏 {black.group(1)} 秒；请检查摄像机和信号源")
    freeze = re.search(r"freeze_duration:([0-9.]+)", line)
    if freeze:
        return LogEvent(datetime.now(), Severity.WARNING, task_id, "画面冻结",
                        f"原始视频画面冻结 {freeze.group(1)} 秒；请检查信号源或网络")
    if any(token in lower for token in ("connection timed out", "connection refused", "broken pipe")):
        return LogEvent(datetime.now(), Severity.ERROR, task_id, "断流",
                        "流连接中断或超时；程序将按策略自动重连")
    return None
~~~

~~~python
# src/stream_recorder/event_logger.py
from pathlib import Path
from queue import Queue
from .events import LogEvent


class EventLogger:
    def __init__(self, log_dir: Path, queue: Queue[LogEvent]) -> None:
        self.queue = queue
        log_dir.mkdir(parents=True, exist_ok=True)
        self.app_path = log_dir / "应用日志.log"
        self.raw_path = log_dir / "ffmpeg-脱敏原始输出.log"

    def log(self, event: LogEvent) -> None:
        line = f"[{event.timestamp:%Y-%m-%d %H:%M:%S.%f}] [{event.severity.value}] [{event.task_id}] [{event.category}] {event.message}\\n"
        with self.app_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        self.queue.put(event)

    def raw(self, line: str) -> None:
        with self.raw_path.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\\n")
~~~

- [ ] **Step 4: Run test to verify it passes**

Run: python -m pytest tests/test_events.py -v  
Expected: PASS; packet drops, black screens, freezes and connectivity failures are Chinese events.

## Task 4: 独立收录进程、看门狗和多任务控制

**Files:**

- Create: src/stream_recorder/recorder.py
- Create: src/stream_recorder/task_controller.py
- Create: tests/test_recorder.py

**Interfaces:**

- Produces: retry_delays(max_retries: int) -> Iterator[int]。
- Produces: Recorder.start(info: StreamInfo) -> None, Recorder.stop() -> None, Recorder.status。
- Produces: TaskController.start(task_id: str) -> None, TaskController.stop(task_id: str) -> None, TaskController.stop_all() -> None。

- [ ] **Step 1: Write the failing test**

~~~python
from stream_recorder.recorder import retry_delays


def test_retry_delays_are_bounded() -> None:
    assert list(retry_delays(5)) == [2, 4, 8, 16, 30]
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest tests/test_recorder.py -v  
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

~~~python
# src/stream_recorder/recorder.py
from collections.abc import Iterator
from subprocess import PIPE, Popen
from threading import Event, Thread
from time import monotonic, sleep
from .models import TaskStatus


def retry_delays(max_retries: int) -> Iterator[int]:
    yield from (2, 4, 8, 16, 30)[:max_retries]


class Recorder:
    def __init__(self, command_builder, analyzer_builder, config, logger) -> None:
        self.command_builder = command_builder
        self.analyzer_builder = analyzer_builder
        self.config = config
        self.logger = logger
        self.status = TaskStatus.STOPPED
        self.stop_requested = Event()
        self.process = None
        self.analyzer = None
        self.last_progress = monotonic()

    def start(self, stream_info) -> None:
        self.stop_requested.clear()
        Thread(target=self._run, args=(stream_info,), daemon=True).start()

    def _run(self, stream_info) -> None:
        for attempt, delay in enumerate((0, *retry_delays(self.config.max_retries))):
            if delay:
                self.status = TaskStatus.RECONNECTING
                self.logger.reconnect(attempt, self.config.max_retries)
                sleep(delay)
            if self.stop_requested.is_set():
                self.status = TaskStatus.STOPPED
                return
            self.status = TaskStatus.RECORDING
            self.last_progress = monotonic()
            self.process = Popen(self.command_builder(stream_info), stdout=PIPE, stderr=PIPE,
                                 text=True, encoding="utf-8", errors="replace")
            if self.config.enable_frame_analysis:
                self.analyzer = Popen(self.analyzer_builder(), stdout=PIPE, stderr=PIPE,
                                      text=True, encoding="utf-8", errors="replace")
            Thread(target=self._watch_progress, daemon=True).start()
            self.process.wait()
            self._stop_children()
            if self.stop_requested.is_set():
                self.status = TaskStatus.STOPPED
                return
        self.status = TaskStatus.FAILED
        self.logger.failure("自动重连次数已用尽；请检查地址、网络和源端状态")

    def _watch_progress(self) -> None:
        while self.process and self.process.poll() is None and not self.stop_requested.is_set():
            if monotonic() - self.last_progress > 15:
                self.logger.disconnect("15 秒未接收到有效媒体数据；正在重连")
                self.process.terminate()
                return
            sleep(0.25)

    def _stop_children(self) -> None:
        for process in (self.process, self.analyzer):
            if process and process.poll() is None:
                process.terminate()

    def stop(self) -> None:
        self.stop_requested.set()
        self._stop_children()
~~~

~~~python
# src/stream_recorder/task_controller.py
class TaskController:
    def __init__(self) -> None:
        self.recorders = {}
        self.stream_info = {}

    def register(self, task_id, recorder, stream_info) -> None:
        self.recorders[task_id] = recorder
        self.stream_info[task_id] = stream_info

    def start(self, task_id: str) -> None:
        self.recorders[task_id].start(self.stream_info[task_id])

    def stop(self, task_id: str) -> None:
        self.recorders[task_id].stop()

    def stop_all(self) -> None:
        for recorder in tuple(self.recorders.values()):
            recorder.stop()
~~~

- [ ] **Step 4: Run test to verify it passes**

Run: python -m pytest tests/test_recorder.py -v  
Expected: PASS; delays are exactly 2, 4, 8, 16, 30 seconds.

## Task 5: PySide6 界面、任务表和实时日志面板

**Files:**

- Create: src/stream_recorder/ui/__init__.py
- Create: src/stream_recorder/ui/main_window.py
- Create: src/stream_recorder/main.py
- Create: tests/test_ui.py

**Interfaces:**

- Consumes: TaskController and Queue[LogEvent]。
- Produces: MainWindow(controller, event_queue) and main() -> int。

- [ ] **Step 1: Write the failing test**

~~~python
from PySide6.QtWidgets import QApplication
from stream_recorder.task_controller import TaskController
from stream_recorder.ui.main_window import MainWindow


def test_main_window_has_realtime_log_panel() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(TaskController())
    assert window.log_view.isReadOnly()
    assert window.task_table.columnCount() == 8
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: python -m pytest tests/test_ui.py -v  
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write minimal implementation**

~~~python
# src/stream_recorder/ui/main_window.py
from queue import Empty, Queue
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QTableWidget, QTextEdit, QVBoxLayout, QWidget


class MainWindow(QMainWindow):
    def __init__(self, controller, event_queue=None) -> None:
        super().__init__()
        self.controller = controller
        self.event_queue = event_queue or Queue()
        self.setWindowTitle("流收录程序")
        self.task_table = QTableWidget(0, 8)
        self.task_table.setHorizontalHeaderLabels(["名称", "协议", "编码", "状态", "时长", "输出目录", "最新事件", "操作"])
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout = QVBoxLayout()
        layout.addWidget(self.task_table)
        layout.addWidget(self.log_view)
        body = QWidget()
        body.setLayout(layout)
        self.setCentralWidget(body)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain_events)
        self.timer.start(100)

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except Empty:
                return
            self.log_view.append(f"[{event.timestamp:%H:%M:%S}] [{event.severity.value}] [{event.category}] {event.message}")
~~~

~~~python
# src/stream_recorder/main.py
import sys
from PySide6.QtWidgets import QApplication
from .task_controller import TaskController
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow(TaskController())
    window.resize(1180, 760)
    window.show()
    return app.exec()
~~~

- [ ] **Step 4: Run test to verify it passes**

Run: python -m pytest tests/test_ui.py -v  
Expected: PASS; task table and read-only real-time log pane are available.

## Task 6: HLS 端到端测试、FFmpeg 获取和 EXE 打包

**Files:**

- Create: tests/integration/test_hls_output.py
- Create: scripts/fetch_ffmpeg.ps1
- Create: scripts/build.ps1
- Create: README.md

**Interfaces:**

- Consumes: FFMPEG_BINARY 环境变量；未设置时使用 bundled/ffmpeg/ffmpeg.exe。
- Produces: dist/流收录程序.exe。

- [ ] **Step 1: Write the failing integration test**

~~~python
import os
import subprocess
from pathlib import Path
import pytest


@pytest.mark.integration
def test_h264_input_produces_m3u8_and_segments(tmp_path: Path) -> None:
    ffmpeg = os.environ.get("FFMPEG_BINARY")
    if not ffmpeg:
        pytest.skip("未指定用于集成测试的 FFmpeg")
    input_file = tmp_path / "input.mp4"
    output_dir = tmp_path / "hls"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                    "-t", "2", "-c:v", "libx264", str(input_file)], check=True)
    subprocess.run([ffmpeg, "-y", "-i", str(input_file), "-c:v", "copy", "-f", "hls",
                    "-hls_segment_type", "fmp4", "-hls_time", "1", "-hls_list_size", "0",
                    "-hls_segment_filename", str(output_dir / "segment_%03d.m4s"),
                    str(output_dir / "index.m3u8")], check=True)
    assert (output_dir / "index.m3u8").read_text(encoding="utf-8").startswith("#EXTM3U")
    assert list(output_dir.glob("*.m4s"))
~~~

- [ ] **Step 2: Run the integration test before configuration**

Run: python -m pytest tests/integration/test_hls_output.py -v  
Expected: SKIPPED with the reason that FFMPEG_BINARY is not configured.

- [ ] **Step 3: Add fixed-version download and build scripts**

~~~powershell
# scripts/fetch_ffmpeg.ps1
param([string]$Version = "8.1.2", [string]$Destination = "bundled\ffmpeg")
$ErrorActionPreference = "Stop"
$archive = Join-Path $env:TEMP "ffmpeg-release-full.7z"
Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z" -OutFile $archive
if (-not (Get-Command 7z -ErrorAction SilentlyContinue)) { throw "需要 7-Zip 命令行工具解压 FFmpeg" }
& 7z x $archive "-o$env:TEMP\ffmpeg-extract" -y | Out-Null
$binary = Get-ChildItem "$env:TEMP\ffmpeg-extract" -Recurse -Filter ffmpeg.exe | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Copy-Item $binary.FullName (Join-Path $Destination "ffmpeg.exe") -Force
Copy-Item (Join-Path $binary.Directory.FullName "ffprobe.exe") (Join-Path $Destination "ffprobe.exe") -Force
$actual = & (Join-Path $Destination "ffmpeg.exe") -version | Select-Object -First 1
if ($actual -notmatch "ffmpeg version $Version") { throw "FFmpeg 版本不匹配：$actual" }
~~~

~~~powershell
# scripts/build.ps1
$ErrorActionPreference = "Stop"
python -m pip install -e ".[dev]"
if (-not (Test-Path "bundled\ffmpeg\ffmpeg.exe")) { .\scripts\fetch_ffmpeg.ps1 }
python -m PyInstaller --noconfirm --onefile --windowed --name "流收录程序" --add-binary "bundled\ffmpeg\ffmpeg.exe;ffmpeg" --add-binary "bundled\ffmpeg\ffprobe.exe;ffmpeg" --collect-all PySide6 src\stream_recorder\main.py
~~~

- [ ] **Step 4: Run verification and package the EXE**

Run: set FFMPEG_BINARY to the downloaded 8.1.2 ffmpeg.exe; then run python -m pytest -v and scripts/build.ps1.  
Expected: all unit tests PASS, integration HLS test PASS, and dist/流收录程序.exe exists as one file.

## Plan Self-Review

- Spec coverage: Task 1 covers protocol entry and configuration; Task 2 covers H.264/H.265 validation and m3u8 output; Task 3 covers Chinese diagnostic logging; Task 4 covers independent multi-task recording and reconnecting; Task 5 covers real-time UI logs; Task 6 covers HLS verification, FFmpeg 8.1.2 and one-file EXE packaging.
- Placeholder scan: No unresolved placeholders remain.
- Type consistency: TaskConfig and StreamInfo feed Task 2; LogEvent feeds Tasks 3 and 5; Recorder is owned by TaskController in Task 4.
