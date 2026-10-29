"""발행 없이 임시 Git 저장소와 가짜 gh/build로 Release의 공개 CLI를 검증한다."""

import os
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys

from wait_helpers import CHILD_READY_TIMEOUT

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from my_video_manager.app_version import DISPLAY_NAME, RELEASE_REPOSITORY
from my_video_manager.runtime_fingerprint import NATIVE_FILES, make_runtime_fingerprint
from my_video_manager.update_manifest import verify_manifest


ROOT = Path(__file__).parents[1]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell 필요")


def git(repository, *arguments):
    return subprocess.run(["git", "-C", str(repository), *arguments], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def repository(request, monkeypatch):
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
    (repo / ".gitignore").write_text("dist/\n.venv/\n", encoding="utf-8")
    python = repo / '.venv/Scripts/python.exe'
    python.parent.mkdir(parents=True)
    shutil.copyfile(sys.executable, python)
    shutil.copyfile(Path(sys.prefix) / 'pyvenv.cfg', repo / '.venv/pyvenv.cfg')
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join((str(ROOT / 'src'), str(Path(sys.prefix) / 'Lib/site-packages'))))
    monkeypatch.setenv('RELEASE_TEST_SOURCE_SCRIPTS', str(ROOT / 'scripts'))
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    keytool = importlib.import_module('generate_update_key')
    key_path = tmp_path / 'keys/test.pem'
    public = keytool.generate_key(key_path, None)
    monkeypatch.setenv('RELEASE_TEST_KEY', str(key_path))
    monkeypatch.setenv('RELEASE_TEST_PUBLIC', public.hex())
    runtime = make_runtime_fingerprint(
        dependencies={'cryptography': '50.0.2'},
        python={'implementation': 'CPython', 'version': '3.10.6', 'platform': 'win32', 'machine': 'AMD64'},
        tools={'pyinstaller': '6.16.0', 'pyinstaller-hooks-contrib': '2026.8'},
        native_files={name: hashlib.sha256(name.encode()).hexdigest() for name in NATIVE_FILES},
        hooks={'hook.py': 'b' * 64}, bundle_files=list(NATIVE_FILES))
    synthetic = repo / 'scripts/synthetic-bundle'
    synthetic.mkdir()
    (synthetic / 'runtime-fingerprint.json').write_text(json.dumps(runtime))
    for name in NATIVE_FILES:
        target = synthetic / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
    # The real helper runs behind a fixture transport and an explicit in-process test pin.
    # No product test bypass or real GitHub command is available in this harness.
    (repo / 'scripts/release_metadata.py').write_text('''
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.environ['RELEASE_TEST_SOURCE_SCRIPTS'])
import release_metadata as tool
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from my_video_manager import update_manifest
update_manifest.UPDATE_PUBLIC_KEY = bytes.fromhex(os.environ['RELEASE_TEST_PUBLIC'])
original = tool.previous_release
def previous_release(repository, version):
    assert repository == os.environ['RELEASE_TEST_RELEASE_REPOSITORY'], repository
    return original(repository, version, api=api)
def api(endpoint, **kwargs):
    kind = os.environ.get('RELEASE_TEST_PREVIOUS', 'first')
    if endpoint.endswith('/latest'):
        assets = [] if kind == 'first' else [{'name': 'update-manifest.json', 'id': 1}]
        if kind not in ('first', 'unsigned'):
            assets.append({'name': 'update-manifest.json.sig', 'id': 2})
        return json.dumps({'tag_name': 'v0.1.0', 'draft': False, 'prerelease': False, 'assets': assets}).encode()
    runtime = json.loads(Path('scripts/synthetic-bundle/runtime-fingerprint.json').read_text())
    fingerprint = runtime['fingerprint'] if kind in ('same', 'unsigned', 'bad-signature') else 'c' * 64
    data = json.dumps({'schema_version': 1, 'version': '0.1.0', 'runtime_fingerprint': fingerprint,
        'previous_runtime_fingerprint': None, 'patch': None, 'patch_available': False,
        'full': {'filename': 'old.exe', 'size': 10, 'sha256': 'a' * 64}}).encode()
    if endpoint.endswith('/2'):
        if kind == 'bad-signature':
            return b'x' * 64
        key = load_pem_private_key(Path(os.environ['RELEASE_TEST_PREVIOUS_KEY']).read_bytes(), password=None)
        return key.sign(data)
    return data
tool.previous_release = previous_release
raise SystemExit(tool.main())
''', encoding='utf-8')
    (repo / "scripts/build.ps1").write_text(r'''param([string]$Version, [switch]$SkipPyInstaller, [switch]$PatchOnly)
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
if ($env:MVM_UPDATE_SIGNING_PASSWORD) { throw '빌드에 암호가 유출됨' }
New-Item -ItemType Directory -Force dist/installer | Out-Null
if ($PatchOnly) {
    [IO.File]::WriteAllText((Join-Path (Get-Location) "dist/installer/MyVideoManager-Patch-$Version.exe"), "patch $Version")
} else {
    [IO.File]::WriteAllText((Join-Path (Get-Location) "dist/installer/MyVideoManager-Setup-$Version.exe"), $Version)
    Copy-Item -Recurse -Force scripts/synthetic-bundle dist/my-video-manager
}
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
                head_build=False, redirect=False, previous='first', key_state='matching', publish=False,
                version='0.2.0'):
    repo, _ = repository
    env = {**os.environ, "RELEASE_TEST_SCRIPT": str(repo / "scripts/release.ps1"),
           "RELEASE_TEST_STATUS": status, "RELEASE_TEST_BUILD": str(int(build)),
           "RELEASE_TEST_BUILD_FAIL": str(int(build_fail)),
           "RELEASE_TEST_DRY_RUN": str(int(dry_run)),
           "RELEASE_TEST_DIRTY_BUILD": str(int(dirty_build)),
           "RELEASE_TEST_HEAD_BUILD": str(int(head_build)), "RELEASE_TEST_REDIRECT": str(int(redirect)),
           'RELEASE_TEST_PREVIOUS': previous, 'RELEASE_TEST_PUBLISH': str(int(publish)),
           'RELEASE_TEST_VERSION': version, 'RELEASE_TEST_RELEASE_REPOSITORY': RELEASE_REPOSITORY}
    env['RELEASE_TEST_PREVIOUS_KEY'] = env['RELEASE_TEST_KEY']
    if key_state == 'missing':
        env['RELEASE_TEST_KEY'] += '.missing'
    elif key_state == 'placeholder':
        env['RELEASE_TEST_PUBLIC'] = ''
    elif key_state == 'mismatch':
        env['RELEASE_TEST_PUBLIC'] = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    # Python을 거쳐 상속된 PowerShell 7 모듈 경로로 5.1 기본 모듈이 가려지지 않게 한다.
    env = {key: value for key, value in env.items() if key.lower() != "psmodulepath"}
    # 함수가 실제 gh를 가린다. 발행 명령이 오면 즉시 실패하며 네트워크는 사용하지 않는다.
    harness = '''
$ErrorActionPreference = 'Stop'
# 한국어 Windows PowerShell 5.1 기본 콘솔을 재현한다. UTF-8 보정은 제품 책임이다.
[Console]::OutputEncoding = [Text.Encoding]::GetEncoding(949)
function global:gh {
    if ($env:MVM_UPDATE_SIGNING_PASSWORD -and $env:RELEASE_TEST_DRY_RUN -ne '1') { throw 'gh에 암호가 유출됨' }
    if ($args[0] -eq 'release' -and $args[1] -eq 'create') {
        [IO.File]::WriteAllText((Join-Path (Get-Location) 'dist/upload-arguments.json'), (ConvertTo-Json @($args)))
        if ($env:RELEASE_TEST_PUBLISH -eq '1') { $global:LASTEXITCODE = 0; return }
        throw '가짜 Release 실패'
    }
    if ($args[0] -ne 'api') { throw '금지된 gh 명령' }
    # Release 조회는 -ReleaseRepository 기본값인 배포 저장소로만 가고 소스 origin은 쓰지 않는다.
    if ($args[1] -notmatch "^repos/$([regex]::Escape($env:RELEASE_TEST_RELEASE_REPOSITORY))(/|$)") { throw '배포 저장소가 아닌 저장소' }
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
        & $env:RELEASE_TEST_SCRIPT -Version $env:RELEASE_TEST_VERSION -PrivateKey $env:RELEASE_TEST_KEY -DryRun:($env:RELEASE_TEST_DRY_RUN -eq '1') -Build:($env:RELEASE_TEST_BUILD -eq '1') *>&1 | ForEach-Object { Write-Output $_ }
    } else {
        & $env:RELEASE_TEST_SCRIPT -Version $env:RELEASE_TEST_VERSION -PrivateKey $env:RELEASE_TEST_KEY -DryRun:($env:RELEASE_TEST_DRY_RUN -eq '1') -Build:($env:RELEASE_TEST_BUILD -eq '1')
    }
    $ResultCode = 0
} catch { Write-Output $_; $ResultCode = 1 }
Write-Output "RESTORED_ENCODING=$([Console]::OutputEncoding.CodePage)"
Write-Output "POWERSHELL_MAJOR=$($PSVersionTable.PSVersion.Major)"
Write-Output "PASSWORD_ENV_CLEARED=$(-not (Test-Path Env:MVM_UPDATE_SIGNING_PASSWORD))"
exit $ResultCode
'''
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", harness],
                          env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CHILD_READY_TIMEOUT)


def snapshot(repository):
    repo, remote = repository
    return (git(repo, "rev-parse", "HEAD"), git(repo, "show-ref"),
            (repo / "pyproject.toml").read_bytes(), git(remote, "show-ref"))


def test_release_repository_default_matches_app_constant():
    script = (ROOT / 'scripts/release.ps1').read_text(encoding='utf-8-sig')
    assert f"[string]$ReleaseRepository = '{RELEASE_REPOSITORY}'" in script
    assert RELEASE_REPOSITORY == 'vananaHope/my-video-manager-releases'


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
    assert notes.read_text(encoding="utf-8").endswith("- 첫 구현\n- 버전 0.2.0 릴리스 준비")
    assert '전체 설치 파일로 한 번 설치해야' in notes.read_text(encoding='utf-8')
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
    assert f"gh release view v0.2.0 --repo github.com/{RELEASE_REPOSITORY}" in result.stdout
    # 경고는 콘솔 폭에서 줄바꿈될 수 있어 공백을 합친 뒤 비교한다.
    create = " ".join(result.stdout.split("gh release create v0.2.0", 1)[1].split("--notes-file", 1)[0].split())
    assert f"--repo github.com/{RELEASE_REPOSITORY} --target main" in create
    assert "--verify-tag" not in result.stdout
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


@pytest.mark.parametrize('previous', ['first', 'same', 'changed', 'unsigned', 'bad-signature'])
@pytest.mark.parametrize('build', [False, True])
def test_dry_run_asset_plan_and_conditional_patch(repository, previous, build):
    repo, _ = repository
    if not build:
        shutil.copytree(repo / 'scripts/synthetic-bundle', repo / 'dist/my-video-manager')
    before = snapshot(repository)
    result = run_release(repository, previous=previous, build=build, key_state='missing')
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(repository) == before
    assert '패치 가능: ' + ('True' if previous == 'same' else 'False') in result.stdout
    assert '실제 발행 시 서명 키 필요' in result.stdout
    for name in ('MyVideoManager-Setup-0.2.0.exe', 'update-manifest.json', 'update-manifest.json.sig'):
        assert name in result.stdout
    fingerprint = json.loads((repo / 'scripts/synthetic-bundle/runtime-fingerprint.json').read_text())['fingerprint']
    assert f'새 지문: {fingerprint}' in result.stdout
    if previous == 'same':
        assert f'이전 지문: {fingerprint}' in result.stdout
        assert '패치 생성·업로드 제외' not in result.stdout
    else:
        assert '패치 생성·업로드 제외' in result.stdout
        assert '전체 설치 파일로 한 번 설치해야' in result.stdout
    assert (repo / 'dist/installer/MyVideoManager-Patch-0.2.0.exe').exists() == (build and previous == 'same')
    assert not (repo / 'dist/installer/0.2.0/update-manifest.json').exists()
    assert not (repo / 'dist/upload-arguments.json').exists()


@pytest.mark.parametrize('state,reason', [
    ('missing', 'No such file'), ('placeholder', '앱 공개 키가 설정되지'), ('mismatch', '서명 키가 앱 공개 키와 다릅니다'),
])
def test_invalid_signing_key_stops_before_commit_build_or_publish(repository, state, reason):
    before = snapshot(repository)
    result = run_release(repository, dry_run=False, key_state=state)
    assert result.returncode != 0
    assert reason in result.stdout + result.stderr
    assert snapshot(repository) == before
    assert not (repository[0] / 'dist').exists()


@pytest.mark.parametrize('previous', ['first', 'same', 'changed', 'unsigned', 'bad-signature'])
def test_publication_uploads_only_eligible_assets_with_verified_manifest(repository, previous):
    repo, _ = repository
    # A leftover patch must never be picked up by a glob on a changed runtime release.
    installer = repo / 'dist/installer'
    installer.mkdir(parents=True)
    patch = installer / 'MyVideoManager-Patch-0.2.0.exe'
    patch.write_bytes(b'stale patch')
    result = run_release(repository, dry_run=False, previous=previous, publish=True)
    assert result.returncode == 0, result.stdout + result.stderr
    output = installer / '0.2.0/update-manifest.json'
    manifest = verify_manifest(output.read_bytes(), output.with_suffix('.json.sig').read_bytes(),
                               public_key=bytes.fromhex(os.environ['RELEASE_TEST_PUBLIC']))
    assert manifest.version == '0.2.0'
    assert manifest.patch_available == (previous == 'same')
    assert (manifest.patch is not None) == (previous == 'same')
    if previous in ('unsigned', 'bad-signature'):
        assert manifest.previous_runtime_fingerprint is None
        assert ('서명 없음' if previous == 'unsigned' else '검증 실패') in result.stdout
    arguments = json.loads((repo / 'dist/upload-arguments.json').read_text(encoding='utf-8-sig'))
    assets = {Path(arg).name for arg in arguments[3:arguments.index('--repo')]}
    expected = {'MyVideoManager-Setup-0.2.0.exe', 'MyVideoManager-Setup-0.2.0.exe.sha256',
                'update-manifest.json', 'update-manifest.json.sig'}
    if previous == 'same':
        expected.add(patch.name)
    else:
        assert patch.read_bytes() == b'stale patch'
    assert assets == expected
    # 소스 origin에는 커밋과 태그만, Release는 소스 태그 없이 배포 저장소 main에 만든다.
    _, remote = repository
    head = git(repo, 'rev-parse', 'HEAD')
    assert git(remote, 'rev-parse', 'main') == head
    assert git(remote, 'rev-parse', 'v0.2.0^{}') == head
    options = arguments[arguments.index('--repo'):]
    assert options[:4] == ['--repo', f'github.com/{RELEASE_REPOSITORY}', '--target', 'main']
    assert '--verify-tag' not in arguments


def test_patch_assets_are_in_failure_recovery_instructions(repository):
    result = run_release(repository, dry_run=False, previous='same')
    assert result.returncode != 0
    upload = result.stdout.split('gh release upload v0.2.0', 1)[1]
    for name in ('MyVideoManager-Patch-0.2.0.exe', 'update-manifest.json', 'update-manifest.json.sig'):
        assert name in upload


@pytest.mark.parametrize('previous', ['first', 'same', 'unsigned', 'bad-signature'])
def test_dry_run_without_bundle_has_definite_fallback(repository, previous):
    before = snapshot(repository)
    result = run_release(repository, previous=previous, key_state='missing')
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(repository) == before
    assert '새 지문: 미정' in result.stdout
    if previous == 'same':
        assert '패치 가능: 미정' in result.stdout
        assert '-DryRun -Build' in result.stdout
    else:
        assert '패치 가능: False' in result.stdout
        assert '조건부:' not in result.stdout
        assert '패치 생성·업로드 제외' in result.stdout
        if previous == 'first':
            assert '첫 릴리스: 패치 없음, 전체 설치만' in result.stdout


@pytest.mark.parametrize('outcome', ['success', 'build-failure', 'wrong-password', 'missing-password'])
def test_encrypted_key_password_is_scoped_and_cleared(repository, monkeypatch, outcome):
    from cryptography.hazmat.primitives import serialization

    key_path = Path(os.environ['RELEASE_TEST_KEY'])
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    password = 'synthetic-release-secret'
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.BestAvailableEncryption(password.encode())))
    if outcome == 'missing-password':
        monkeypatch.delenv('MVM_UPDATE_SIGNING_PASSWORD', raising=False)
    else:
        monkeypatch.setenv('MVM_UPDATE_SIGNING_PASSWORD', 'wrong-secret' if outcome == 'wrong-password' else password)
    before = snapshot(repository)
    result = run_release(repository, dry_run=False, publish=True, build_fail=outcome == 'build-failure')
    assert (result.returncode == 0) == (outcome == 'success'), result.stdout + result.stderr
    assert 'PASSWORD_ENV_CLEARED=True' in result.stdout
    assert password not in result.stdout + result.stderr
    assert 'wrong-secret' not in result.stdout + result.stderr
    if outcome != 'success':
        assert snapshot(repository) == before
    else:
        output = repository[0] / 'dist/installer/0.2.0/update-manifest.json'
        assert verify_manifest(output.read_bytes(), output.with_suffix('.json.sig').read_bytes(),
                               public_key=key.public_key().public_bytes_raw()).version == '0.2.0'


@pytest.mark.parametrize('damaged', [False, True])
def test_patch_only_build_validates_bundle_and_never_rebuilds_full_installer(repository, damaged):
    repo, _ = repository
    for name in ('build.ps1', 'bundle_fingerprint.py', 'patch_payload.py', 'installer_metadata.py'):
        shutil.copyfile(ROOT / 'scripts' / name, repo / 'scripts' / name)
    # Large production bundle/license checks are replaced; fingerprint and payload checks are real.
    (repo / 'scripts/check_bundle.py').write_text('print("synthetic bundle")')
    app = repo / 'dist/my-video-manager'
    shutil.copytree(repo / 'scripts/synthetic-bundle', app)
    for name, data in {'my-video-manager.exe': 'exe', 'THIRD-PARTY-NOTICES.txt': 'license',
                       'licenses/test.txt': 'license', 'my_video_manager/build-version.txt': '0.2.0',
                       'my_video_manager/web/index.html': 'html'}.items():
        path = app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    if damaged:
        (app / NATIVE_FILES[0]).write_bytes(b'changed runtime')
    compiler = repo / 'compiler.ps1'
    compiler.write_text('''
[IO.File]::WriteAllText((Join-Path (Get-Location) 'dist/compiler-arguments.json'), (ConvertTo-Json @($args)))
$global:LASTEXITCODE = 0
''', encoding='utf-8-sig')
    full = repo / 'dist/installer/MyVideoManager-Setup-0.2.0.exe'
    full.parent.mkdir()
    full.write_bytes(b'preserve full installer')
    env = {key: value for key, value in os.environ.items() if key.lower() != 'psmodulepath'}
    result = subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(repo / 'scripts/build.ps1'), '-Version', '0.2.0', '-SkipPyInstaller',
                             '-PatchOnly', '-InnoCompiler', str(compiler)],
                            env=env, capture_output=True, timeout=CHILD_READY_TIMEOUT)
    assert (result.returncode != 0) == damaged, result.stdout + result.stderr
    assert full.read_bytes() == b'preserve full installer'
    compiled = repo / 'dist/compiler-arguments.json'
    assert compiled.exists() != damaged
    if not damaged:
        arguments = json.loads(compiled.read_text(encoding='utf-8-sig'))
        assert any(arg.startswith('/DPatchInclude=') for arg in arguments)
        # 표시 이름 include는 패치 전용 빌드에서도 Inno 컴파일 직전에 만든다.
        display_name = next(arg.split('=', 1)[1] for arg in arguments
                            if arg.startswith('/DDisplayNameInclude='))
        assert Path(display_name).read_bytes().startswith(b'\xef\xbb\xbf')
        assert DISPLAY_NAME in Path(display_name).read_text(encoding='utf-8-sig')
        assert (repo / 'build/patch-payload.iss').exists()
