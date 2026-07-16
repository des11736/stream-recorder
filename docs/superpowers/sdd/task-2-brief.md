# Task 2: 独立的收录时长累计器

## 范围

- 新增 `src/stream_recorder/duration.py`，只包含无 Qt 依赖的计时逻辑。
- 提供 `RecordingDuration.resume(now: float) -> None`、`pause(now: float) -> None`、`seconds(now: float) -> int` 和 `format_duration(seconds: int) -> str`。
- `resume()` 必须幂等；已经计时的状态再次 resume 不得重新开始。
- `pause()` 必须幂等；暂停后使用之后任意时间读取，累计秒数不得继续增加。
- `seconds()` 以向下取整的累计秒数返回；`format_duration()` 固定输出 `HH:MM:SS`，允许小时数大于 24。
- 不接入 UI、不改变任何现有收录逻辑；该任务仅新增可单测的领域对象。

## 测试先行

新增 `tests/test_duration.py`：覆盖开始/暂停/恢复后的累加、重复 resume/pause 的幂等性、停止后冻结、`00:00:00`、`01:01:01` 和大于 24 小时的格式。先运行并确认新测试失败，再做最小实现。

## 验收

运行：`python -m pytest tests/test_duration.py -v`

全部通过，且模块无 PySide6 依赖。
