# 流收录程序异常检测与输出格式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 简化收录界面，支持 m3u8 或 MP4 输出，并将黑屏/冻结分析替换为一个通用异常检测开关。

**Architecture:** `TaskConfig` 明确携带输出格式和异常检测开关；FFmpeg 命令构建器按格式生成 HLS 或 fragmented MP4。收录器只在异常检测开启时启动低帧率无画面监视器，且不再使用黑屏/冻结滤镜。PySide6 界面只暴露格式、切片长度、异常检测和保存位置。

**Tech Stack:** Python 3.10、PySide6、pytest、FFmpeg 8.1.2、PyInstaller。

## Global Constraints

- RTSP 在内部固定使用 TCP，不向用户展示传输方式选择。
- 仅支持 H.264/H.265 视频，视频始终使用 `-c:v copy`。
- HLS 默认输出为 fMP4 `index.m3u8` 与分片；切片长度范围为 2 至 60 秒。
- MP4 输出文件固定为任务目录内的 `recording.mp4`，并使用 fragmented MP4 标志。
- 不再检测或记录黑屏、画面冻结。
- “异常检测”默认开启；关闭后不启动无画面监视器，也不显示丢帧/断流等详细异常事件，但自动重连和任务状态仍有效。
- 当前目录不是 Git 仓库；不执行提交。

---

## File Structure

- Modify: `src/stream_recorder/models.py` — 定义 `OutputFormat`，简化 `TaskConfig`。
- Modify: `src/stream_recorder/ffmpeg_tools.py` — 固定 RTSP/TCP，构建 HLS、MP4 与无画面监视命令。
- Modify: `src/stream_recorder/events.py` — 删除黑屏/冻结事件映射。
- Modify: `src/stream_recorder/recorder.py` — 使用异常检测开关和按格式输出的目标文件。
- Modify: `src/stream_recorder/ui/main_window.py` — 简化控件，增加格式下拉框和异常检测按钮。
- Modify: `tests/test_ffmpeg_tools.py`、`tests/test_events.py`、`tests/test_recorder.py`、`tests/test_ui.py`、`tests/integration/test_hls_output.py` — 覆盖新行为。
- Modify: `README.md` — 更新功能与使用说明。

## Task 1: 输出格式模型与 FFmpeg 命令

**Files:**
- Modify: `src/stream_recorder/models.py`
- Modify: `src/stream_recorder/ffmpeg_tools.py`
- Modify: `tests/test_ffmpeg_tools.py`

**Interfaces:**
- Produces: `OutputFormat.HLS = "hls"` 和 `OutputFormat.MP4 = "mp4"`。
- Changes: `TaskConfig(..., output_format: OutputFormat = OutputFormat.HLS, enable_anomaly_detection: bool = True)`。
- Produces: `build_anomaly_monitor_command(ffmpeg: Path, config: TaskConfig) -> list[str]`。

- [ ] **Step 1: 写入失败测试**

```python
from stream_recorder.models import OutputFormat


def test_mp4_command_uses_fragmented_mp4_and_not_hls(tmp_path: Path) -> None:
    config = TaskConfig(
        "task-1", "前门摄像头", "rtsp://example.com/live", tmp_path,
        output_format=OutputFormat.MP4,
    )
    info = parse_probe_json({"streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "avg_frame_rate": "25/1"},
        {"codec_type": "audio", "codec_name": "aac"},
    ]})

    command = build_recorder_command(Path("ffmpeg.exe"), config, info, tmp_path / "output")

    assert command[command.index("-f") + 1] == "mp4"
    assert command[command.index("-movflags") + 1] == "frag_keyframe+empty_moov+default_base_moof"
    assert command[-1] == "recording.mp4"
    assert "-hls_time" not in command


def test_anomaly_monitor_has_no_black_or_freeze_filters(tmp_path: Path) -> None:
    command = build_anomaly_monitor_command(Path("ffmpeg.exe"), _config(tmp_path, "http://example.com/live"))

    assert command[command.index("-vf") + 1] == "fps=1"
    assert "blackdetect" not in command
    assert "freezedetect" not in command
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_ffmpeg_tools.py -v`  
Expected: FAIL，原因是 `OutputFormat` 与 `build_anomaly_monitor_command` 尚不存在。

- [ ] **Step 3: 实现模型和命令分支**

```python
# models.py
class OutputFormat(str, Enum):
    HLS = "hls"
    MP4 = "mp4"


@dataclass(frozen=True)
class TaskConfig:
    task_id: str
    name: str
    source_url: str
    output_root: Path
    segment_seconds: int = 6
    output_format: OutputFormat = OutputFormat.HLS
    enable_anomaly_detection: bool = True
    max_retries: int = 5
```

```python
# ffmpeg_tools.py: _input_arguments
if protocol is Protocol.RTSP:
    arguments.extend(["-rtsp_transport", "tcp"])
```

```python
# ffmpeg_tools.py: build_recorder_command output tail
if config.output_format is OutputFormat.MP4:
    return [*base, "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "recording.mp4"]
return [*base, "-f", "hls", "-hls_time", str(config.segment_seconds), ... , "index.m3u8"]


def build_anomaly_monitor_command(ffmpeg: Path, config: TaskConfig) -> list[str]:
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "repeat+level+info",
            *_input_arguments(config), "-map", "0:v:0", "-an", "-vf", "fps=1", "-f", "null", "-"]
```

- [ ] **Step 4: 运行命令测试确认通过**

Run: `python -m pytest tests/test_ffmpeg_tools.py -v`  
Expected: PASS；HLS 命令保留，MP4 命令无 HLS 参数，RTSP 为 TCP，监视命令无黑屏/冻结滤镜。

## Task 2: 异常事件与收录器行为

**Files:**
- Modify: `src/stream_recorder/events.py`
- Modify: `src/stream_recorder/recorder.py`
- Modify: `tests/test_events.py`
- Modify: `tests/test_recorder.py`

**Interfaces:**
- Consumes: `TaskConfig.output_format`、`TaskConfig.enable_anomaly_detection` 和 `build_anomaly_monitor_command()`。
- Produces: `recording_target(config: TaskConfig, output_dir: Path) -> Path`，返回 `index.m3u8` 或 `recording.mp4`。

- [ ] **Step 1: 写入失败测试**

```python
from stream_recorder.models import OutputFormat, TaskConfig
from stream_recorder.recorder import recording_target


def test_black_and_freeze_diagnostics_are_ignored() -> None:
    assert parse_ffmpeg_line("cam-1", "black_duration:11.1") is None
    assert parse_ffmpeg_line("cam-1", "freeze_duration:16.2") is None


def test_recording_target_follows_selected_format(tmp_path: Path) -> None:
    hls = TaskConfig("hls", "HLS", "http://example.com/live", tmp_path)
    mp4 = TaskConfig("mp4", "MP4", "http://example.com/live", tmp_path, output_format=OutputFormat.MP4)

    assert recording_target(hls, tmp_path / "hls").name == "index.m3u8"
    assert recording_target(mp4, tmp_path / "mp4").name == "recording.mp4"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_events.py tests/test_recorder.py -v`  
Expected: FAIL；现有事件解析仍会返回黑屏/冻结事件，`recording_target` 尚不存在。

- [ ] **Step 3: 实现异常检测开关和格式目标**

```python
# events.py: 删除 black_duration 与 freeze_duration 的正则分支；保留丢帧、断流和无有效画面分支。

# recorder.py
def recording_target(config: TaskConfig, output_dir: Path) -> Path:
    return output_dir / ("recording.mp4" if config.output_format is OutputFormat.MP4 else "index.m3u8")


if self.config.enable_anomaly_detection:
    self._start_anomaly_monitor()

if self.config.enable_anomaly_detection and not self._no_frame_reported and now - self._last_frame_at > 20:
    self._no_frame_reported = True
    self._emit(Severity.WARNING, "无有效画面", "原始视频信号 20 秒未解出有效画面")

if self.config.enable_anomaly_detection:
    event = parse_ffmpeg_line(self.config.task_id, line)
    if event is not None:
        self.logger.log(event)
```

`_start_analyzer`、`_analyzer_process` 与 `analysis` 参数分别重命名为 `_start_anomaly_monitor`、`_monitor_process` 和 `monitor`，只使用 `build_anomaly_monitor_command`。仅 HLS 任务检测并通告 `index.m3u8`；两种格式都使用 `recording_target` 记录输出文件路径。

- [ ] **Step 4: 运行行为测试确认通过**

Run: `python -m pytest tests/test_events.py tests/test_recorder.py -v`  
Expected: PASS；黑屏/冻结文本不会产生事件，输出目标随格式变化。

## Task 3: 简化 PySide6 任务表单

**Files:**
- Modify: `src/stream_recorder/ui/main_window.py`
- Modify: `tests/test_ui.py`

**Interfaces:**
- Produces: `format_combo: QComboBox`，数据为 `OutputFormat.HLS` 与 `OutputFormat.MP4`。
- Produces: `anomaly_button: QPushButton`，可切换并反映 `异常检测：开启/关闭`。
- Consumes: `_set_output_format()` 来显示或隐藏 `segment_label` 与 `segment_spin`。

- [ ] **Step 1: 写入失败测试**

```python
from stream_recorder.models import OutputFormat


def test_capture_form_has_format_and_one_anomaly_toggle(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(TaskController(), Queue(), tmp_path)

    assert window.format_combo.currentData() is OutputFormat.HLS
    assert window.anomaly_button.isCheckable() and window.anomaly_button.isChecked()
    assert not hasattr(window, "transport_combo")
    assert not hasattr(window, "analysis_check")
    assert window.output_button.text() == "选择"
    assert window.output_button.maximumWidth() <= 72

    assert window.segment_label.text() == "切片长度"
    assert not window.segment_label.isHidden() and not window.segment_spin.isHidden()
    window.format_combo.setCurrentIndex(1)
    assert window.segment_label.isHidden() and window.segment_spin.isHidden()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_ui.py -v`  
Expected: FAIL；当前窗口没有格式选择与异常检测按钮，并仍有旧控件。

- [ ] **Step 3: 实现表单简化**

```python
self.output_button = QPushButton("选择")
self.output_button.setObjectName("secondaryButton")
self.output_button.setMaximumWidth(72)
self.output_button.clicked.connect(self._choose_output_root)

self.format_combo = QComboBox()
self.format_combo.addItem("m3u8（HLS）", OutputFormat.HLS)
self.format_combo.addItem("MP4", OutputFormat.MP4)
self.format_combo.currentIndexChanged.connect(self._set_output_format)

self.anomaly_button = QPushButton("异常检测：开启")
self.anomaly_button.setObjectName("detectionToggle")
self.anomaly_button.setCheckable(True)
self.anomaly_button.setChecked(True)
self.anomaly_button.toggled.connect(self._set_anomaly_detection_label)
```

在网格中移除 RTSP 和画面分析两列，显示“输出位置”“切片长度”“收录格式”；将标签保存为 `segment_label`。MP4 选择时调用 `segment_label.setHidden(True)` 与 `segment_spin.setHidden(True)`；切回 m3u8 时恢复显示。`_request_start()` 传入 `output_format=self.format_combo.currentData()` 与 `enable_anomaly_detection=self.anomaly_button.isChecked()`，不再传入 RTSP 传输参数。

- [ ] **Step 4: 运行界面测试确认通过**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_ui.py -v`  
Expected: PASS；旧控件不存在，异常检测按钮可切换，选择 MP4 会隐藏切片长度。

## Task 4: 集成测试、说明与正式 EXE

**Files:**
- Modify: `tests/integration/test_hls_output.py`
- Modify: `README.md`
- Modify: `scripts/build.ps1`（仅在实际需要时保留现有 `src/launcher.py` 入口）

**Interfaces:**
- Validates: H.264/H.265 输入可分别生成 HLS 和 `recording.mp4`。
- Delivers: `dist/流收录程序.exe`。

- [ ] **Step 1: 写入失败 MP4 集成测试**

```python
@pytest.mark.integration
@pytest.mark.parametrize(("encoder", "expected_codec"), (("libx264", "H.264"), ("libx265", "H.265")))
def test_http_stream_becomes_fragmented_mp4(tmp_path: Path, ffmpeg_binary: Path, encoder: str, expected_codec: str) -> None:
    source = _make_source(tmp_path, ffmpeg_binary, encoder)
    info = run_probe(ffmpeg_binary.with_name("ffprobe.exe"), _serve_and_url(tmp_path, source))
    config = TaskConfig("local-mp4", "本地 MP4", "http://127.0.0.1/live", tmp_path, output_format=OutputFormat.MP4)
    output_dir = tmp_path / "mp4"
    output_dir.mkdir()

    subprocess.run(build_recorder_command(ffmpeg_binary, config, info, output_dir), cwd=output_dir, check=True, timeout=60)

    assert info.video_codec == expected_codec
    assert (output_dir / "recording.mp4").is_file()
```

- [ ] **Step 2: 运行集成测试确认失败**

Run: `$env:FFMPEG_BINARY=(Resolve-Path 'bundled\\ffmpeg\\ffmpeg.exe').Path; python -m pytest tests/integration/test_hls_output.py -v`  
Expected: FAIL；MP4 输出格式尚未实现。

- [ ] **Step 3: 更新测试辅助函数和 README**

将现有 HTTP 服务器与源文件生成逻辑提取为 `_make_source` 和 `_serve_and_url`，避免 HLS 与 MP4 测试重复。README 仅描述“异常检测”，删除黑屏/冻结、画面分析和 RTSP 传输选择说明；增加 m3u8/MP4 输出与“切片长度仅适用于 m3u8”的说明。

- [ ] **Step 4: 运行完整验证和重新打包**

Run:

```powershell
$env:FFMPEG_BINARY = (Resolve-Path 'bundled\ffmpeg\ffmpeg.exe').Path
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest -v
.\scripts\build.ps1
```

Expected: 全部单元与 H.264/H.265 的 HLS、MP4 集成测试通过；生成 `dist\流收录程序.exe`。

- [ ] **Step 5: 正常窗口启动验证**

Run: 通过 Windows 正常启动 `dist\流收录程序.exe`，确认主窗口标题为“流收录程序”，没有 `Unhandled exception in script` 窗口；验证完成后关闭仅由验证创建的进程。

## Plan Self-Review

- Spec coverage: Task 1 实现格式与默认 TCP；Task 2 删除黑屏/冻结并控制异常检测；Task 3 简化 UI 和缩小选择按钮；Task 4 覆盖两种编码、两种格式、文档与 EXE。
- Placeholder scan: 未发现未完成占位或未定义的后续步骤。
- Type consistency: `OutputFormat` 在模型、命令构建器、收录器、UI 与集成测试使用同一枚举；`enable_anomaly_detection` 在 UI 和收录器使用同一字段。
