"""설정 화면의 업데이트 확인 표시 데이터. 실패 이유 코드의 사용자 문구는 이 표 한 곳에서 정한다."""
import re
from typing import TypedDict


class UpdateResultData(TypedDict):
    checkedAt: str
    kind: str
    currentVersion: str | None
    latestVersion: str | None
    downloadSize: int | None
    failureReason: str | None
    failureMessage: str
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
}


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
        failureMessage=failure_message(reason) if reason else '',
        failureQuiet=reason in QUIET_FAILURES, stale=result.stale)


def update_status_data(core, controls) -> UpdateStatusData:
    return UpdateStatusData(
        installedVersion=core.installed_update_info().version,
        automatic=core.automatic_update_check_enabled(), checking=controls.checking,
        error=controls.error, last=update_result_data(core.last_update_check()))
