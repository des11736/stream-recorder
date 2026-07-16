$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BundledFfmpeg = Join-Path $ProjectRoot "bundled\ffmpeg\ffmpeg.exe"
$BundledFfprobe = Join-Path $ProjectRoot "bundled\ffmpeg\ffprobe.exe"
$License = Join-Path $ProjectRoot "bundled\ffmpeg\LICENSE-FFmpeg.txt"

Push-Location $ProjectRoot
try {
    python -m pip install -e ".[dev]"
    if (-not (Test-Path -LiteralPath $BundledFfmpeg) -or -not (Test-Path -LiteralPath $BundledFfprobe)) {
        & (Join-Path $PSScriptRoot "fetch_ffmpeg.ps1")
    }

    $Arguments = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "流收录程序",
        "--paths", "src",
        "--add-binary", "bundled\ffmpeg\ffmpeg.exe;ffmpeg",
        "--add-binary", "bundled\ffmpeg\ffprobe.exe;ffmpeg"
    )
    if (Test-Path -LiteralPath $License) {
        $Arguments += @("--add-data", "bundled\ffmpeg\LICENSE-FFmpeg.txt;ffmpeg")
    }
    $Arguments += "src\launcher.py"
    & python @Arguments
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "dist\流收录程序.exe"))) {
        throw "PyInstaller 未生成预期的 EXE 文件"
    }
}
finally {
    Pop-Location
}

