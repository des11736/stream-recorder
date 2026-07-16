# Task 3 实现报告：主窗口地址记忆和任务时长

## 修改范围

- `src/stream_recorder/ui/main_window.py`
  - 注入可选的仅关键字 `QSettings` 与时钟。
  - 恢复/持久化已验证的规范化流地址。
  - 为每项任务维护独立 `RecordingDuration`，并使用独立的 1 秒 `QTimer` 刷新“已收录”列。
  - 根据任务状态暂停或恢复计时，保留停止/失败后的累计值。
- `tests/test_ui.py`
  - 为地址恢复、无效地址保护、计时暂停/恢复以及双任务隔离添加测试。
  - 使既有的成功启动测试使用临时 INI `QSettings`，避免写入真实用户默认设置。

## TDD 证据

### RED

命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; python -m pytest tests/test_ui.py -v
```

结果：退出码 `1`；收集 7 项，2 项通过、5 项失败。新增测试和更新后的启动测试均按预期报出：

```text
TypeError: MainWindow.__init__() got an unexpected keyword argument 'settings'
```

失败原因是生产代码尚未提供简报要求的仅关键字 `settings`（因此也尚未提供 `clock` 和时长刷新机制），不是测试拼写或测试环境错误。

### GREEN（验收命令）

命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; python -m pytest tests/test_ui.py -v
```

结果：退出码 `0`；7 项全部通过，耗时 `0.24s`。

### 回归验证

命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; python -m pytest -v
```

结果：退出码 `0`；46 项通过、4 项跳过，耗时 `0.78s`。跳过的均为既有 FFmpeg 集成测试。

## 自查

- `MainWindow.__init__` 新增的 `settings` 和 `clock` 均为仅关键字参数，默认值分别为 `QSettings("流收录程序", "流收录程序")` 和 `time.monotonic`。
- 使用常量 `LAST_STREAM_URL_KEY = "last_stream_url"`；仅在 URL 和切片时长校验均成功、即将创建任务时写回并调用 `sync()`。
- 无效地址走既有错误分支，不会覆盖已保存地址。
- 新任务行初始化独立 `RecordingDuration`，表格初值仍为 `00:00:00`。
- 新增的 `_duration_timer` 以 1,000 ms 刷新全部任务，与既有的 100 ms `_event_timer` 相互独立。
- `RECORDING` 恢复计时；`PROBING`、`RECONNECTING`、`STOPPED`、`FAILED` 暂停计时。停止和失败后刷新结果保持不变；重连后再次 `RECORDING` 会继续累计。
- 未改变既有布局、任务配置、日志消费或输出格式逻辑。

## 顾虑

无阻塞项。时长刷新依赖正常的 Qt 事件循环；自动化测试通过可注入时钟和直接调用刷新函数避免依赖真实等待时间，同时仍覆盖了生产代码使用的状态事件路径。
