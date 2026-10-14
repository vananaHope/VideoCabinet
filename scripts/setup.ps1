param([switch]$SkipFFmpeg)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Confirm-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)" }
}

python -c "import struct, sys; assert sys.version_info >= (3, 10) and struct.calcsize('P') == 8, '64-bit Python 3.10+ is required'"
Confirm-Exit 'Python check'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js 22.12 이상이 필요합니다. https://nodejs.org/en/download 에서 설치하고 새 터미널에서 다시 실행하세요 (README 환경 준비 참고).'
}
node -e "const [major, minor] = process.versions.node.split('.').map(Number); process.exit(major < 22 || (major === 22 && minor < 12) ? 1 : 0)"
if ($LASTEXITCODE -ne 0) {
    throw 'Node.js 22.12 이상이 필요합니다. https://nodejs.org/en/download 에서 업데이트하고 새 터미널에서 다시 실행하세요 (README 환경 준비 참고).'
}
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    python -m venv .venv
    Confirm-Exit 'venv'
}
& .venv/Scripts/python.exe -m pip install --upgrade pip
Confirm-Exit 'pip upgrade'
& .venv/Scripts/python.exe -m pip install -e '.[dev,cuda]'
Confirm-Exit 'Python dependencies'
& .venv/Scripts/python.exe -c "from PySide6 import QtWebEngineWidgets, QtWebChannel"
Confirm-Exit 'Qt WebEngine / WebChannel'
& .venv/Scripts/python.exe scripts/generate_web_types.py --check
Confirm-Exit 'Web bridge types'
Push-Location frontend
try {
    npm ci
    Confirm-Exit 'Frontend dependencies'
    npm run lint
    Confirm-Exit 'Frontend lint'
    npm run typecheck
    Confirm-Exit 'Frontend typecheck'
    npm run build
    Confirm-Exit 'Frontend build'
} finally { Pop-Location }

if (-not $SkipFFmpeg -and -not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    winget install --id Gyan.FFmpeg --version 9.0.2 --exact --source winget --accept-package-agreements --accept-source-agreements --silent --disable-interactivity
    # winget은 이미 동일 버전이 있으면 비영 종료 코드를 반환할 수 있으므로
    # 실제 실행 파일 검증을 아래 어댑터 탐색으로 수행한다.
}
if (-not (Get-Command 7z -ErrorAction SilentlyContinue) -and -not (Test-Path "$env:ProgramFiles/7-Zip/7z.exe")) {
    winget install --id 7zip.7zip --version 26.04 --exact --source winget --accept-package-agreements --accept-source-agreements --silent --disable-interactivity
    Confirm-Exit '7-Zip'
}
& .venv/Scripts/python.exe scripts/install_libmpv.py
Confirm-Exit 'libmpv'
& .venv/Scripts/python.exe -c "from my_video_manager.adapters import FFmpegMediaReader; m = FFmpegMediaReader(); print(m.ffmpeg); print(m.ffprobe)"
Confirm-Exit 'FFmpeg check'
& .venv/Scripts/python.exe -c "from my_video_manager.transcription import prepare_cuda_runtime; prepare_cuda_runtime(); import ctranslate2; print('CUDA GPUs:', ctranslate2.get_cuda_device_count()); print('CUDA compute types:', ctranslate2.get_supported_compute_types('cuda'))"
Confirm-Exit 'CUDA runtime check (NVIDIA GPU and current driver required; see README)'
& .venv/Scripts/python.exe -m pytest
Confirm-Exit 'pytest'
Write-Host 'Ready: .venv/Scripts/python.exe -m my_video_manager'
