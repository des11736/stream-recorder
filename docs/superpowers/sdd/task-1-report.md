# Task 1 implementer report

## 状态

已完成：Windows 下 FFprobe、主收录 FFmpeg 和异常检测 FFmpeg 都会使用
`subprocess.CREATE_NO_WINDOW`，从 GUI 启动时不会额外创建 CMD 控制台窗口。
非 Windows 平台不会传递任何 creation flags。

## TDD 证据

### RED

命令：

```powershell
python -m pytest tests/test_subprocess_options.py tests/test_ffmpeg_tools.py tests/test_recorder.py -v
```

结果：`4 failed, 10 passed`。

- `test_subprocess_options.py` 的两个测试失败：`hidden_console_kwargs` 尚未提供。
- `test_run_probe_passes_create_no_window_flag_to_runner` 失败：`run_probe()` 尚不接受 `runner`。
- `test_recorder_and_anomaly_monitor_share_hidden_console_options` 失败：两个假的 FFmpeg 进程调用均未收到 `creationflags`。

以上失败均直接对应本任务新增的行为。

### GREEN / 最终验收

命令：

```powershell
python -m pytest tests/test_subprocess_options.py tests/test_ffmpeg_tools.py tests/test_recorder.py -v
```

结果：`14 passed in 0.15s`，退出码为 0。

## 修改文件

- `src/stream_recorder/subprocess_options.py`
  - 新增 `hidden_console_kwargs(platform_name=None)`；Windows 返回
    `{"creationflags": subprocess.CREATE_NO_WINDOW}`，其他平台返回 `{}`。
- `src/stream_recorder/ffmpeg_tools.py`
  - `run_probe()` 默认仍调用 `subprocess.run`，并增加仅供测试注入的可选 `runner`。
  - FFprobe 调用展开共用隐藏窗口参数。
- `src/stream_recorder/recorder.py`
  - 主收录和异常检测两处 `process_factory` 调用均展开相同的共用参数。
- `tests/test_subprocess_options.py`
  - 新增 Windows 与非 Windows 参数返回值测试。
- `tests/test_ffmpeg_tools.py`
  - 新增假 runner 测试，确认 FFprobe 收到 `creationflags`。
- `tests/test_recorder.py`
  - 新增假进程工厂测试，确认主收录和异常检测进程均收到相同的 `creationflags`。

## 自查

- 保持 FFprobe/FFmpeg 命令参数不变。
- 保持日志管道、`stdout`/`stderr` 重定向、`cwd` 与异常检测流程不变；仅新增
  Windows 创建标志。
- 默认 `run_probe()` 路径仍是 `subprocess.run`。
- 使用 Windows 上的 `subprocess.CREATE_NO_WINDOW` 常量；非 Windows 返回空参数字典。

## 审查修复追加

### 跨平台测试

- `tests/test_subprocess_options.py` 不再在测试宿主上直接读取
  `subprocess.CREATE_NO_WINDOW`。Windows 分支通过 monkeypatch 注入稳定的标志值，
  因此可以在非 Windows CI 上验证 Windows 行为；Linux 分支明确断言 `{}`。
- `tests/test_ffmpeg_tools.py` 通过替换 `hidden_console_kwargs()` 分别验证传入隐藏
  窗口参数和空参数时的行为；空参数场景明确断言 runner 未收到 `creationflags`。
- `tests/test_recorder.py` 同样替换共用 helper，避免依赖测试宿主平台常量。

### 原有子进程契约覆盖

- FFprobe 测试现在验证完整命令以及既有的 `capture_output`、`check`、`encoding`、
  `errors` 和 `timeout` 参数，另验证新增的隐藏窗口参数。
- 收录测试现在区分主收录（`-progress pipe:1`）和异常检测（`-vf fps=1`）调用；
  分别精确断言两者原有的 `stdout`、`stderr`、`text`、`encoding`、`errors`、
  `bufsize`，以及主收录特有的 `cwd`。两者均断言收到同一隐藏窗口参数。

### 本轮测试

先运行指定命令时发现测试自身遗漏了 `build_probe_command` 导入（`NameError`），
修正导入后无需改动生产代码。最终验收命令：

```powershell
python -m pytest tests/test_subprocess_options.py tests/test_ffmpeg_tools.py tests/test_recorder.py -v
```

结果：`15 passed in 0.08s`，退出码为 0。
