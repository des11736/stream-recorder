"""Top-level entry point used by PyInstaller's frozen executable."""

from stream_recorder.main import main


if __name__ == "__main__":
    raise SystemExit(main())
