# 最终审查修复报告：重连计时与地址持久化时序

## 范围

按 `final-fix-brief.md` 执行，生产与测试代码仅修改以下允许文件：

- `src/stream_recorder/recorder.py`
- `src/stream_recorder/ui/main_window.py`
- `tests/test_recorder.py`
- `tests/test_ui.py`

本报告是简报明确要求的交付文档。未执行 Git 命令。

## 根因

1. `Recorder._run()` 在每次 `wait(delay)` 返回后才发布 `RECONNECTING`。因此第二次及后续尝试的 2/4/8/16/30 秒退避期间，UI 仍保留前一次的 `RECORDING` 状态并继续累计时长。
2. `MainWindow._request_start()` 在创建任务行和 `start_requested.emit(config)` 之前调用 `settings.setValue()` 与 `sync()`。因此任何同步信号槽在收到启动请求时都会读到新的规范化地址，而不是先前已保存的地址。
3. `MainWindow.update_task()` 已对 `STOPPED` 和 `FAILED` 调用 `duration.pause()`；原测试只覆盖 `STOPPED`，缺少 `FAILED` 的回归覆盖。

## TDD 证据

### RED：先写测试并确认失败

新增/扩展的回归测试：

- `test_recorder_marks_reconnecting_before_nonzero_backoff_wait`：替换 `_stop_requested` 与 `_run_once`，在首个非零 `wait()` 调用时记录状态，并断言完整状态顺序。
- `test_task_request_persists_normalized_address_after_start_signal`：在 `start_requested` 的同步槽中从临时 INI 文件读取地址，并断言信号发出期间仍是旧地址；返回后才是规范化地址。
- `test_recording_duration_accumulates_only_while_recording` 参数化 `STOPPED` 和 `FAILED` 两个终态。

在未修改生产代码时运行：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_recorder.py::test_recorder_marks_reconnecting_before_nonzero_backoff_wait tests/test_ui.py::test_task_request_persists_normalized_address_after_start_signal tests/test_ui.py::test_recording_duration_accumulates_only_while_recording -v
```

结果：4 项中 2 项失败、2 项通过。

- 重连测试失败：首个非零退避等待时观测到 `TaskStatus.RECORDING`，预期为 `TaskStatus.RECONNECTING`。
- 持久化测试失败：信号槽中读到 `rtmp://camera.example.com/live`，预期为旧地址 `rtsp://camera.example.com/previous`。
- 终态冻结参数化的 `STOPPED` 与 `FAILED` 均通过，证实对应生产分支原本正确，无需修改时长累计器。

### GREEN：最小修复后回归通过

对同一命令重新运行，结果为 4 passed（0.27s）。

## 最小实现修改

1. `Recorder._run()`：仅将 `TaskStatus.RECONNECTING` 的发布移动到每个非首次尝试的 `wait(delay)` 之前；保持原有退避序列、重试次数、停止分支和中文重连日志内容不变。实际 FFmpeg 尝试前仍发布 `TaskStatus.RECORDING`。
2. `MainWindow._request_start()`：任务行仍可在发射前创建；将 `LAST_STREAM_URL_KEY` 的 `setValue()` 与 `sync()` 移到 `start_requested.emit(config)` 返回之后。键名与规范化方式未改变。
3. `tests/test_ui.py`：将已有时长冻结断言参数化，以覆盖 `STOPPED` 与 `FAILED`，未修改时长累计实现。

## 验证结果

简报指定的 focused 测试：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_recorder.py tests/test_ui.py -v
```

结果：16 passed（0.33s）。

简报指定的完整测试：

```powershell
$env:FFMPEG_BINARY = (Resolve-Path 'bundled\ffmpeg\ffmpeg.exe').Path
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest -v
```

结果：53 passed（3.68s），包含 4 个本地 FFmpeg 集成测试。

## 自查

- 非零退避调用 `wait()` 时状态已为 `RECONNECTING`；成功离开等待后，才进入 `RECORDING`。
- 回归断言确认状态序列仍为 `RECORDING → RECONNECTING → RECORDING → FAILED`。
- 同步启动信号槽读到旧 INI 值，信号返回后才读到规范化新值。
- 时长冻结覆盖两个终态，且未改动 `RecordingDuration` 或其累计逻辑。
- 未改动 FFmpeg 命令、重连日志文本、持久化键名、退避秒数、重试次数或停止逻辑。
