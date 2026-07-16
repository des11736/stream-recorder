# 任务时长、地址记忆与隐藏子进程窗口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让收录时长在录制期间准确累计并保留，记住上一次成功启动的地址，并消除 Windows 上 FFmpeg/FFprobe 弹出的空白 CMD 窗口。

**Architecture:** 新增纯 Python 计时对象，以单调时钟累计“收录中”状态的秒数；主窗口用一秒定时器刷新表格。主窗口通过 `QSettings` 读写最后一个成功发起的地址。新增统一子进程参数函数，供 FFprobe 与两个 FFmpeg 启动点复用 Windows 的无控制台窗口参数。

**Tech Stack:** Python 3.10、PySide6、pytest、subprocess、PyInstaller。

## Global Constraints

- 地址仅在通过协议校验并成功发出启动请求后持久化。
- 时长仅在状态为“收录中”时增长，重连、检测、停止和失败期间不增长。
- Windows 子进程使用 `subprocess.CREATE_NO_WINDOW`；其他系统保持原始参数。
- 保留既有多任务、中文日志、地址脱敏和 H.264/H.265 收录行为。

---

### Task 1: 统一隐藏 Windows 子进程控制台窗口

**Files:**
- Create: `src/stream_recorder/subprocess_options.py`
- Modify: `src/stream_recorder/ffmpeg_tools.py:1-75`
- Modify: `src/stream_recorder/recorder.py:1-190`
- Modify: `tests/test_ffmpeg_tools.py`
- Modify: `tests/test_recorder.py`

**Interfaces:**
- Produces: `hidden_console_kwargs(platform_name: str | None = None) -> dict[str, int]`
- Consumes: `subprocess.CREATE_NO_WINDOW` on Windows.

- [ ] **Step 1: Write failing tests for platform options and all child-process callers.**

```python
from types import SimpleNamespace


def test_hidden_console_kwargs_only_applies_on_windows() -> None:
    assert hidden_console_kwargs("linux") == {}
    assert hidden_console_kwargs("win32") == {"creationflags": subprocess.CREATE_NO_WINDOW}


def test_run_probe_passes_hidden_console_options(monkeypatch) -> None:
    captured = {}
    result = SimpleNamespace(stdout='{"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1, "height": 1, "avg_frame_rate": "1/1"}]}')
    monkeypatch.setattr(ffmpeg_tools, "hidden_console_kwargs", lambda: {"creationflags": 123})
    run_probe(Path("ffprobe.exe"), "http://example.com/live", runner=lambda *args, **kwargs: captured.update(kwargs) or result)
    assert captured["creationflags"] == 123
```

```python
def test_recorder_processes_pass_hidden_console_options(monkeypatch, tmp_path: Path) -> None:
    captured = []
    monkeypatch.setattr(recorder_module, "hidden_console_kwargs", lambda: {"creationflags": 123})

    class FinishedProcess:
        stdout = None
        stderr = None

        def poll(self):
            return 0

    recorder = Recorder(
        TaskConfig("task", "任务", "http://example.com/live", tmp_path),
        Path("ffmpeg.exe"),
        EventLogger(tmp_path / "logs", Queue()),
        tmp_path / "output",
        process_factory=lambda *args, **kwargs: captured.append(kwargs) or FinishedProcess(),
    )
    recorder._run_once(StreamInfo("H.264", 1, 1, "1/1", "aac"))
    recorder._start_anomaly_monitor()
    assert [kwargs["creationflags"] for kwargs in captured] == [123, 123]
```

- [ ] **Step 2: Run the focused tests and confirm failure because the helper and new injection points do not exist.**

Run: `python -m pytest tests/test_ffmpeg_tools.py tests/test_recorder.py -v`

Expected: FAIL with import errors or missing `creationflags` assertions.

- [ ] **Step 3: Add the platform helper and reuse it for FFprobe and both FFmpeg processes.**

```python
# subprocess_options.py
def hidden_console_kwargs(platform_name: str | None = None) -> dict[str, int]:
    if (platform_name or sys.platform) == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
```

Pass `**hidden_console_kwargs()` to `subprocess.run()` in `run_probe()` and to both `self._process_factory(...)` calls in `Recorder`.

- [ ] **Step 4: Run focused tests and confirm they pass.**

Run: `python -m pytest tests/test_ffmpeg_tools.py tests/test_recorder.py -v`

Expected: PASS.

### Task 2: Add a pure, independently testable recording-duration accumulator

**Files:**
- Create: `src/stream_recorder/duration.py`
- Create: `tests/test_duration.py`

**Interfaces:**
- Produces: `RecordingDuration.resume(now: float) -> None`, `pause(now: float) -> None`, `seconds(now: float) -> int`, `format_duration(seconds: int) -> str`.
- Consumes: floating-point monotonic timestamps from the UI.

- [ ] **Step 1: Write failing duration tests.**

```python
def test_duration_counts_only_while_resumed() -> None:
    duration = RecordingDuration()
    duration.resume(10.0)
    assert duration.seconds(15.9) == 5
    duration.pause(16.1)
    assert duration.seconds(100.0) == 6
    duration.resume(120.0)
    assert duration.seconds(122.2) == 8


def test_duration_formats_hours_minutes_and_seconds() -> None:
    assert format_duration(3661) == "01:01:01"
```

- [ ] **Step 2: Run the new tests and confirm failure because the module does not exist.**

Run: `python -m pytest tests/test_duration.py -v`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the smallest accumulator.**

```python
@dataclass
class RecordingDuration:
    _completed_seconds: float = 0.0
    _resumed_at: float | None = None

    def resume(self, now: float) -> None:
        if self._resumed_at is None:
            self._resumed_at = now

    def pause(self, now: float) -> None:
        if self._resumed_at is not None:
            self._completed_seconds += now - self._resumed_at
            self._resumed_at = None
```

Implement `seconds()` with integer floor and `format_duration()` using `divmod`.

- [ ] **Step 4: Run duration tests and confirm they pass.**

Run: `python -m pytest tests/test_duration.py -v`

Expected: PASS.

### Task 3: Persist the last address and bind duration to task statuses in the main window

**Files:**
- Modify: `src/stream_recorder/ui/main_window.py:1-355`
- Modify: `tests/test_ui.py`

**Interfaces:**
- Consumes: `RecordingDuration`, `format_duration`, `QSettings`, `TaskStatus`.
- Produces: optional `settings: QSettings | None` and `clock: Callable[[], float]` constructor parameters for deterministic UI tests.

- [ ] **Step 1: Write failing UI tests for restored address and status-driven duration.**

```python
def test_successful_start_persists_url_for_next_window(tmp_path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    first = MainWindow(TaskController(), Queue(), tmp_path, settings=settings)
    first.url_edit.setText("http://example.com/live")
    first._request_start()
    second = MainWindow(TaskController(), Queue(), tmp_path, settings=settings)
    assert second.url_edit.text() == "http://example.com/live"


def test_duration_pauses_on_reconnect_and_freezes_on_stop(tmp_path) -> None:
    now = [10.0]
    window = MainWindow(TaskController(), Queue(), tmp_path, clock=lambda: now[0])
    config = TaskConfig("task", "任务", "http://example.com/live", tmp_path)
    window.add_task_row(config, "HTTP", "检测中", TaskStatus.PROBING.value, "等待启动")
    window.update_task("task", status=TaskStatus.RECORDING.value)
    now[0] = 15.9
    window._refresh_task_durations()
    assert window.task_table.item(0, 4).text() == "00:00:05"
```

Continue the test through reconnect, resumed recording and stopped state, asserting the frozen final text.

- [ ] **Step 2: Run UI tests and confirm failure because the constructor does not accept settings/clock and no duration refresh exists.**

Run: `$env:QT_QPA_PLATFORM = 'offscreen'; python -m pytest tests/test_ui.py -v`

Expected: FAIL with constructor or method errors.

- [ ] **Step 3: Implement address persistence and independent duration refresh.**

```python
self._settings = settings or QSettings("流收录程序", "流收录程序")
self._clock = clock or monotonic
self._durations: dict[str, RecordingDuration] = {}
self._duration_timer = QTimer(self)
self._duration_timer.timeout.connect(self._refresh_task_durations)
self._duration_timer.start(1000)
```

Initialize the address field from `last_stream_url`; save the normalized address after validation. Create a `RecordingDuration` when adding a task. Resume it when the UI receives `TaskStatus.RECORDING`, pause it for `RECONNECTING`, `STOPPED`, and `FAILED`, then render its formatted value in table column 4.

- [ ] **Step 4: Run UI tests and confirm they pass.**

Run: `$env:QT_QPA_PLATFORM = 'offscreen'; python -m pytest tests/test_ui.py -v`

Expected: PASS.

### Task 4: Document and verify the complete behavior

**Files:**
- Modify: `README.md:5-38`
- Modify: `docs/superpowers/specs/2026-07-16-task-duration-address-and-hidden-console-design.md` only if implementation exposes a necessary specification correction.

**Interfaces:**
- Consumes: final UI, duration and subprocess behavior from Tasks 1-3.
- Produces: user-facing instructions that explain restored address, duration behavior and no-terminal-window behavior.

- [ ] **Step 1: Update the README feature list and usage section.**

Add that the latest successful stream address is restored at next startup, that “已收录” increases only while recording and freezes after the task ends, and that FFmpeg/FFprobe run without CMD windows on Windows.

- [ ] **Step 2: Run the full test suite.**

Run: `$env:FFMPEG_BINARY = (Resolve-Path 'bundled\ffmpeg\ffmpeg.exe').Path; $env:QT_QPA_PLATFORM = 'offscreen'; python -m pytest -v`

Expected: PASS, including all integration tests.

- [ ] **Step 3: Rebuild the one-file Windows application and launch it once.**

Run: `python -m PyInstaller --noconfirm --clean --onefile --windowed --name '流收录程序-时长地址修正版' --paths src --add-binary 'bundled\ffmpeg\ffmpeg.exe;ffmpeg' --add-binary 'bundled\ffmpeg\ffprobe.exe;ffmpeg' --add-data 'bundled\ffmpeg\LICENSE-FFmpeg.txt;ffmpeg' 'src\launcher.py'`

Launch the generated executable, confirm its process remains running, then terminate only that validation process.
