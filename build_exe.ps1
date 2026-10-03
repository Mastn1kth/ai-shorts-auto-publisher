$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  throw 'Сначала создайте .venv и установите requirements-build.txt (см. README).'
}
$buildTemp = Join-Path $PSScriptRoot '.build-temp'
New-Item -ItemType Directory -Force -Path $buildTemp | Out-Null
$env:TEMP = $buildTemp
$env:TMP = $buildTemp
$env:PYINSTALLER_CONFIG_DIR = Join-Path $buildTemp 'pyinstaller-cache'

$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source

& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name 'Shortform Studio' `
  --add-data 'web;web' `
  --add-binary "$ffmpeg;." `
  --add-binary "$ffprobe;." `
  --collect-all faster_whisper `
  --collect-all ctranslate2 `
  --collect-all onnxruntime `
  --collect-all cv2 `
  --collect-all av `
  --collect-all yt_dlp `
  --collect-all webview `
  --collect-all google.genai `
  --hidden-import shorts_generator.local.transcriber `
  --hidden-import shorts_generator.local.downloader `
  --hidden-import shorts_generator.local.clipper `
  --hidden-import shorts_generator.local.llm `
  --exclude-module torch `
  --exclude-module torchvision `
  --exclude-module PyQt5 `
  --exclude-module PyQt6 `
  --exclude-module PySide6 `
  desktop.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Write-Host "Готово: $PSScriptRoot\dist\Shortform Studio\Shortform Studio.exe"
