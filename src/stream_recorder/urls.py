from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Protocol

_PROTOCOLS = {
    "rtmp": Protocol.RTMP,
    "rtmps": Protocol.RTMP,
    "rtsp": Protocol.RTSP,
    "http": Protocol.HTTP,
    "https": Protocol.HTTP,
}
_SENSITIVE_QUERY_KEYS = {"token", "signature", "sig", "key", "auth", "password", "pass"}


def normalize_stream_url(url: str) -> str:
    """Trim a URL and correct the common RTMP spelling mistake."""
    value = url.strip()
    if value.lower().startswith("rmtp://"):
        return "rtmp://" + value[7:]
    return value


def validate_stream_url(url: str) -> Protocol:
    """Return the supported protocol or raise a user-facing validation error."""
    normalized = normalize_stream_url(url)
    parts = urlsplit(normalized)
    protocol = _PROTOCOLS.get(parts.scheme.lower())
    if protocol is None or not parts.hostname:
        raise ValueError("请输入有效的 RTMP、RTSP、HTTP 或 HTTPS 流地址")
    try:
        _ = parts.port
    except ValueError as error:
        raise ValueError("流地址的端口格式无效") from error
    return protocol


def validate_segment_seconds(seconds: int) -> int:
    """Ensure the selected HLS segment duration stays practical."""
    if not 2 <= int(seconds) <= 60:
        raise ValueError("分片时长必须介于 2 到 60 秒之间")
    return int(seconds)


def mask_stream_url(url: str) -> str:
    """Remove credentials and common signed URL parameters from visible logs."""
    parts = urlsplit(normalize_stream_url(url))
    netloc = parts.netloc.rsplit("@", 1)[-1]
    if parts.username:
        netloc = f"{parts.username}:***@{netloc}"
    query = urlencode(
        [
            (key, "***" if key.lower() in _SENSITIVE_QUERY_KEYS else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ],
        safe="*",
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))
