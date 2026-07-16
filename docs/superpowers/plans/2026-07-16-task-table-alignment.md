# 运行任务表格对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让运行任务表头与任务行列对齐，固定紧凑的停止按钮，并移除操作单元格的额外底色。

**Architecture:** 仅调整 MainWindow 的表头伸缩模式和操作单元格组件树。第 6 列“最新事件”吸收多余宽度，第 7 列“操作”固定为 120px；停止按钮放入透明、居中的容器，维持原有 stop_requested 信号接口。

**Tech Stack:** Python 3、PySide6、pytest、PyInstaller。

## Global Constraints

- 不修改录制、停止、状态更新、日志、FFmpeg 或任务数据逻辑。
- 保留隐藏的任务 ID 列与既有次要按钮视觉样式。
- 停止按钮的最小和最大尺寸均为 96px × 30px；操作列固定为 120px。
- 在源码测试通过后，生成并启动 Windows EXE 验证。

---

### Task 1: 为表格布局和停止按钮建立回归测试

**Files:**

- Modify: D:\codex_project\流收录程序\tests\test_ui.py:1-267

**Interfaces:**

- Consumes: MainWindow.task_table、MainWindow.stop_requested、MainWindow._task_rows。
- Produces: 两个回归测试，锁定列伸缩模式、紧凑按钮尺寸、透明容器与停止信号行为。

- [ ] **Step 1: 写入失败测试**

将 PySide6 导入替换为：

~~~python
from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtWidgets import QApplication, QHeaderView, QPushButton
~~~

在 _grid_position 之后加入：

~~~python
def test_task_table_keeps_operation_column_fixed_and_event_column_stretched(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(TaskController(), Queue(), tmp_path)
    header = window.task_table.horizontalHeader()

    assert not header.stretchLastSection()
    assert header.sectionResizeMode(6) is QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(7) is QHeaderView.ResizeMode.Fixed
    assert window.task_table.columnWidth(7) == 120


def test_task_row_uses_compact_transparent_stop_button_container(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(TaskController(), Queue(), tmp_path)
    task_id = _create_task(window)
    row = window._task_rows[task_id]
    action_host = window.task_table.cellWidget(row, 7)
    action_layout = action_host.layout()
    stop_button = action_host.findChild(QPushButton, "stopTaskButton")
    requested = []
    window.stop_requested.connect(requested.append)

    assert action_host.styleSheet() == "background: transparent;"
    assert not action_host.autoFillBackground()
    assert action_layout.contentsMargins().left() == 0
    assert action_layout.contentsMargins().top() == 0
    assert action_layout.contentsMargins().right() == 0
    assert action_layout.contentsMargins().bottom() == 0
    assert action_layout.alignment() & Qt.AlignmentFlag.AlignCenter
    assert stop_button.minimumSize() == QSize(96, 30)
    assert stop_button.maximumSize() == QSize(96, 30)

    stop_button.click()

    assert requested == [task_id]
~~~

- [ ] **Step 2: 运行测试并确认失败原因正确**

Run: python -m pytest tests/test_ui.py::test_task_table_keeps_operation_column_fixed_and_event_column_stretched tests/test_ui.py::test_task_row_uses_compact_transparent_stop_button_container -v

Expected: FAIL；当前表头仍启用 stretchLastSection()，且第 7 列单元格组件是直接放入的按钮，没有名为 stopTaskButton 的透明容器。

- [ ] **Step 3: 暂不修改生产代码**

失败输出应证明测试覆盖现有缺陷，而不是导入、测试夹具或拼写错误。

- [ ] **Step 4: 不在本任务提交**

测试与实现必须在 Task 2 同一次提交，避免仅提交已知失败的测试。

### Task 2: 固定操作列并以透明容器承载停止按钮

**Files:**

- Modify: D:\codex_project\流收录程序\src\stream_recorder\ui\main_window.py:16-30,216-235,352-375
- Modify: D:\codex_project\流收录程序\tests\test_ui.py:1-110

**Interfaces:**

- Consumes: QHeaderView.ResizeMode、Qt.AlignmentFlag.AlignCenter、现有 stop_requested: Signal(str)。
- Produces: 固定 120px 的操作列、伸展的最新事件列，以及对象名为 stopTaskButton 的 96px × 30px 停止按钮。

- [ ] **Step 1: 变更生产代码**

将 widgets 导入区中的 QHBoxLayout, 后新增：

~~~python
    QHeaderView,
~~~

在 _build_task_panel 中用以下代码替换当前从 header = self.task_table.horizontalHeader() 到 self.task_table.setColumnWidth(6, 260) 的内容：

~~~python
        header = self.task_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultSectionSize(112)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.task_table.setColumnWidth(0, 150)
        self.task_table.setColumnWidth(5, 200)
        self.task_table.setColumnWidth(7, 120)
~~~

在 add_task_row 中用以下代码替换从 stop_button = QPushButton("停止") 到 setCellWidget 的内容：

~~~python
        action_host = QWidget()
        action_host.setStyleSheet("background: transparent;")
        action_host.setAutoFillBackground(False)
        action_layout = QHBoxLayout(action_host)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stop_button = QPushButton("停止")
        stop_button.setObjectName("stopTaskButton")
        stop_button.setProperty("variant", "secondary")
        stop_button.setFixedSize(96, 30)
        stop_button.clicked.connect(lambda _checked=False, task_id=config.task_id: self.stop_requested.emit(task_id))
        action_layout.addWidget(stop_button)
        self.task_table.setCellWidget(row, 7, action_host)
~~~

在 _apply_console_theme 中将次要按钮选择器改为同时覆盖按钮属性：

~~~css
            QPushButton#secondaryButton, QPushButton[variant="secondary"] { background: #ffffff; color: #365a94; border-color: #c8d8ef; }
~~~

- [ ] **Step 2: 运行定向测试并确认通过**

Run: python -m pytest tests/test_ui.py::test_task_table_keeps_operation_column_fixed_and_event_column_stretched tests/test_ui.py::test_task_row_uses_compact_transparent_stop_button_container -v

Expected: 2 passed。

- [ ] **Step 3: 运行完整测试集**

Run: python -m pytest -v

Expected: 所有测试通过；无测试失败。

- [ ] **Step 4: 生成人工验证截图和 Windows EXE**

Run: python -m PyInstaller --noconfirm --clean "流收录程序-参考图界面版.spec"

Expected: 命令成功，并输出 D:\codex_project\流收录程序\dist\流收录程序-参考图界面版.exe。

随后以隐藏窗口方式启动 EXE 5 秒并确认进程仍在运行，再终止本次验证创建的进程；这不会影响用户已经启动的程序。

- [ ] **Step 5: 提交实现与测试**

~~~powershell
git add src/stream_recorder/ui/main_window.py tests/test_ui.py
git commit -m "fix(ui): align task action column"
~~~

