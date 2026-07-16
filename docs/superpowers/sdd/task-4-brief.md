# Task 4: 更新说明、完整回归、打包与启动验证

## 范围

- 仅修改 `README.md`；不要修改生产代码或测试代码。
- 在功能列表和使用步骤中准确说明：
  - 程序会在下次启动时自动填回上一次成功启动收录的流地址。
  - 任务列表“已收录”只在“收录中”状态递增；检测、重连不递增；停止/失败后保留最终时长。
  - Windows 上 FFprobe、主收录 FFmpeg、异常检测 FFmpeg 不显示 CMD 窗口，日志仍在界面与输出目录日志文件中可见。
- 保留已有 H.264/H.265、HLS/MP4、多任务、异常检测、分片长度等说明。

## 验证

1. 运行完整回归：

```powershell
$env:FFMPEG_BINARY = (Resolve-Path 'bundled\ffmpeg\ffmpeg.exe').Path
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest -v
```

2. 创建新包：

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name '流收录程序-时长地址修正版' --paths src --add-binary 'bundled\ffmpeg\ffmpeg.exe;ffmpeg' --add-binary 'bundled\ffmpeg\ffprobe.exe;ffmpeg' --add-data 'bundled\ffmpeg\LICENSE-FFmpeg.txt;ffmpeg' 'src\launcher.py'
```

3. 用 `Start-Process -WindowStyle Hidden -PassThru` 启动新 EXE；等待 5 秒，确认该 PID 仍存在，再只终止这个验证进程。

## 验收

- README 的描述与实际实现一致。
- 完整测试全部通过，包含 H.264/H.265 的 HLS/MP4 集成测试。
- `dist\流收录程序-时长地址修正版.exe` 存在并已成功启动验证。
