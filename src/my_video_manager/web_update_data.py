"""설정 화면과 셸 알림의 업데이트 표시 데이터. 실패 이유 코드의 사용자 문구는 이 표 한 곳에서 정한다."""
import re
from typing import TypedDict

from .update_check import announces_update, offers_update


class UpdateResultData(TypedDict):
    checkedAt: str
    kind: str
    currentVersion: str | None
    latestVersion: str | None
    downloadSize: int | None
    failureReason: str | None
    failureMessage: str
    # 서명되지 않은 GitHub 릴리스 본문의 짧은 요약. 화면은 글자로만 보인다(HTML·링크 해석 없음).
    releaseNotes: str | None
    # 공개 키를 넣기 전 개발 빌드처럼 사용자가 할 일이 없는 실패는 경고 대신 정보로 조용히 보인다.
    failureQuiet: bool
    # 이전 버전에서 확인한 이력. 현재 설치본의 업데이트 안내로 쓰지 않는다.
    stale: bool


class UpdateStatusData(TypedDict):
    installedVersion: str
    automatic: bool
    checking: bool
    # 확인 결과를 저장하지 못한 것처럼 기록으로 남지 않는 이번 실행의 실패.
    error: str
    last: UpdateResultData | None
    # 마지막 결과가 현재 설치본의 업데이트인데 그 버전을 건너뛰었다.
    skipped: bool
    # 셸에 새 버전 알림이 보이는 중이다("나중에"·업데이트 선택 전).
    noticeVisible: bool
    # 마지막 결과의 버전을 지금 받기 시작할 수 있다. 진행 중이거나 설치를 넘겼으면 "업데이트"를 보이지 않는다.
    updateAllowed: bool


class UpdateNoticeData(TypedDict):
    """셸 수준 새 버전 알림."""
    version: str
    kind: str
    downloadSize: int
    releaseNotes: str | None


class UpdateInstallResultData(TypedDict):
    """지난 실행에서 넘긴 설치의 결과. 다음 실행 때 한 번 보인다."""
    # success | warning | error
    tone: str
    title: str
    message: str
    # full: 전체 설치 파일로 다시 시도, same: 같은 종류로 다시 시도, None: 다시 시도 없음.
    retry: str | None
    # 실패했고 설치 프로그램 기록이 남아 있으면 그 위치. 다음 성공 때까지 지우지 않는다.
    logPath: str | None


class UpdateInstallData(TypedDict):
    """업데이트 내려받기·설치 진행. 셸 알림과 설정 업데이트 구역이 같은 값을 보인다."""
    # idle | downloading | cancelling | confirm | ready | preparing | failed
    phase: str
    version: str | None
    # patch | full. 내려받기 전에는 확인 결과의 종류다.
    kind: str | None
    received: int
    # 첫 진행률이 오기 전에는 모른다.
    total: int | None
    # confirm 단계에서 확인 대화에 보일 본문: 끊길 작업과 재시작 뒤 이어질 대기 항목.
    confirmation: str
    failureMessage: str
    canRetry: bool
    # ready 안내를 셸에서 닫았다. 설정 업데이트 구역에는 계속 보인다.
    readyDismissed: bool
    result: UpdateInstallResultData | None


class ShellUpdateData(TypedDict):
    notice: UpdateNoticeData | None
    install: UpdateInstallData


QUIET_FAILURES = frozenset({'invalid_public_key'})
SIGNATURE_FAILURE = '업데이트 정보의 서명을 확인하지 못했습니다. 안전을 위해 이 정보를 쓰지 않습니다.'
FORMAT_FAILURE = '업데이트 정보의 형식이 올바르지 않습니다.'
FAILURE_MESSAGES = {
    'invalid_public_key': '업데이트 서명 키가 아직 설정되지 않았습니다. 이 빌드에서는 업데이트를 확인하지 않습니다.',
    'network': '인터넷에 연결하지 못했습니다. 연결을 확인한 뒤 다시 확인하세요.',
    'timeout': 'GitHub 응답이 늦어 확인을 멈췄습니다. 잠시 뒤 다시 확인하세요.',
    'http_403': 'GitHub가 요청을 거절했습니다(HTTP 403). 요청 한도일 수 있으니 한 시간쯤 뒤 다시 확인하세요.',
    'http_429': 'GitHub 요청 한도를 넘었습니다(HTTP 429). 한 시간쯤 뒤 다시 확인하세요.',
    'http_404': 'GitHub에서 최신 릴리스를 찾지 못했습니다(HTTP 404).',
    'unsafe_redirect': '허용하지 않은 주소로 연결하려 해서 확인을 멈췄습니다.',
    'too_many_redirects': '주소 이동이 너무 많아 확인을 멈췄습니다.',
    'response_too_large': '응답이 예상보다 커서 확인을 멈췄습니다.',
    'invalid_response': 'GitHub 응답을 읽지 못했습니다.',
    'invalid_release': '최신 릴리스 정보가 올바르지 않습니다.',
    'release_version_mismatch': '릴리스 버전과 업데이트 정보의 버전이 다릅니다.',
    'invalid_signature': SIGNATURE_FAILURE,
    'invalid_signature_format': SIGNATURE_FAILURE,
    'invalid_json': FORMAT_FAILURE,
    'invalid_format': FORMAT_FAILURE,
    'unsupported_schema': '이 버전이 읽을 수 없는 업데이트 정보입니다. GitHub Release에서 새 버전을 직접 받아 주세요.',
    'installation_unavailable': '설치된 앱 정보를 읽지 못했습니다.',
    'invalid_installed_version': '설치된 앱의 버전을 알 수 없습니다.',
    'check_failed': '알 수 없는 문제로 확인하지 못했습니다.',
    'storage': '업데이트 파일을 저장하지 못했습니다. 디스크 공간과 데이터 폴더를 확인하세요.',
    'cancelled': '업데이트 내려받기를 취소했습니다.',
}


# 내려받기(download_update)와 설치 넘기기(prepare_update_install, 앱 종료)의 실패. 확인 문구(FAILURE_MESSAGES)와
# 겹치는 코드도 "다시 시도"를 안내하도록 여기서 먼저 찾는다. 여기 없는 서명·형식 코드는 확인 문구를 쓴다.
DOWNLOAD_FAILURE_MESSAGES = {
    'no_update': '설치할 업데이트 정보가 없습니다. ‘지금 확인’으로 다시 확인하세요.',
    'not_newer': '이미 이 버전이거나 더 새 버전이 설치되어 있습니다.',
    'installation_unavailable': '설치된 앱 정보를 읽지 못해 업데이트를 받지 않았습니다.',
    'release_version_mismatch': '릴리스 버전과 업데이트 정보의 버전이 달라 받지 않았습니다.',
    'disk_full': '디스크 공간이 부족해 업데이트를 받지 못했습니다. 공간을 비운 뒤 다시 시도하세요.',
    'size_mismatch': '받은 파일의 크기가 업데이트 정보와 달라 지웠습니다. 다시 시도하세요.',
    'hash_mismatch': '받은 파일이 업데이트 정보와 맞지 않아(SHA-256) 지웠습니다. 다시 시도하세요.',
    'network': '인터넷에 연결하지 못했습니다. 연결을 확인한 뒤 다시 시도하세요.',
    'timeout': '응답이 늦어 내려받기를 멈췄습니다. 잠시 뒤 다시 시도하세요.',
    'http_403': 'GitHub가 요청을 거절했습니다(HTTP 403). 한 시간쯤 뒤 다시 시도하세요.',
    'http_404': 'GitHub에서 업데이트 파일을 찾지 못했습니다(HTTP 404).',
    'http_429': 'GitHub 요청 한도를 넘었습니다(HTTP 429). 한 시간쯤 뒤 다시 시도하세요.',
    'unsafe_redirect': '허용하지 않은 주소로 연결하려 해서 내려받기를 멈췄습니다.',
    'too_many_redirects': '주소 이동이 너무 많아 내려받기를 멈췄습니다.',
    'response_too_large': '파일이 업데이트 정보보다 커서 내려받기를 멈췄습니다.',
    'invalid_response': '파일을 끝까지 받지 못했습니다. 다시 시도하세요.',
    'storage': '업데이트 파일을 저장하지 못했습니다. 디스크 공간과 데이터 폴더를 확인하세요.',
    'download_failed': '알 수 없는 문제로 업데이트를 받지 못했습니다. 다시 시도하세요.',
    'installer_missing': '받아 둔 설치 파일이 없어졌습니다. 다시 받아 주세요.',
    'helper_start_failed': '설치 도우미(Windows PowerShell)를 시작하지 못했습니다. 다시 시도하세요.',
    'helper_failed': '설치 도우미가 준비 중에 끝났습니다. 실행 정책이나 백신 프로그램이 막았을 수 있습니다.',
    'helper_not_ready': '설치 도우미가 20초 안에 준비되지 않았습니다. 다시 시도하세요.',
    'handoff_failed': '알 수 없는 문제로 설치를 넘기지 못했습니다. 다시 시도하세요.',
    'source_run': '소스에서 실행한 앱은 설치본을 고치지 않습니다. 설치한 앱에서 업데이트하세요.',
    'quit_blocked': '진행 중인 작업 때문에 앱을 닫을 수 없습니다. 작업이 끝난 뒤 다시 시도하세요.',
    'busy_check_failed': '진행 중인 작업을 확인하지 못했습니다. 다시 시도하세요.',
    'quit_failed': '앱을 닫지 못해 설치가 시작되지 않았습니다. 5분 안에 완전 종료하면 설치가 이어집니다.',
}

# 다음 실행 때 읽는 설치 결과(last_update_install)의 실패 이유.
INSTALL_RESULT_MESSAGES = {
    'patch_rejected': '설치된 앱과 맞지 않아 패치를 적용하지 못했습니다. 전체 설치 파일로 다시 시도하세요.',
    'installer_failed': '설치 프로그램이 오류로 끝났습니다{code}. 다시 시도하세요.',
    'app_did_not_exit': '앱이 5분 안에 닫히지 않아 설치하지 않았습니다. 다시 시도하세요.',
    'hash_mismatch': '설치 직전에 받은 파일이 바뀌어 안전을 위해 설치하지 않았습니다. 다시 시도하세요.',
    'installer_unreadable': '설치 직전에 받은 파일을 읽지 못해 설치하지 않았습니다. 백신 프로그램이 막았을 수 있습니다. '
                            '다시 시도하세요.',
    'installer_start_failed': '설치 프로그램을 시작하지 못했습니다. 백신 프로그램이 막았을 수 있습니다. 다시 시도하세요.',
    'installer_timeout': '설치가 30분 안에 끝나지 않아 기다림을 멈췄습니다. 설치가 아직 진행 중이거나 끝났을 수 있으니 '
                         '잠시 뒤 앱을 다시 켜 보세요. 버전이 그대로면 다시 업데이트하세요.',
    'no_result': '설치가 끝났는지 확인하지 못했습니다. 버전이 그대로라 다시 시도할 수 있습니다.',
}

BUSY_LABELS = {'playback': '영상 재생', 'transcription': '받아쓰기', 'translation': '번역',
               'refinement': '자막 다듬기', 'preparation': '자막 기능 준비'}


def failure_message(reason: str) -> str:
    if reason in FAILURE_MESSAGES:
        return FAILURE_MESSAGES[reason]
    if match := re.fullmatch(r'http_(5[0-9][0-9])', reason):
        return f'GitHub 서버에 일시적인 문제가 있습니다(HTTP {match[1]}). 잠시 뒤 다시 확인하세요.'
    if match := re.fullmatch(r'http_([0-9]{3})', reason):
        return f'GitHub가 오류를 돌려주었습니다(HTTP {match[1]}).'
    return f'확인하지 못했습니다({reason}).'


def update_result_data(result) -> UpdateResultData | None:
    """stale은 저장값이 아니라 읽을 때 계산한 속성이라 asdict 대신 필드를 하나씩 옮긴다."""
    if result is None:
        return None
    reason = result.failure_reason
    return UpdateResultData(
        checkedAt=result.checked_at.isoformat(), kind=result.kind,
        currentVersion=result.current_version, latestVersion=result.latest_version,
        downloadSize=result.download_size, failureReason=reason,
        failureMessage=failure_message(reason) if reason else '', releaseNotes=result.release_notes,
        failureQuiet=reason in QUIET_FAILURES, stale=result.stale)


def update_status_data(core, controls) -> UpdateStatusData:
    # 설정 화면은 1초마다 갱신하므로 확인 결과와 건너뛴 버전을 한 번씩만 읽는다.
    last = core.last_update_check()
    skipped_version = core.skipped_update_version()
    return UpdateStatusData(
        installedVersion=core.installed_update_info().version,
        automatic=core.automatic_update_check_enabled(), checking=controls.checking,
        error=controls.error, last=update_result_data(last),
        skipped=offers_update(last) and last.latest_version == skipped_version,
        noticeVisible=announces_update(last, skipped_version) and not controls.hidden(last),
        updateAllowed=not controls.install.refusal(last.latest_version if offers_update(last) else None))


def shell_update_data(controls) -> ShellUpdateData:
    result = controls.notice()
    return ShellUpdateData(notice=None if result is None else UpdateNoticeData(
        version=result.latest_version, kind=result.kind, downloadSize=result.download_size,
        releaseNotes=result.release_notes), install=update_install_data(controls.install))


def download_failure_message(reason: str) -> str:
    if reason in DOWNLOAD_FAILURE_MESSAGES:
        return DOWNLOAD_FAILURE_MESSAGES[reason]
    if match := re.fullmatch(r'http_(5[0-9][0-9])', reason):
        return f'GitHub 서버에 일시적인 문제가 있습니다(HTTP {match[1]}). 잠시 뒤 다시 시도하세요.'
    return failure_message(reason)


def install_result_data(outcome, retry=None, log_path=None) -> UpdateInstallResultData | None:
    """last_update_install()의 결과를 안내 문구로. retry는 UpdateInstall.result_retry,
    log_path는 실패이고 기록 파일이 있을 때만 넘긴다."""
    if outcome is None:
        return None
    if outcome.status == 'installed':
        return UpdateInstallResultData(tone='success', title=f'{outcome.version} 버전으로 업데이트했습니다',
                                       message='', retry=None, logPath=None)
    reason = outcome.failure_reason or 'no_result'
    if reason == 'installer_failed':
        message = INSTALL_RESULT_MESSAGES[reason].format(
            code='' if outcome.exit_code is None else f'(종료 코드 {outcome.exit_code})')
    else:
        message = INSTALL_RESULT_MESSAGES.get(reason, f'설치하지 못했습니다({reason}). 다시 시도하세요.')
    timeout = reason == 'installer_timeout'
    return UpdateInstallResultData(
        tone='warning' if timeout or outcome.status == 'incomplete' else 'error',
        title=f'{outcome.version} 버전 업데이트를 ' + ('마쳤는지 알 수 없습니다' if timeout else '설치하지 못했습니다'),
        message=message, retry=retry, logPath=None if log_path is None else str(log_path))


def busy_confirmation(busy) -> str:
    """설치 전 확인 대화 본문. busy는 UpdateBusyState에 자막 기능 준비를 더한 것이다."""
    labels = ', '.join(BUSY_LABELS.get(reason, reason) for reason in busy.blocking)
    parts = [f'지금 설치하면 진행 중인 작업을 멈추고 앱을 닫습니다: {labels}. 설치가 끝나면 앱을 다시 실행합니다.']
    if 'transcription' in busy.blocking:
        parts.append('받아쓰던 영상은 다시 실행한 뒤 처음부터 다시 받아씁니다.')
    waiting = [f'{name} {count}개' for name, count in (('받아쓰기', busy.waiting_transcriptions),
                                                      ('번역·다듬기', busy.waiting_translations)) if count]
    if waiting:
        parts.append(f'대기 중인 {"·".join(waiting)}는 다시 실행한 뒤 이어서 처리합니다.')
    return ' '.join(parts)


def update_install_data(install) -> UpdateInstallData:
    failed = install.phase == 'failed'
    return UpdateInstallData(
        phase=install.phase, version=install.version, kind=install.kind, received=install.received,
        total=install.total, confirmation=busy_confirmation(install.busy) if install.phase == 'confirm' else '',
        failureMessage=install.failure_text or download_failure_message(install.failure) if failed else '',
        canRetry=failed and install.can_retry, readyDismissed=install.ready_dismissed, result=install_result_data(install.result, install.result_retry, install.result_log))
