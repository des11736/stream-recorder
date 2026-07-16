# 最终审查修复：重连计时与地址持久化时序

## 必须修复

1. `Recorder._run()` 的第 2 次及后续重试必须在等待退避时间之前发布 `TaskStatus.RECONNECTING`，使 UI 在整个 2/4/8/16/30 秒等待期间暂停时长。开始实际 FFmpeg 尝试前才发布 `TaskStatus.RECORDING`。不改变重试次数、退避秒数、停止逻辑或中文重连日志。
2. 主窗口仅能在 `start_requested.emit(config)` 成功发出后保存并 `sync()` 规范化地址。任务行可以在发射前创建；保存不得发生在发射前。
3. 增加回归测试：
   - 使用替代 `_stop_requested` 与替换 `_run_once` 的 Recorder 测试，断言第一个非零退避 `wait()` 被调用时最后一个状态是 `RECONNECTING`，并保持原先 `RECORDING → RECONNECTING → RECORDING → FAILED` 顺序。
   - UI 测试让 `start_requested` 槽在信号发出时读取临时 INI setting，断言当时仍是旧地址；信号之后 setting 才变为规范化新地址。
   - 将任务时长冻结断言参数化或单独增加测试，覆盖 `STOPPED` 与 `FAILED` 两个终态。

## 约束

- 仅修改 `src/stream_recorder/recorder.py`、`src/stream_recorder/ui/main_window.py`、`tests/test_recorder.py`、`tests/test_ui.py`。
- 严格测试先行；先看到对应回归测试失败，再做最小修复。
- 不修改时长累计器、FFmpeg 命令、日志处理或持久化的键名。

## 验收

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_recorder.py tests/test_ui.py -v
```

通过后运行完整测试：

```powershell
$env:FFMPEG_BINARY = (Resolve-Path 'bundled\ffmpeg\ffmpeg.exe').Path
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest -v
```
