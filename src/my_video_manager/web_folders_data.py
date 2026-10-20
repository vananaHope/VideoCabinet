"""폴더 관리 화면의 공개 JSON 데이터."""
from typing import TypedDict

from .external_subtitles import WARNING_PREFIX
from .library import ScanIssueKind

# 따로 닫을 수 있는 검사 안내 묶음. summary는 등록 요약·알림 또는 검사 실패 문구다.
SCAN_NOTICE_GROUPS = ('failures', 'subtitleWarnings', 'summary')

class RestorableVideoData(TypedDict):
    id: int
    title: str
    missing: bool
    excluded: bool


class ScanIssueData(TypedDict):
    path: str
    message: str


class ScanReportData(TypedDict):
    """검사 안내. 안내는 코어가 정한 종류별로 나눠 넘긴다(실패는 오류, 외부 자막은 경고, 알림은 정보).

    revision은 보고가 바뀔 때마다 오르며, 닫기 요청이 그사이 온 새 결과를 닫지 않게 한다.
    dismissible은 끝난 검사의 결과라 묶음마다 닫을 수 있다는 뜻이다. 닫은 묶음은 비워서(요약은 빈 문구) 넘긴다.
    """
    revision: int
    dismissible: bool
    message: str
    failed: bool
    failures: list[ScanIssueData]
    subtitleWarnings: list[ScanIssueData]
    notes: list[ScanIssueData]


class FoldersData(TypedDict):
    folders: list[str]
    excluded: list[RestorableVideoData]
    dismissed: list[RestorableVideoData]
    minimum: float
    scanning: bool
    report: ScanReportData
    automaticDetection: bool
    unwatched: list[str]
    watchStartFailed: bool


def scan_report_data(report, revision) -> ScanReportData:
    groups = {kind: [] for kind in ScanIssueKind}
    # 코어가 같은 경로의 같은 안내를 두 번 낼 수 있다(순회 오류와 저장된 위치 오류). 화면에는 한 번만 보이고 개수도 맞춘다.
    for kind, path, message in dict.fromkeys((issue.kind, str(issue.path), issue.message) for issue in report.issues):
        # 외부 자막 경고 목록 제목이 종류를 말하므로 상세 절과 같이 접두어를 뺀다.
        if kind is ScanIssueKind.SUBTITLE:
            message = message.removeprefix(WARNING_PREFIX)
        groups[kind].append(ScanIssueData(path=path, message=message))
    shown = {group: group not in report.dismissed for group in SCAN_NOTICE_GROUPS}
    return ScanReportData(
        revision=revision, dismissible=report.finished, failed=report.failed,
        message=report.message if shown['summary'] else '', notes=groups[ScanIssueKind.NOTE] if shown['summary'] else [],
        failures=groups[ScanIssueKind.FAILURE] if shown['failures'] else [],
        subtitleWarnings=groups[ScanIssueKind.SUBTITLE] if shown['subtitleWarnings'] else [])
