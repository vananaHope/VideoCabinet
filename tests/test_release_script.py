"""발행 없이 임시 Git 저장소와 가짜 gh/build로 Release의 공개 CLI를 검증한다."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell 필요")


def git(repository, *arguments):
    return subprocess.run(["git", "-C", str(repository), *arguments], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def repository(request):
    # Git의 receive-pack/PowerShell 5.1은 긴 pytest basetemp에서 MAX_PATH에 걸린다.
    # 이 통합 테스트의 저장소만 짧고 독립적인 OS 임시 경로에 둔다.
    temporary = tempfile.TemporaryDirectory(prefix='mvm-rel-')
    request.addfinalizer(temporary.cleanup)
    tmp_path = Path(temporary.name)
    repo = tmp_path / "release repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "릴리스 검사")
    git(repo, "config", "user.email", "release-test@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.longpaths", "true")
    git(repo, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (repo / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/release.ps1", repo / "scripts/release.ps1")
    (repo / "pyproject.toml").write_text('[project]\nname = "test"\nversion = "0.1.0"\n', encoding="utf-8")
    (repo / ".gitignore").write_text("dist/\n", encoding="utf-8")
    (repo / "scripts/build.ps1").write_text(r'''param([string]$Version)
if (-not $Version) {
    $Version = [regex]::Match([IO.File]::ReadAllText((Join-Path (Get-Location) 'pyproject.toml')), 'version = "([^"\r\n]+)"').Groups[1].Value
}
if ($env:RELEASE_TEST_DIRTY_BUILD -eq '1') {
    [IO.File]::WriteAllText((Join-Path (Get-Location) 'build-change.txt'), 'preserve me')
}
if ($env:RELEASE_TEST_HEAD_BUILD -eq '1') {
    git commit --allow-empty -m '빌드 중 사용자 작업'
    throw 'HEAD 변경 뒤 빌드 실패'
}
if ($env:RELEASE_TEST_BUILD_FAIL -eq '1') { throw '가짜 빌드 실패' }
New-Item -ItemType Directory -Force dist/installer | Out-Null
[IO.File]::WriteAllText((Join-Path (Get-Location) "dist/installer/MyVideoManager-Setup-$Version.exe"), $Version)
$global:LASTEXITCODE = 0
''', encoding="utf-8-sig")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "첫 구현")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "--bare", str(repo), str(remote)], check=True, capture_output=True)
    git(remote, "config", "core.longpaths", "true")
    url = "https://github.com/release-tests/my-video-manager.git"
    git(repo, "remote", "add", "origin", url)
    # 원격 읽기와 실패 복구 시험의 push 모두 임시 bare 저장소로만 보낸다.
    git(repo, "config", f"url.{remote.as_posix()}.insteadOf", url)
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo, remote


def run_release(repository, *, build=False, status="404", build_fail=False, dry_run=True, dirty_build=False,
                head_build=False, redirect=False):
    repo, _ = repository
    env = {**os.environ, "RELEASE_TEST_SCRIPT": str(repo / "scripts/release.ps1"),
           "RELEASE_TEST_STATUS": status, "RELEASE_TEST_BUILD": str(int(build)),
           "RELEASE_TEST_BUILD_FAIL": str(int(build_fail)),
           "RELEASE_TEST_DRY_RUN": str(int(dry_run)),
           "RELEASE_TEST_DIRTY_BUILD": str(int(dirty_build)),
           "RELEASE_TEST_HEAD_BUILD": str(int(head_build)), "RELEASE_TEST_REDIRECT": str(int(redirect))}
    # Python을 거쳐 상속된 PowerShell 7 모듈 경로로 5.1 기본 모듈이 가려지지 않게 한다.
    env = {key: value for key, value in env.items() if key.lower() != "psmodulepath"}
    # 함수가 실제 gh를 가린다. 발행 명령이 오면 즉시 실패하며 네트워크는 사용하지 않는다.
    harness = '''
$ErrorActionPreference = 'Stop'
# 한국어 Windows PowerShell 5.1 기본 콘솔을 재현한다. UTF-8 보정은 제품 책임이다.
[Console]::OutputEncoding = [Text.Encoding]::GetEncoding(949)
function global:gh {
    if ($args[0] -eq 'release' -and $args[1] -eq 'create') {
        throw '가짜 Release 실패'
    }
    if ($args[0] -ne 'api') { throw '금지된 gh 명령' }
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
    if ($env:RELEASE_TEST_REDIRECT -eq '1') {
        & $env:RELEASE_TEST_SCRIPT -Version '0.2.0' -DryRun:($env:RELEASE_TEST_DRY_RUN -eq '1') -Build:($env:RELEASE_TEST_BUILD -eq '1') *>&1 | ForEach-Object { Write-Output $_ }
    } else {
        & $env:RELEASE_TEST_SCRIPT -Version '0.2.0' -DryRun:($env:RELEASE_TEST_DRY_RUN -eq '1') -Build:($env:RELEASE_TEST_BUILD -eq '1')
    }
    $ResultCode = 0
} catch { Write-Output $_; $ResultCode = 1 }
Write-Output "RESTORED_ENCODING=$([Console]::OutputEncoding.CodePage)"
Write-Output "POWERSHELL_MAJOR=$($PSVersionTable.PSVersion.Major)"
exit $ResultCode
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
    assert "RESTORED_ENCODING=949" in result.stdout
    if os.name == "nt":
        assert "POWERSHELL_MAJOR=5" in result.stdout
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


def reject_push(remote):
    hooks = remote / "hooks"
    git(remote, "config", "core.hooksPath", hooks.as_posix())
    hook = hooks / "pre-receive"
    hook.write_text("#!/bin/sh\necho TEST_PUSH_REJECTED >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


def test_build_throw_restores_local_version_commit(repository):
    before = snapshot(repository)
    result = run_release(repository, dry_run=False, build_fail=True)
    assert result.returncode != 0
    assert snapshot(repository) == before
    assert git(repository[0], "status", "--porcelain") == ""
    assert "로컬 버전 커밋과 이번 태그를 복구했습니다" in result.stdout
    assert "RESTORED_ENCODING=949" in result.stdout


def test_rejected_push_restores_commit_tag_and_preserves_korean_notes(repository):
    repo, remote = repository
    reject_push(remote)
    before = snapshot(repository)
    result = run_release(repository, dry_run=False)
    assert result.returncode != 0
    assert "TEST_PUSH_REJECTED" in result.stderr + result.stdout
    assert snapshot(repository) == before
    assert git(repo, "status", "--porcelain") == ""
    notes = repo / "dist/installer/release-notes-0.2.0.md"
    assert notes.read_text(encoding="utf-8") == "- 첫 구현\n- 버전 0.2.0 릴리스 준비"
    assert "RESTORED_ENCODING=949" in result.stdout
    if os.name == "nt":
        assert "POWERSHELL_MAJOR=5" in result.stdout


def test_build_changes_are_preserved_with_exact_recovery_commands(repository):
    repo, remote = repository
    before = snapshot(repository)
    result = run_release(repository, dry_run=False, dirty_build=True)
    assert result.returncode != 0
    assert (repo / "build-change.txt").read_text() == "preserve me"
    assert git(repo, "rev-parse", "HEAD") != before[0]
    assert git(remote, "show-ref") == before[3]
    assert "git stash push --include-untracked" in result.stdout
    assert f"git log --oneline {before[0]}..HEAD" in result.stdout
    assert 'git revert' in result.stdout
    assert f"git reset --keep {before[0]}" not in result.stdout


def test_release_failure_preserves_pushed_refs_and_prints_manual_completion(repository):
    repo, remote = repository
    result = run_release(repository, dry_run=False)
    assert result.returncode != 0
    head = git(repo, "rev-parse", "HEAD")
    assert git(remote, "rev-parse", "main") == head
    assert git(remote, "rev-parse", "v0.2.0^{}") == head
    assert git(repo, "rev-parse", "v0.2.0^{}") == head
    assert "git ls-remote origin refs/heads/main refs/tags/v0.2.0" in result.stdout
    assert "gh release view v0.2.0 --repo github.com/release-tests/my-video-manager" in result.stdout
    assert "gh release create v0.2.0" in result.stdout
    assert "--notes-file" in result.stdout
    assert "gh release upload v0.2.0" in result.stdout
    assert git(repo, "status", "--porcelain") == ""


def test_head_change_preserves_user_commit_and_never_suggests_reset(repository):
    repo, remote = repository
    before = snapshot(repository)
    result = run_release(repository, dry_run=False, head_build=True)
    assert result.returncode != 0
    assert git(repo, 'log', '-1', '--format=%s') == '빌드 중 사용자 작업'
    assert git(repo, 'rev-list', '--count', f'{before[0]}..HEAD') == '2'
    assert git(remote, 'show-ref') == before[3]
    assert 'git revert' in result.stdout
    assert 'git reset --keep' not in result.stdout


def test_redirected_git_stderr_warning_does_not_leave_index_lock(repository):
    repo, _ = repository
    git(repo, 'config', 'core.autocrlf', 'true')
    before = snapshot(repository)
    result = run_release(repository, dry_run=False, build_fail=True, redirect=True)
    assert result.returncode != 0
    assert snapshot(repository) == before
    assert not (repo / '.git/index.lock').exists()
