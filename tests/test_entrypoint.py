from pathlib import Path
import runpy


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_frozen_entrypoint_imports_package_main_as_a_top_level_script() -> None:
    """PyInstaller must not execute a package-relative module as its entry script."""
    entrypoint = PROJECT_ROOT / "src" / "launcher.py"

    assert entrypoint.is_file()
    namespace = runpy.run_path(str(entrypoint), run_name="pyinstaller_entrypoint")
    assert callable(namespace["main"])
