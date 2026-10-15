"""발행 없이 임시 Git 저장소와 가짜 gh/build로 Release의 공개 CLI를 검증한다."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell 필요")


def git(repository, *arguments):
    return subprocess.run(["git", "-C", str(repository), *arguments], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "release repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "릴리스 검사")
    git(repo, "config", "user.email", "release-test@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (repo / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/release.ps1", repo / "scripts/release.ps1")
    (repo / "pyproject.toml").write_text('[project]\nname = "test"\nversion = "0.1.0"\n', encoding="utf-8")
    (repo / ".gitignore").write_text("dist/\n", encoding="utf-8")
    (repo / "scripts/build.ps1").write_text('''param([string]$Version)
if (-not $Version) { throw '버전 인자 누락' }
if ($env:RELEASE_TEST_BUILD_FAIL -eq '1') { throw '가짜 빌드 실패' }
New-Item -ItemType Directory -Force dist/installer | Out-Null
[IO.File]::WriteAllText((Join-Path (Get-Location) "dist/installer/MyVideoManager-Setup-$Version.exe"), $Version)
$global:LASTEXITCODE = 0
''', encoding="utf-8-sig")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "첫 구현")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "--bare", str(repo), str(remote)], check=True, capture_output=True)
    url = "https://github.com/release-tests/my-video-manager.git"
    git(repo, "remote", "add", "origin", url)
    # 원격 읽기는 실제 GitHub 대신 이 테스트의 bare 저장소로만 보낸다.
    git(repo, "config", f"url.{remote.as_posix()}.insteadOf", url)
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo, remote


def run_release(repository, *, build=False, status="404", build_fail=False):
    repo, _ = repository
    env = {**os.environ, "RELEASE_TEST_SCRIPT": str(repo / "scripts/release.ps1"),
           "RELEASE_TEST_STATUS": status, "RELEASE_TEST_BUILD": str(int(build)),
           "RELEASE_TEST_BUILD_FAIL": str(int(build_fail))}
    # 함수가 실제 gh를 가린다. 발행 명령이 오면 즉시 실패하며 네트워크는 사용하지 않는다.
    harness = '''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
function global:gh {
    if ($args[0] -ne 'api') { throw '금지된 gh 발행 명령' }
    if ($args[1] -notlike 'repos/release-tests/my-video-manager*') { throw 'origin과 다른 저장소' }
    if ($args[1] -notmatch '/releases/') {
        $global:LASTEXITCODE = 0
        return
    }
    if ($env:RELEASE_TEST_STATUS -eq '200') {
        Write-Output 'HTTP/2.0 200 OK'
        $global:LASTEXITCODE = 0
    } else {
        Write-Output "HTTP/2.0 $env:RELEASE_TEST_STATUS Error"
        $global:LASTEXITCODE = 1
    }
}
try {
    & $env:RELEASE_TEST_SCRIPT -Version '0.2.0' -DryRun -Build:($env:RELEASE_TEST_BUILD -eq '1')
    exit 0
} catch { Write-Output $_; exit 1 }
'''
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", harness],
                          env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)


def snapshot(repository):
    repo, remote = repository
    return (git(repo, "rev-parse", "HEAD"), git(repo, "show-ref"),
            (repo / "pyproject.toml").read_bytes(), git(remote, "show-ref"))


@pytest.mark.parametrize("build", [False, True])
def test_dry_run_does_not_change_version_commits_refs_or_remote(repository, build):
    before = snapshot(repository)
    result = run_release(repository, build=build)
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(repository) == before
    repo, _ = repository
    assert git(repo, "status", "--porcelain") == ""
    assert "첫 구현" in result.stdout
    assert "0.1.0 -> 0.2.0" in result.stdout
    installer = repo / "dist/installer/MyVideoManager-Setup-0.2.0.exe"
    assert installer.exists() == build
    if build:
        assert installer.read_text() == "0.2.0"


@pytest.mark.parametrize("state", ["dirty", "untracked", "ahead", "behind", "remote_advanced", "branch", "local_tag", "remote_tag"])
def test_preflight_rejects_unsafe_repository_without_mutating_it(repository, state):
    repo, remote = repository
    initial = git(repo, "rev-parse", "HEAD")
    if state == "dirty":
        (repo / "pyproject.toml").write_text('changed', encoding="utf-8")
    elif state == "untracked":
        (repo / "untracked.txt").touch()
    elif state == "branch":
        git(repo, "checkout", "-b", "feature")
    elif state == "local_tag":
        git(repo, "update-ref", "refs/tags/v0.2.0", initial)
    elif state == "remote_tag":
        git(remote, "update-ref", "refs/tags/v0.2.0", initial)
    else:
        git(repo, "commit", "--allow-empty", "-m", "다음 변경")
        advanced = git(repo, "rev-parse", "HEAD")
        if state in ("behind", "remote_advanced"):
            # 로컬 객체를 공유하는 임시 bare 저장소를 다시 만들어 push 없이 원격 전진을 흉내 낸다.
            git(remote, "fetch", str(repo), "main")
            git(remote, "update-ref", "refs/heads/main", advanced)
            git(repo, "reset", "--hard", initial)
            if state == "behind":
                git(repo, "update-ref", "refs/remotes/origin/main", advanced)
    before = snapshot(repository)
    result = run_release(repository)
    assert result.returncode != 0, result.stdout
    assert snapshot(repository) == before
    assert not (repo / "dist").exists()


@pytest.mark.parametrize("status", ["200", "403", "500"])
def test_existing_release_or_inconclusive_lookup_stops(repository, status):
    before = snapshot(repository)
    result = run_release(repository, status=status)
    assert result.returncode != 0
    assert snapshot(repository) == before
    assert git(repository[0], "status", "--porcelain") == ""


def test_dry_run_build_failure_does_not_commit_or_publish(repository):
    before = snapshot(repository)
    result = run_release(repository, build=True, build_fail=True)
    assert result.returncode != 0
    assert snapshot(repository) == before
    assert git(repository[0], "status", "--porcelain") == ""


def test_notes_start_after_previous_version_tag(repository):
    repo, remote = repository
    git(repo, "update-ref", "refs/tags/v0.1.0", "HEAD")
    git(repo, "commit", "--allow-empty", "-m", "후속 수정")
    advanced = git(repo, "rev-parse", "HEAD")
    git(remote, "fetch", str(repo), "main")
    git(remote, "update-ref", "refs/heads/main", advanced)
    git(repo, "update-ref", "refs/remotes/origin/main", advanced)
    before = snapshot(repository)
    result = run_release(repository)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "후속 수정" in result.stdout
    assert "첫 구현" not in result.stdout
    assert snapshot(repository) == before
