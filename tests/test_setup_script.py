"""실제 PowerShell 분기에서 외부 명령만 대체해 전체/빠른 모드 계약을 확인한다."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


POWERSHELL = shutil.which("powershell")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell 필요")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/setup.ps1"


@pytest.mark.parametrize("fast", [False, True])
def test_setup_keeps_required_steps_and_skips_only_optional_checks(tmp_path, fast):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "frontend").mkdir()
    shutil.copyfile(SCRIPT, tmp_path / "scripts/setup.ps1")
    harness = tmp_path / "run.ps1"
    harness.write_text(r'''
$ErrorActionPreference = 'Stop'
$global:Calls = [System.Collections.Generic.List[string]]::new()
function global:python {
    $global:Calls.Add("python $args")
    $global:LASTEXITCODE = 0
    if ($args -contains 'import sys; print(sys.executable)') { 'python.exe' }
}
function global:node { $global:Calls.Add("node $args"); $global:LASTEXITCODE = 0 }
function global:uv { $global:Calls.Add("uv $args"); $global:LASTEXITCODE = 0 }
function global:npm { $global:Calls.Add("npm $args"); $global:LASTEXITCODE = 0 }
function global:ffmpeg {}
function global:7z {}
function global:winget { throw '이미 설치된 도구에 winget을 호출하면 안 됩니다.' }
function global:.venv/Scripts/python.exe {
    $global:Calls.Add("venv $args")
    $global:LASTEXITCODE = 0
}
& "$PSScriptRoot/scripts/setup.ps1" -Worktree:FAST_FLAG
$global:Calls | ConvertTo-Json | Set-Content -Encoding UTF8 "$PSScriptRoot/calls.json"
'''.replace("FAST_FLAG", "$true" if fast else "$false"), encoding="utf-8-sig")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, (result.stdout, result.stderr)
    calls = json.loads((tmp_path / "calls.json").read_text(encoding="utf-8-sig"))
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
