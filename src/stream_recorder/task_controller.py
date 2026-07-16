from typing import Any


class TaskController:
    """Keep independently running recorders addressable by a stable task id."""

    def __init__(self) -> None:
        self.recorders: dict[str, Any] = {}
        self.stream_info: dict[str, Any] = {}

    def register(self, task_id: str, recorder: Any, stream_info: Any) -> None:
        self.recorders[task_id] = recorder
        self.stream_info[task_id] = stream_info

    def unregister(self, task_id: str) -> None:
        recorder = self.recorders.pop(task_id, None)
        self.stream_info.pop(task_id, None)
        if recorder is not None:
            recorder.stop()

    def start(self, task_id: str) -> None:
        self.recorders[task_id].start(self.stream_info[task_id])

    def stop(self, task_id: str) -> None:
        self.recorders[task_id].stop()

    def stop_all(self) -> None:
        for recorder in tuple(self.recorders.values()):
            recorder.stop()
