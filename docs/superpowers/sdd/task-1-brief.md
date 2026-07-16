# Task 1: 统一隐藏 Windows 子进程控制台窗口

## 范围

- 新增 `src/stream_recorder/subprocess_options.py`，提供 `hidden_console_kwargs(platform_name: str | None = None) -> dict[str, int]`。
- Windows 返回 `{"creationflags": subprocess.CREATE_NO_WINDOW}`，其他平台返回 `{}`。
- `ffmpeg_tools.run_probe()` 调用 FFprobe 时必须传入这个参数；为可测试性，可添加仅用于注入 `subprocess.run` 的可选 `runner` 参数，默认仍为 `subprocess.run`。
- `Recorder._run_once()` 和 `Recorder._start_anomaly_monitor()` 启动两类 FFmpeg 时必须传入相同参数。
- 不改变日志管道、标准输入输出重定向、启动命令或异常检测行为。

## 测试先行

先在 `tests/test_subprocess_options.py` 覆盖 Windows/非 Windows 的返回值；在 `tests/test_ffmpeg_tools.py` 验证 FFprobe 的 runner 收到 `creationflags`；在 `tests/test_recorder.py` 用假进程工厂验证主收录与异常检测进程均收到相同参数。先运行并确认新测试失败，再做最小实现。

## 验收

运行：`python -m pytest tests/test_subprocess_options.py tests/test_ffmpeg_tools.py tests/test_recorder.py -v`

全部通过，且在 Windows 打包 GUI 下不会为 FFprobe 或任一 FFmpeg 子进程创建 CMD 窗口。
