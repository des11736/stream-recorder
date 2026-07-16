from stream_recorder.duration import RecordingDuration, format_duration


def test_accumulates_elapsed_time_across_pause_and_resume() -> None:
    duration = RecordingDuration()

    duration.resume(10.0)
    assert duration.seconds(11.9) == 1

    duration.pause(20.0)
    duration.resume(25.0)

    assert duration.seconds(30.9) == 15


def test_repeated_resume_does_not_restart_the_active_interval() -> None:
    duration = RecordingDuration()

    duration.resume(10.0)
    duration.resume(20.0)
    duration.pause(30.0)

    assert duration.seconds(30.0) == 20


def test_repeated_pause_keeps_the_duration_frozen() -> None:
    duration = RecordingDuration()

    duration.resume(10.0)
    duration.pause(15.0)
    duration.pause(30.0)

    assert duration.seconds(1_000.0) == 5


def test_unstarted_duration_is_zero() -> None:
    assert RecordingDuration().seconds(1_000.0) == 0


def test_formats_zero_duration() -> None:
    assert format_duration(0) == "00:00:00"


def test_formats_one_hour_one_minute_one_second() -> None:
    assert format_duration(3_661) == "01:01:01"


def test_formats_hours_beyond_one_day_without_wrapping() -> None:
    assert format_duration(90_061) == "25:01:01"
