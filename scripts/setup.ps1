param([switch]$SkipFFmpeg, [switch]$Worktree)
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
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    # 같은 IDE에서 다른 worktree가 먼저 설치한 경우에도 새 PATH를 찾는다.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    # 2025-09-03 출시. 최초 설치만 고정하고 이미 설치된 uv는 유지한다.
    winget install --id astral-sh.uv --version 0.8.15 --exact --source winget --accept-package-agreements --accept-source-agreements --silent --disable-interactivity
    Confirm-Exit 'uv install'
    # winget의 사용자 PATH 변경을 현재 PowerShell에도 반영한다.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv를 찾을 수 없습니다. 새 터미널에서 scripts/setup.ps1을 다시 실행하세요.'
    }
}
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    $Python = python -c "import sys; print(sys.executable)"
    Confirm-Exit 'Python path'
    uv venv --python $Python .venv
    Confirm-Exit 'venv'
}
# uv는 하드링크 불가 시 경고를 출력하고 복사로 자동 전환한다.
uv pip install --python .venv/Scripts/python.exe --link-mode hardlink -e '.[dev,cuda]'
Confirm-Exit 'Python dependencies'
& .venv/Scripts/python.exe -c "from PySide6 import QtWebEngineWidgets, QtWebChannel"
Confirm-Exit 'Qt WebEngine / WebChannel'
& .venv/Scripts/python.exe scripts/generate_web_types.py --check
Confirm-Exit 'Web bridge types'
Push-Location frontend
try {
    npm ci
    Confirm-Exit 'Frontend dependencies'
    if (-not $Worktree) {
        npm run lint
        Confirm-Exit 'Frontend lint'
        npm run typecheck
        Confirm-Exit 'Frontend typecheck'
    }
    npm run build
    Confirm-Exit 'Frontend build'
} finally { Pop-Location }

if (-not $Worktree -and -not $SkipFFmpeg -and -not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    winget install --id Gyan.FFmpeg --version 9.0.2 --exact --source winget --accept-package-agreements --accept-source-agreements --silent --disable-interactivity
    # winget은 이미 동일 버전이 있으면 비영 종료 코드를 반환할 수 있으므로
    # 실제 실행 파일 검증을 아래 어댑터 탐색으로 수행한다.
}
if (-not (Get-Command 7z -ErrorAction SilentlyContinue) -and -not (Test-Path "$env:ProgramFiles/7-Zip/7z.exe")) {
    if ($Worktree) {
        throw '7-Zip이 없습니다. scripts/setup.ps1을 -Worktree 없이 먼저 실행하세요.'
    }
    winget install --id 7zip.7zip --version 26.04 --exact --source winget --accept-package-agreements --accept-source-agreements --silent --disable-interactivity
    Confirm-Exit '7-Zip'
}
& .venv/Scripts/python.exe scripts/install_libmpv.py
Confirm-Exit 'libmpv'
& .venv/Scripts/python.exe -c "from my_video_manager.adapters import FFmpegMediaReader; m = FFmpegMediaReader(); print(m.ffmpeg); print(m.ffprobe)"
if ($Worktree -and $LASTEXITCODE -ne 0) {
    throw 'FFmpeg/ffprobe 확인에 실패했습니다. scripts/setup.ps1을 -Worktree 없이 먼저 실행하세요.'
}
Confirm-Exit 'FFmpeg check'
& .venv/Scripts/python.exe -c "from my_video_manager.transcription import prepare_cuda_runtime; prepare_cuda_runtime(); import ctranslate2; print('CUDA GPUs:', ctranslate2.get_cuda_device_count()); print('CUDA compute types:', ctranslate2.get_supported_compute_types('cuda'))"
Confirm-Exit 'CUDA runtime check (NVIDIA GPU and current driver required; see README)'
if (-not $Worktree) {
    & .venv/Scripts/python.exe -m pytest
    Confirm-Exit 'pytest'
}
Write-Host 'Ready: .venv/Scripts/python.exe -m my_video_manager'
