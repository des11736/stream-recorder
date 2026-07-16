from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class Protocol(str, Enum):
    RTMP = "rtmp"
    RTSP = "rtsp"
    HTTP = "http"


class OutputFormat(str, Enum):
    HLS = "hls"
    MP4 = "mp4"


class TaskStatus(str, Enum):
    STOPPED = "已停止"
    PROBING = "正在检测"
    RECORDING = "收录中"
    RECONNECTING = "正在重连"
    FAILED = "失败"


class Severity(str, Enum):
    INFO = "信息"
    WARNING = "警告"
    ERROR = "错误"


@dataclass(frozen=True)
class StreamInfo:
    video_codec: str
    width: int
    height: int
    frame_rate: str
    audio_codec: str | None


@dataclass(frozen=True)
class TaskConfig:
    task_id: str
    name: str
    source_url: str
    output_root: Path
    segment_seconds: int = 6
    output_format: OutputFormat = OutputFormat.HLS
    enable_anomaly_detection: bool = True
    max_retries: int = 5

    def to_json(self) -> dict:
        data = asdict(self)
        data["output_root"] = str(self.output_root)
        return data
