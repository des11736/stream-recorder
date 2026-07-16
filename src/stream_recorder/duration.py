"""Recording-duration tracking without UI dependencies."""


class RecordingDuration:
    """Accumulate elapsed recording time across pause and resume cycles."""

    def __init__(self) -> None:
        self._accumulated_seconds = 0.0
        self._resumed_at: float | None = None

    def resume(self, now: float) -> None:
        """Begin counting time, unless the duration is already running."""
        if self._resumed_at is None:
            self._resumed_at = now

    def pause(self, now: float) -> None:
        """Stop counting time, unless the duration is already paused."""
        if self._resumed_at is not None:
            self._accumulated_seconds += now - self._resumed_at
            self._resumed_at = None

    def seconds(self, now: float) -> int:
        """Return the accumulated duration, rounded down to whole seconds."""
        elapsed = self._accumulated_seconds
        if self._resumed_at is not None:
            elapsed += now - self._resumed_at
        return int(elapsed)


def format_duration(seconds: int) -> str:
    """Format a duration as ``HH:MM:SS`` without limiting the hour field."""
    hours, remainder = divmod(seconds, 3_600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
