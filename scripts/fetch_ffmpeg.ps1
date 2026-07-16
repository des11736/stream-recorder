param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\bundled\ffmpeg")
)

$ErrorActionPreference = "Stop"
$Version = "8.1.2"
$ExpectedSha256 = "B8CDEFAB5F50590A076C27C2B56B0294A0E6154FADED28BA1BA05EBC4F801F57"
$Url = "https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/ffmpeg-8.1.2-full_build.zip"
$Archive = Join-Path $env:TEMP "ffmpeg-$Version-full_build.zip"
$ExtractRoot = Join-Path $env:TEMP "ffmpeg-$Version-extract"

Invoke-WebRequest -Uri $Url -OutFile $Archive
$ActualSha256 = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
if ($ActualSha256 -ne $ExpectedSha256) {
    throw "FFmpeg 下载文件校验失败。期望 SHA-256：$ExpectedSha256；实际：$ActualSha256"
}

if (Test-Path -LiteralPath $ExtractRoot) {
    Remove-Item -LiteralPath $ExtractRoot -Recurse -Force
}
Expand-Archive -LiteralPath $Archive -DestinationPath $ExtractRoot -Force
$Ffmpeg = Get-ChildItem -LiteralPath $ExtractRoot -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if ($null -eq $Ffmpeg) {
    throw "压缩包中未找到 ffmpeg.exe"
}
$Ffprobe = Join-Path $Ffmpeg.Directory.FullName "ffprobe.exe"
if (-not (Test-Path -LiteralPath $Ffprobe)) {
    throw "压缩包中未找到 ffprobe.exe"
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Copy-Item -LiteralPath $Ffmpeg.FullName -Destination (Join-Path $Destination "ffmpeg.exe") -Force
Copy-Item -LiteralPath $Ffprobe -Destination (Join-Path $Destination "ffprobe.exe") -Force
$License = Get-ChildItem -LiteralPath $ExtractRoot -Recurse -Include "LICENSE*", "COPYING*" | Select-Object -First 1
if ($null -ne $License) {
    Copy-Item -LiteralPath $License.FullName -Destination (Join-Path $Destination "LICENSE-FFmpeg.txt") -Force
}

$VersionLine = & (Join-Path $Destination "ffmpeg.exe") -version | Select-Object -First 1
if ($VersionLine -notmatch "ffmpeg version $Version") {
    throw "内置 FFmpeg 版本不正确：$VersionLine"
}
Write-Host "已准备 FFmpeg $Version：$Destination"

