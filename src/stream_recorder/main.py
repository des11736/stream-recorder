import sys
from pathlib import Path
from queue import Queue

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .events import LogEvent
from .resources import locate_ffmpeg_tools
from .service import RecordingService
from .task_controller import TaskController
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    event_queue: Queue[LogEvent] = Queue()
    window = MainWindow(TaskController(), event_queue, Path.home() / "Videos" / "流收录")

    try:
        ffmpeg, ffprobe = locate_ffmpeg_tools()
        service = RecordingService(event_queue, ffmpeg, ffprobe)
        window.start_requested.connect(service.start)
        window.stop_requested.connect(service.stop)
        app.aboutToQuit.connect(service.stop_all)
        window.engine_badge.setText("FFMPEG · 已就绪")
    except RuntimeError as error:
        window.engine_badge.setText("FFMPEG · 缺失")
        QTimer.singleShot(0, lambda: window.show_error(str(error)))

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
