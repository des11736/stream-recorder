import pytest

from stream_recorder.models import Protocol
from stream_recorder.urls import (
    mask_stream_url,
    normalize_stream_url,
    validate_segment_seconds,
    validate_stream_url,
)


def test_rmtp_is_normalized_and_credentials_are_masked() -> None:
    url = normalize_stream_url("rmtp://alice:secret@example.com/live?token=abc&quality=main")

    assert url == "rtmp://alice:secret@example.com/live?token=abc&quality=main"
    assert validate_stream_url(url) is Protocol.RTMP
    assert mask_stream_url(url) == "rtmp://alice:***@example.com/live?token=***&quality=main"


@pytest.mark.parametrize("url", ("", "file:///C:/video.mp4", "ftp://example.com/live", "rtsp://"))
def test_rejects_empty_or_unsupported_stream_urls(url: str) -> None:
    with pytest.raises(ValueError, match="RTMP|RTSP|HTTP|地址"):
        validate_stream_url(url)


@pytest.mark.parametrize("seconds", (2, 6, 60))
def test_accepts_hls_segment_duration_in_supported_range(seconds: int) -> None:
    assert validate_segment_seconds(seconds) == seconds


@pytest.mark.parametrize("seconds", (1, 61))
def test_rejects_hls_segment_duration_outside_supported_range(seconds: int) -> None:
    with pytest.raises(ValueError, match="2.*60"):
        validate_segment_seconds(seconds)
