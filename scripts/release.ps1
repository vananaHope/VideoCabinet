param(
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$DryRun,
    [switch]$Build,
    [string]$PrivateKey = '',
    # 기본값은 src/my_video_manager/app_version.py의 RELEASE_REPOSITORY와 같아야 한다(테스트가 검사).
    [string]$ReleaseRepository = 'vananaHope/my-video-manager-releases'
)
# Windows PowerShell 5.1은 이 인코딩으로 git의 UTF-8 출력을 해독한다.
$OriginalOutputEncoding = [Console]::OutputEncoding
$SigningPassword = $null
try {
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
    $ErrorActionPreference = 'Stop'
    if (-not $DryRun -and $env:MVM_UPDATE_SIGNING_PASSWORD) {
        $SigningPassword = ConvertTo-SecureString $env:MVM_UPDATE_SIGNING_PASSWORD -AsPlainText -Force
        Remove-Item Env:MVM_UPDATE_SIGNING_PASSWORD
    }
    Set-Location (Join-Path $PSScriptRoot '..')

    function Get-Git([string[]]$Arguments) {
        # Windows PowerShell 5.1의 재지정된 stderr 경고는 종료 코드로 판정한다.
        $ErrorActionPreference = 'Continue'
        $Result = & git @Arguments
        if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') 실패 ($LASTEXITCODE)" }
        return ($Result -join "`n").Trim()
    }

    $Python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
    function Get-Metadata([string[]]$Arguments) {
        $ErrorActionPreference = 'Continue'
        $PasswordPointer = [IntPtr]::Zero
        try {
            if ($SigningPassword -and $Arguments[0] -in @('preflight', 'sign')) {
                $PasswordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SigningPassword)
                $env:MVM_UPDATE_SIGNING_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($PasswordPointer)
            }
            $Result = & $Python -X utf8 "$PSScriptRoot/release_metadata.py" @Arguments
            if ($LASTEXITCODE -ne 0) { throw '릴리스 메타데이터 검사에 실패했습니다. 위 원인을 확인하세요.' }
            return ($Result -join "`n" | ConvertFrom-Json)
        } finally {
            if (-not $DryRun) { Remove-Item Env:MVM_UPDATE_SIGNING_PASSWORD -ErrorAction SilentlyContinue }
            if ($PasswordPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PasswordPointer) }
        }
    }
    function Get-PatchPlan {
        $Arguments = @('plan', '--directory', $AppDirectory)
        if ($Previous.runtime_fingerprint) { $Arguments += @('--previous-fingerprint', $Previous.runtime_fingerprint) }
        if ($DryRun -and -not $Build) { $Arguments += '--allow-missing' }
        return Get-Metadata $Arguments
    }
    function Show-AssetPlan($Plan) {
        Write-Host "이전 Release: $($Previous.tag), $($Previous.reason)"
        Write-Host "이전 지문: $(if ($Previous.runtime_fingerprint) { $Previous.runtime_fingerprint } else { '없음/신뢰할 수 없음' })"
        Write-Host "새 지문: $(if ($Plan.runtime_fingerprint) { $Plan.runtime_fingerprint } else { '미정' })"
        if ($Previous.authentication -eq 'none') { Write-Host '첫 릴리스: 패치 없음, 전체 설치만' }
        Write-Host "패치 가능: $(if ($null -eq $Plan.patch_available) { '미정' } else { $Plan.patch_available }) — $($Plan.reason)"
        Write-Host '생성·업로드 자산:'
        foreach ($Asset in @($Installer, $Checksum, $Manifest, $Signature)) { Write-Host "  $Asset" }
        if ($Plan.patch_available) { Write-Host "  $PatchInstaller" }
        elseif ($null -eq $Plan.patch_available) { Write-Host "  조건부: $PatchInstaller (빌드 후 지문 일치 때만)" }
        else { Write-Host "패치 생성·업로드 제외: $PatchInstaller" }
    }

    if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
        throw '버전은 x.y.z 형식이어야 합니다.'
    }
    if ($Build -and -not $DryRun) { throw '-Build는 -DryRun과 함께만 사용합니다.' }
    if ($ReleaseRepository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw '배포 저장소는 owner/name 형식이어야 합니다.' }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'scripts/setup.ps1로 Python 환경을 먼저 준비하세요.' }
    foreach ($Tool in @('git', 'gh')) {
        if (-not (Get-Command $Tool -ErrorAction SilentlyContinue)) {
            throw "$Tool 도구가 필요합니다. Git for Windows와 GitHub CLI를 설치하고 gh auth login을 실행하세요."
        }
    }

    # 1. 읽기 전용 검사. dry-run에서는 fetch로 원격 추적 ref조차 바꾸지 않는다.
    if ((Get-Git @('symbolic-ref', '--quiet', '--short', 'HEAD')) -ne 'main') {
        throw 'main 브랜치에서만 릴리스할 수 있습니다.'
    }
    if (Get-Git @('status', '--porcelain', '--untracked-files=all')) {
        throw '작업 트리가 깨끗하지 않습니다. 변경과 추적하지 않는 파일을 먼저 정리하세요.'
    }
    $HeadCommit = Get-Git @('rev-parse', 'HEAD')
    $TrackingCommit = Get-Git @('rev-parse', 'refs/remotes/origin/main')
    $RemoteMain = Get-Git @('ls-remote', 'origin', 'refs/heads/main')
    if (-not $RemoteMain -or $HeadCommit -ne $TrackingCommit -or ($RemoteMain -split '\s+')[0] -ne $HeadCommit) {
        throw 'main이 origin/main 및 원격 main과 같지 않습니다. 먼저 동기화하세요.'
    }
    $Tag = "v$Version"
    if (Get-Git @('tag', '--list', $Tag)) { throw "이미 있는 태그입니다: $Tag" }
    if (Get-Git @('ls-remote', '--tags', 'origin', "refs/tags/$Tag")) { throw "원격에 이미 있는 태그입니다: $Tag" }
    # 비공개 소스 저장소(origin)에는 버전 커밋과 태그만 push한다.
    # Release 조회·이전 매니페스트·자산 게시는 공개 배포 저장소에서만 한다.
    $Repository = $ReleaseRepository

    # 저장소 접근 실패를 Release 없음(404)으로 오인하지 않는다.
    & gh api "repos/$Repository" --hostname github.com --silent
    if ($LASTEXITCODE -ne 0) { throw 'GitHub 저장소에 접근할 수 없습니다. 로그인과 원격 저장소를 확인하세요.' }
    $SavedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $ReleaseResponse = & gh api "repos/$Repository/releases/tags/$Tag" --hostname github.com --include --silent 2>$null
        $ReleaseExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $SavedPreference }
    if ($ReleaseExit -eq 0) { throw "이미 있는 Release입니다: $Tag" }
    if (($ReleaseResponse -join "`n") -notmatch '(?m)^HTTP/\S+\s+404\b') {
        throw 'Release 존재 여부를 확인하지 못했습니다. 연결과 권한을 확인하세요.'
    }

    $ProjectPath = Join-Path (Get-Location) 'pyproject.toml'
    $ProjectText = [IO.File]::ReadAllText($ProjectPath)
    $ProjectSection = [regex]::Match($ProjectText, '(?ms)^\[project\]\r?\n(?<body>.*?)(?=^\[|\z)')
    $VersionMatch = [regex]::Match($ProjectSection.Groups['body'].Value, '(?m)^version\s*=\s*"(?<version>[^"]+)"')
    if (-not $VersionMatch.Success) { throw 'pyproject.toml의 project.version을 찾을 수 없습니다.' }
    $CurrentVersion = $VersionMatch.Groups['version'].Value
    if ([version]$Version -le [version]$CurrentVersion) { throw '현재 버전보다 큰 새 버전을 지정하세요.' }
    $MergedTags = Get-Git @('tag', '--merged', 'HEAD', '--sort=-version:refname', '--list', 'v[0-9]*')
    $PreviousTag = ($MergedTags -split "`n")[0]
    $Range = if ($PreviousTag) { "${PreviousTag}..HEAD" } else { 'HEAD' }
    $CommitMessage = "버전 $Version 릴리스 준비"
    $Installer = Join-Path (Get-Location) "dist/installer/MyVideoManager-Setup-$Version.exe"
    $Checksum = "$Installer.sha256"
    $PatchInstaller = Join-Path (Split-Path $Installer) "MyVideoManager-Patch-$Version.exe"
    $Manifest = Join-Path (Split-Path $Installer) "$Version/update-manifest.json"
    $Signature = "$Manifest.sig"
    $AppDirectory = Join-Path (Get-Location) 'dist/my-video-manager'
    $KeyArguments = @()
    if ($PrivateKey) { $KeyArguments = @('--private-key', $PrivateKey) }
    # 암호는 한 번만 받고 preflight/sign 자식 프로세스 환경에만 잠시 제공한다.
    if (-not $DryRun) {
        $KeyInfo = Get-Metadata (@('key-info') + $KeyArguments)
        if ($KeyInfo.encrypted -and -not $SigningPassword) {
            if ([Console]::IsInputRedirected) { throw '비대화형 실행에는 MVM_UPDATE_SIGNING_PASSWORD가 필요합니다.' }
            $SigningPassword = Read-Host 'Signing key password' -AsSecureString
            if ($SigningPassword.Length -eq 0) { throw '서명 키 암호는 비어 있을 수 없습니다.' }
        }
        Get-Metadata (@('preflight') + $KeyArguments) | Out-Null
        foreach ($Output in @($Manifest, $Signature)) {
            if (Test-Path -LiteralPath $Output) { throw "기존 메타데이터를 덮어쓰지 않습니다: $Output" }
        }
    }
    $Previous = Get-Metadata @('previous', '--repository', $Repository, '--version', $Version)
    $FullInstallNote = '이번 버전은 전체 설치 파일로 한 번 설치해야 합니다. 이후 런타임 지문이 같은 버전부터 패치를 사용할 수 있습니다.'
    # 이름이 바뀐 첫 Release에만 넣는다. 이 Release를 발행한 뒤 $RenameNote와 $IncludeRenameNote를 지운다.
    $RenameNote = '이번 버전부터 앱 이름이 **상영실**로 바뀌었습니다. 라이브러리·설정 데이터와 설치 위치는 그대로이므로 다시 설정하거나 옮길 필요가 없습니다.'
    $IncludeRenameNote = $true

    if ($DryRun) {
        Write-Host "계획: pyproject.toml 버전 $CurrentVersion -> $Version, 커밋: $CommitMessage"
        Write-Host "계획: 태그 $Tag 생성, origin에 main과 태그 push, 설치 파일·SHA-256·매니페스트·서명을 배포 저장소 $Repository Release에 게시"
        Write-Host '실제 발행 시 서명 키 필요: 앱 내장 공개 키 일치 검사 필수 (DryRun은 개인 키를 읽거나 암호를 묻지 않음).'
        Write-Host "릴리스 노트 (기준: $Range):"
        Get-Git @('-c', 'i18n.logOutputEncoding=utf-8', 'log', '--reverse', '--format=%s', $Range) | Write-Host
        Write-Host $CommitMessage
        if ($Build) {
            & "$PSScriptRoot/build.ps1" -Version $Version
            if ($LASTEXITCODE -ne 0) { throw 'dry-run 빌드에 실패했습니다.' }
        }
        $Plan = Get-PatchPlan
        Show-AssetPlan $Plan
        if ($null -eq $Plan.patch_available) { Write-Host "패치 불가 판정 시 릴리스 노트 안내: $FullInstallNote" }
        elseif (-not $Plan.patch_available) { Write-Host "릴리스 노트 안내: $FullInstallNote" }
        if ($IncludeRenameNote) { Write-Host "릴리스 노트 안내: $RenameNote" }
        if ($Build -and $Plan.patch_available) {
            & "$PSScriptRoot/build.ps1" -Version $Version -SkipPyInstaller -PatchOnly
            if ($LASTEXITCODE -ne 0) { throw 'dry-run 패치 빌드에 실패했습니다.' }
        }
        Write-Host '매니페스트·서명·체크섬은 실제 발행 단계에서 생성합니다.'
        Write-Host 'DryRun 완료: 버전·커밋·태그·원격은 변경하지 않았습니다.'
        return
    }

    # 버전 커밋과 태그는 이번 실행이 만든 상태만 복구한다.
    $VersionCommit = $HeadCommit
    $CreatedTag = $null
    $PushAttempted = $false
    $PushConfirmed = $false
    try {
        # 2. project.version만 바꾸고 한국어로 커밋한다.
        $Offset = $ProjectSection.Groups['body'].Index + $VersionMatch.Groups['version'].Index
        $Updated = $ProjectText.Remove($Offset, $CurrentVersion.Length).Insert($Offset, $Version)
        [IO.File]::WriteAllText($ProjectPath, $Updated, (New-Object Text.UTF8Encoding($false)))
        Get-Git @('add', '--', 'pyproject.toml') | Write-Host
        Get-Git @('commit', '-m', $CommitMessage) | Write-Host
        $VersionCommit = Get-Git @('rev-parse', 'HEAD')
        # 3. 실패는 아래 catch에서 발행 여부와 로컬 변경을 확인한 뒤 복구한다.
        & "$PSScriptRoot/build.ps1"
        if ($LASTEXITCODE -ne 0) { throw '빌드에 실패했습니다.' }
        if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { throw "설치 파일이 없습니다: $Installer" }
        $Plan = Get-PatchPlan
        Show-AssetPlan $Plan
        $Assets = @($Installer, $Checksum, $Manifest, $Signature)
        $ManifestArguments = @('sign', '--version', $Version, '--runtime-fingerprint', (Join-Path $AppDirectory 'runtime-fingerprint.json'), '--full', $Installer, '--output', $Manifest) + $KeyArguments
        if ($Previous.runtime_fingerprint) { $ManifestArguments += @('--previous-fingerprint', $Previous.runtime_fingerprint) }
        if ($Plan.patch_available) {
            & "$PSScriptRoot/build.ps1" -Version $Version -SkipPyInstaller -PatchOnly
            if ($LASTEXITCODE -ne 0) { throw '패치 빌드에 실패했습니다.' }
            $Assets += $PatchInstaller
            $ManifestArguments += @('--patch', $PatchInstaller)
        }
        Get-Metadata $ManifestArguments | Out-Null
        if (Get-Git @('status', '--porcelain', '--untracked-files=all')) { throw '빌드가 추적 대상 파일을 변경했습니다. 발행을 중단합니다.' }
        $Digest = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
        [IO.File]::WriteAllText($Checksum, "$Digest  $([IO.Path]::GetFileName($Installer))`n", (New-Object Text.UTF8Encoding($false)))
        # 6. 이전 태그 이후 커밋 제목으로 노트를 만든 뒤 4~5단계에 사용한다.
        $NotesPath = Join-Path (Split-Path $Installer) "release-notes-$Version.md"
        $Subjects = Get-Git @('-c', 'i18n.logOutputEncoding=utf-8', 'log', '--reverse', '--format=%s', $Range)
        $Notes = (($Subjects -split "`n" | ForEach-Object { "- $_" }) -join "`n")
        $Notices = @()
        if ($IncludeRenameNote) { $Notices += $RenameNote }
        if (-not $Plan.patch_available) { $Notices += $FullInstallNote }
        if ($Notices.Count -gt 0) { $Notes = (($Notices -join "`n`n") + "`n`n" + $Notes) }
        [IO.File]::WriteAllText($NotesPath, $Notes, (New-Object Text.UTF8Encoding($false)))
        # 4. 원격 main이 바뀌면 non-fast-forward/atomic push가 전체를 거부한다. 강제 push하지 않는다.
        Get-Git @('tag', '-a', $Tag, '-m', "버전 $Version 릴리스") | Write-Host
        $CreatedTag = Get-Git @('rev-parse', "refs/tags/$Tag")
        $PushAttempted = $true
        Get-Git @('push', '--atomic', 'origin', 'HEAD:refs/heads/main', "refs/tags/$Tag") | Write-Host
        $PushConfirmed = $true
        # 5. 배포 저장소에는 소스 태그가 없으므로 그 저장소 main에 같은 이름의 태그를 만들며 게시한다.
        & gh release create $Tag @Assets --repo "github.com/$Repository" --target main --title "$Tag 릴리스" --notes-file $NotesPath
        if ($LASTEXITCODE -ne 0) { throw 'Release 생성에 실패했습니다. 원격 태그와 자산 상태를 확인하세요. 자동 덮어쓰기는 하지 않습니다.' }
        Write-Host "릴리스 완료: $Tag"

    } catch {
        $Failure = $_
        $RemoteUnchanged = -not $PushAttempted
        if ($PushAttempted -and -not $PushConfirmed) {
            # 응답 유실로 push 성공을 실패로 볼 수도 있으므로 원격을 다시 읽는다.
            try {
                $RemoteRefs = Get-Git @('ls-remote', 'origin', 'refs/heads/main', "refs/tags/$Tag")
                $RemoteUnchanged = $RemoteRefs -match "^$HeadCommit\s+refs/heads/main$"
            } catch { $RemoteUnchanged = $false }
        }
        if ($PushConfirmed -or -not $RemoteUnchanged) {
            Write-Warning "로컬 커밋과 태그를 보존합니다. push 성공 시 원격 main과 $Tag 태그가 남아 있습니다."
            Write-Warning "먼저 확인: git ls-remote origin refs/heads/main refs/tags/$Tag"
            Write-Warning "Release 확인: gh release view $Tag --repo github.com/$Repository"
            Write-Warning "origin의 main/태그가 이번 커밋($VersionCommit)을 가리키고 배포 저장소에 Release가 없으면 실행:"
            $AssetArguments = ($Assets | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ' '
            Write-Warning "gh release create $Tag $AssetArguments --repo github.com/$Repository --target main --title '$Tag 릴리스' --notes-file '$NotesPath'"
            Write-Warning "Release가 이미 있으면 다음 목록 중 누락 자산만 골라 추가: gh release upload $Tag $AssetArguments --repo github.com/$Repository"
        } else {
            try {
                if ((Get-Git @('rev-parse', 'HEAD')) -ne $VersionCommit) {
                    throw '실행 중 HEAD가 바뀌었습니다.'
                }
                # 커밋 이전 실패는 우리가 쓴 버전 파일만 원본으로 복구한다.
                if ($VersionCommit -eq $HeadCommit -and [IO.File]::ReadAllText($ProjectPath) -eq $Updated) {
                    Get-Git @('restore', '--source', $HeadCommit, '--staged', '--worktree', '--', 'pyproject.toml') | Write-Host
                }
                if (Get-Git @('status', '--porcelain', '--untracked-files=all')) {
                    throw '다른 작업 파일 변경이 있어 자동 복구하지 않습니다.'
                }
                if ($CreatedTag) {
                    # 같은 이름을 외부에서 바꿨으면 삭제하지 않는다.
                    Get-Git @('update-ref', '-d', "refs/tags/$Tag", $CreatedTag) | Write-Host
                }
                Get-Git @('reset', '--keep', $HeadCommit) | Write-Host
                Write-Warning "발행 전 실패: 로컬 버전 커밋과 이번 태그를 복구했습니다 (HEAD=$HeadCommit)."
            } catch {
                Write-Warning "자동 복구 중단: $_"
                Write-Warning 'git status와 git diff를 확인하고 보존할 변경을 먼저 저장하세요.'
                Write-Warning '변경 보관: git stash push --include-untracked'
                if ($CreatedTag) { Write-Warning "이번 태그인지 확인 후 삭제: git update-ref -d refs/tags/$Tag $CreatedTag" }
                Write-Warning "추가 커밋과 현재 브랜치 확인: git log --oneline $HeadCommit..HEAD"
                Write-Warning "현재 HEAD와 작업을 보존한 뒤 이번 버전 커밋($VersionCommit)만 git revert 등으로 정리하세요. 다른 커밋까지 reset하지 마세요."
            }
        }
        throw $Failure
    }
} finally {
    if (-not $DryRun) { Remove-Item Env:MVM_UPDATE_SIGNING_PASSWORD -ErrorAction SilentlyContinue }
    if ($SigningPassword) { $SigningPassword.Dispose() }
    [Console]::OutputEncoding = $OriginalOutputEncoding
}
