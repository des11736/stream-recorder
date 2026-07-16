from stream_recorder import subprocess_options
from stream_recorder.subprocess_options import hidden_console_kwargs



def test_windows_uses_create_no_window_flag(monkeypatch) -> None:
    create_no_window = 0x08000000
    monkeypatch.setattr(
        subprocess_options.subprocess,
        "CREATE_NO_WINDOW",
        create_no_window,
        raising=False,
    )

    assert hidden_console_kwargs("Windows") == {"creationflags": create_no_window}


def test_non_windows_uses_no_creation_flags() -> None:
    assert hidden_console_kwargs("Linux") == {}
