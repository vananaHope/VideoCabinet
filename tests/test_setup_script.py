"""실제 PowerShell 분기에서 외부 명령만 대체해 전체/빠른 모드 계약을 확인한다."""

import json
from pathlib import Path
import shutil
import subprocess

from wait_helpers import CHILD_READY_TIMEOUT

import pytest


POWERSHELL = shutil.which("powershell")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell 필요")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/setup.ps1"


def run_setup(tmp_path, *, fast=True, missing="", uv_install="present"):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "frontend").mkdir()
    shutil.copyfile(SCRIPT, tmp_path / "scripts/setup.ps1")
    harness = tmp_path / "run.ps1"
    harness.write_text(r'''
$ErrorActionPreference = 'Stop'
$global:Calls = [System.Collections.Generic.List[string]]::new()
$global:UvAvailable = 'UV_INSTALL' -eq 'present'
function global:Get-Command {
    param([string]$Name, $ErrorAction)
    if ($Name -eq 'uv' -and -not $global:UvAvailable) { return $null }
    if ($Name -eq '7z' -and 'MISSING_TOOL' -eq '7z') { return $null }
    Microsoft.PowerShell.Core\Get-Command $Name -ErrorAction SilentlyContinue
}
function global:Test-Path {
    param([string]$Path)
    if ($Path -like '*7-Zip/7z.exe' -and 'MISSING_TOOL' -eq '7z') { return $false }
    Microsoft.PowerShell.Management\Test-Path $Path
}
function global:python {
    $global:Calls.Add("python $args")
    $global:LASTEXITCODE = 0
    if ($args -contains 'import sys; print(sys.executable)') { 'python.exe' }
}
function global:node { $global:Calls.Add("node $args"); $global:LASTEXITCODE = 0 }
function global:uv {
    $global:Calls.Add("uv $args")
    $global:LASTEXITCODE = if ('UV_INSTALL' -eq 'broken') { 9 } else { 0 }
}
function global:npm { $global:Calls.Add("npm $args"); $global:LASTEXITCODE = 0 }
function global:ffmpeg {}
function global:7z {}
function global:winget {
    $global:Calls.Add("winget $args")
    if ($args -notcontains 'astral-sh.uv' -or 'UV_INSTALL' -eq 'present') {
        throw '요청하지 않은 도구 설치'
    }
    $global:UvAvailable = 'UV_INSTALL' -ne 'missing'
    $global:LASTEXITCODE = 17 # 이미 설치됨 등 비영 종료라도 실제 실행 파일로 판정
}
function global:.venv/Scripts/python.exe {
    $global:Calls.Add("venv $args")
    $global:LASTEXITCODE = 0
    if ('MISSING_TOOL' -eq 'ffmpeg' -and "$args" -match 'FFmpegMediaReader') {
        $global:LASTEXITCODE = 1
    }
}
try {
    & "$PSScriptRoot/scripts/setup.ps1" -Worktree:FAST_FLAG
} catch {
    $_.Exception.Message | Set-Content -Encoding UTF8 "$PSScriptRoot/error.txt"
    exit 1
} finally {
    $global:Calls | ConvertTo-Json | Set-Content -Encoding UTF8 "$PSScriptRoot/calls.json"
}
'''.replace("FAST_FLAG", "$true" if fast else "$false")
       .replace("MISSING_TOOL", missing).replace("UV_INSTALL", uv_install), encoding="utf-8-sig")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                            capture_output=True, timeout=CHILD_READY_TIMEOUT)
    calls = json.loads((tmp_path / "calls.json").read_text(encoding="utf-8-sig"))
    error = tmp_path / "error.txt"
    return result, calls, error.read_text(encoding="utf-8-sig") if error.exists() else ""


@pytest.mark.parametrize("fast", [False, True])
def test_setup_keeps_required_steps_and_skips_only_optional_checks(tmp_path, fast):
    result, calls, error = run_setup(tmp_path, fast=fast)
    assert result.returncode == 0, (error, result.stdout, result.stderr)
    assert "uv --version" in calls
    assert "uv venv --python python.exe .venv" in calls
    assert "uv pip install --python .venv/Scripts/python.exe --link-mode hardlink -e .[dev,cuda]" in calls
    for step in ("npm ci", "npm run build", "venv scripts/generate_web_types.py --check",
                 "venv scripts/install_libmpv.py"):
        assert step in calls
    assert any("QtWebEngineWidgets, QtWebChannel" in call for call in calls)
    assert any("FFmpegMediaReader" in call for call in calls)
    assert any("get_supported_compute_types('cuda')" in call for call in calls)
    for step in ("npm run lint", "npm run typecheck"):
        assert (step in calls) is not fast
    assert any(call.startswith("venv -m pytest") for call in calls) is not fast


@pytest.mark.parametrize("missing,message", [("7z", "7-Zip이 없습니다"), ("ffmpeg", "FFmpeg/ffprobe 확인에 실패")])
def test_fast_mode_missing_tools_fails_with_full_setup_guidance(tmp_path, missing, message):
    result, calls, error = run_setup(tmp_path, missing=missing)
    assert result.returncode != 0
    assert message in error and "-Worktree 없이" in error
    assert not any(call.startswith("winget ") for call in calls)
    assert not any("get_supported_compute_types" in call for call in calls)
    assert ("venv scripts/install_libmpv.py" in calls) is (missing == "ffmpeg")


@pytest.mark.parametrize("uv_install", ["installed", "missing", "broken"])
def test_uv_install_uses_executable_instead_of_winget_exit_code(tmp_path, uv_install):
    result, calls, error = run_setup(tmp_path, uv_install=uv_install)
    assert sum(call.startswith("winget install --id astral-sh.uv") for call in calls) == 1
    assert (result.returncode == 0) is (uv_install == "installed"), error
    assert ("uv --version" in calls) is (uv_install != "missing")
    if uv_install == "missing":
        assert "uv를 찾을 수 없습니다" in error
    if uv_install == "broken":
        assert "uv check failed" in error
    assert any(call.startswith("uv pip install") for call in calls) is (uv_install == "installed")
