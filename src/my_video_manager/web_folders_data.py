"""폴더 관리 화면의 공개 JSON 데이터."""
from typing import TypedDict

from .external_subtitles import WARNING_PREFIX
from .library import ScanIssueKind


class RestorableVideoData(TypedDict):
    id: int
    title: str
    missing: bool
    excluded: bool


class ScanIssueData(TypedDict):
    path: str
    message: str


class ScanReportData(TypedDict):
    """검사 안내. 안내는 코어가 정한 종류별로 나눠 넘긴다(실패는 오류, 외부 자막은 경고, 알림은 정보)."""
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


def scan_report_data(report) -> ScanReportData:
    groups = {kind: [] for kind in ScanIssueKind}
    for issue in report.issues:
        # 외부 자막 경고 목록 제목이 종류를 말하므로 상세 절과 같이 접두어를 뺀다.
        message = issue.message.removeprefix(WARNING_PREFIX) if issue.kind is ScanIssueKind.SUBTITLE else issue.message
        groups[issue.kind].append(ScanIssueData(path=str(issue.path), message=message))
    return ScanReportData(message=report.message, failed=report.failed, failures=groups[ScanIssueKind.FAILURE],
                          subtitleWarnings=groups[ScanIssueKind.SUBTITLE], notes=groups[ScanIssueKind.NOTE])
