# 전체 pytest를 병렬로 실행한다. release.ps1이 버전 커밋 전에 부르며, 단독으로 실행해도 된다.
# 추가 인자는 pytest에 그대로 넘긴다(예: -x, -n 2).
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$Python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'scripts/setup.ps1로 Python 환경을 먼저 준비하세요.' }
# Windows PowerShell 5.1은 출력이 재지정되면 pytest의 stderr 경고도 오류로 만들므로 종료 코드로만 판정한다.
$ErrorActionPreference = 'Continue'
& $Python -m pytest -n auto -q @args
exit $LASTEXITCODE
