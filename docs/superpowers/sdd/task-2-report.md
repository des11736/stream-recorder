# Task 2 实施报告：独立的收录时长累计器

## 实施结果

新增无 Qt 依赖的 `stream_recorder.duration` 模块，提供：

- `RecordingDuration.resume(now)`：开始计时；运行中重复调用不重置起点。
- `RecordingDuration.pause(now)`：冻结当前累计值；暂停中重复调用不改变累计值。
- `RecordingDuration.seconds(now)`：返回累计的向下取整秒数。
- `format_duration(seconds)`：固定输出 `HH:MM:SS`，小时数不会在 24 后回绕。

## TDD 记录

### RED

先仅新增 `tests/test_duration.py`，然后运行：

```powershell
python -m pytest tests/test_duration.py -v
```

输出摘要：测试收集失败（0 个测试项），原因为
`ModuleNotFoundError: No module named 'stream_recorder.duration'`。
这证明测试失败的原因是目标模块尚未实现。

### GREEN / 验收

新增最小实现后运行：

```powershell
python -m pytest tests/test_duration.py -v
```

输出摘要：收集到 7 个测试项，全部通过；退出码 `0`；耗时 `0.02s`。

## 修改文件

- `src/stream_recorder/duration.py`
- `tests/test_duration.py`
- 本报告：`docs/superpowers/sdd/task-2-report.md`

## 自查

- 开始、暂停、恢复后的累计时间已有测试覆盖。
- 连续两次 `resume()` 不会重置计时起点；连续两次 `pause()` 后时长保持冻结。
- 未开始计时读取为零；运行期间的小数秒经 `int()` 向下取整。
- 已覆盖 `00:00:00`、`01:01:01` 与 `25:01:01`（超过 24 小时）。
- `duration.py` 仅使用 Python 标准语言构件，未导入 PySide6 或其他 Qt 模块。
