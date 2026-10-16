param(
    [switch]$SkipPyInstaller,
    [string]$AppDirectory = 'dist/my-video-manager',
    [string]$OutputDirectory = 'dist/installer',
    [string]$InnoCompiler = '',
    [string]$Version = ''
)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Confirm-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)" }
}

$Python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Python 환경이 없습니다. README의 scripts/setup.ps1을 먼저 실행하세요.'
}
foreach ($Tool in @('node', 'npm')) {
    if (-not (Get-Command $Tool -ErrorAction SilentlyContinue)) {
        throw 'Node.js 22.12 이상이 필요합니다: https://nodejs.org/en/download (설치 후 새 터미널에서 실행)'
    }
}
node -e "const [major, minor] = process.versions.node.split('.').map(Number); process.exit(major < 22 || (major === 22 && minor < 12) ? 1 : 0)"
Confirm-Exit 'Node.js 22.12+'
if (-not $InnoCompiler) {
    $Found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($Found) { $InnoCompiler = $Found.Source }
    else {
        $Candidates = @(
            "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe",
            "$env:LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe"
        )
        $InnoCompiler = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler)) {
    throw 'Inno Setup 6의 ISCC.exe가 필요합니다. https://jrsoftware.org/isdl.php 에서 설치하거나 -InnoCompiler 경로를 지정하세요.'
}
if (-not [IO.Path]::IsPathRooted($AppDirectory)) { $AppDirectory = Join-Path (Get-Location) $AppDirectory }
$AppDirectory = [IO.Path]::GetFullPath($AppDirectory)
if (-not [IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path (Get-Location) $OutputDirectory
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

$VersionScript = @'
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
print(tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])
'@
if (-not $Version) {
    $Version = & $Python -c $VersionScript
    Confirm-Exit 'pyproject.toml version (Python 3.10은 setup의 tomli 필요)'
}
if ($Version -notmatch '^\d+\.\d+\.\d+(\.\d+)?$') { throw "Inno Setup에 사용할 수 없는 버전: $Version" }

# 1. 웹 빌드
Push-Location frontend
try {
    if (-not (Test-Path node_modules)) {
        npm ci
        Confirm-Exit 'Frontend dependencies'
    }
    npm run build
    Confirm-Exit 'Frontend build'
} finally { Pop-Location }
# 2. 생성 검사: 생성 파일은 여기서 변경하지 않는다.
& $Python scripts/generate_web_types.py --check
Confirm-Exit 'Generated contracts'
# 3. onedir: CUDA는 제외하고 Qt WebEngine·웹·미디어 도구를 동봉한다.
if (-not $SkipPyInstaller) {
    & $Python -m PyInstaller --version
    Confirm-Exit 'PyInstaller (uv pip install --python .venv/Scripts/python.exe --link-mode hardlink -e .[build])'
    & $Python scripts/prepare_bundle.py --version $Version
    Confirm-Exit 'Bundle assets'
    & $Python -m PyInstaller --noconfirm --clean --distpath (Split-Path $AppDirectory) installer/my-video-manager.spec
    Confirm-Exit 'PyInstaller'
    $BuiltDirectory = Join-Path (Split-Path $AppDirectory) 'my-video-manager'
    if ($AppDirectory -ne $BuiltDirectory) { throw 'PyInstaller 출력 폴더 이름은 my-video-manager여야 합니다.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $AppDirectory 'my-video-manager.exe'))) {
    throw '실행 폴더에 my-video-manager.exe가 없습니다.'
}
& $Python scripts/check_bundle.py $AppDirectory
Confirm-Exit 'Bundle contents'
# 기존 실행 폴더는 빌드 당시 지문을 보존하며 현재 환경으로 다시 계산하지 않는다.
& $Python scripts/bundle_fingerprint.py --check $AppDirectory
Confirm-Exit 'Runtime fingerprint'
# 4. Inno Setup. 버전 원본은 pyproject.toml 하나다.
& $InnoCompiler "/DAppVersion=$Version" "/DAppDirectory=$AppDirectory" "/DInstallerOutput=$OutputDirectory" installer/my-video-manager.iss
Confirm-Exit 'Inno Setup'
Write-Host "Created: $OutputDirectory/MyVideoManager-Setup-$Version.exe"
