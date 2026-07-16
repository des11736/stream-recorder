# Task 3: 在主窗口接入地址记忆和任务时长

## 范围

- 仅修改 `src/stream_recorder/ui/main_window.py` 与 `tests/test_ui.py`。
- 使用 Task 2 的 `RecordingDuration` 和 `format_duration`。
- 在 `MainWindow.__init__` 添加仅关键字的可选参数：`settings: QSettings | None = None` 与 `clock: Callable[[], float] | None = None`；默认 settings 为 `QSettings("流收录程序", "流收录程序")`，默认 clock 为 `time.monotonic`。
- 使用常量键名 `last_stream_url`。窗口创建时将该键的字符串值填入流地址框；不存在时保留空输入框。
- 只有通过地址校验、即将创建任务的规范化地址才写回 QSettings 并调用 `sync()`；无效地址不能覆盖已有值。
- 创建任务行时为该 task_id 创建独立的 `RecordingDuration`，表格的“已收录”列初值仍为 `00:00:00`。
- 使用独立 1 秒 `QTimer` 刷新所有任务的时长列；不得影响既有 100 ms 日志队列定时器。
- 收到 `TaskStatus.RECORDING.value` 时 resume；收到 `RECONNECTING`、`STOPPED`、`FAILED` 时 pause；`PROBING` 不计时。重连后下一次 `RECORDING` 继续累计。停止/失败后保持最后文本不变。
- 保持现有 UI 布局、任务创建、日志消费、输出格式逻辑不变。

## 测试先行

在 `tests/test_ui.py` 增加：

1. 使用临时 INI `QSettings`，成功创建任务后新窗口恢复完整地址。
2. 设置已有地址后尝试无效地址，替换 `show_error` 防止弹窗，断言设置没有被覆盖。
3. 用可变列表模拟 clock：创建任务、发送 RECORDING，推进时间并刷新，断言 `00:00:05`；发送 RECONNECTING 后推进时间仍为 5 秒；再次 RECORDING 并推进后累计；发送 STOPPED 后推进时间，最终文本保持不变。
4. 用两个 task_id 验证不同任务的时长互不影响。

先运行并确认新测试因缺少构造参数/刷新方法而失败，再做最小实现。

## 验收

运行：`$env:QT_QPA_PLATFORM = 'offscreen'; python -m pytest tests/test_ui.py -v`

全部通过；不写入用户真实的默认 QSettings 测试数据。
