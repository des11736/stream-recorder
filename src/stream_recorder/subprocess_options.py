import platform
import subprocess


def hidden_console_kwargs(platform_name: str | None = None) -> dict[str, int]:
    """Return Windows-only subprocess options that suppress console windows."""
    if (platform_name or platform.system()) == "Windows":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
