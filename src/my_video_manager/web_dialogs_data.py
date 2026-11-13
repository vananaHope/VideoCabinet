"""대화상자에 필요한 값만 전달하는 웹 계약. 도메인 객체는 노출하지 않는다."""
from typing import TypedDict
from .web_library_data import TagCandidatesData, TagUsageData
from .web_translation_data import TranslationSettingsData, TranslationSelectionData


class DialogRow(TypedDict):
    id: str
    title: str
    detail: str
    status: str
    start: float
    end: float | None


class DialogValues(TypedDict):
    name: str
    text: str
    start: float
    end: float
    range: bool
    choice: str
    members: list[str]
    selections: list[TranslationSelectionData]
    fallback: bool
    key_action: str
    key: str


class DialogData(TypedDict):
    id: str
    kind: str
    title: str
    description: str
    rows: list[DialogRow]
    # 태그 편집에서 고를 수 있는 등록 태그 전체(붙은 영상 수가 많은 순). 붙은 태그는 rows이고 화면이 목록에서 뺀다.
    tags: list[TagUsageData]
    # 무작위 이어 재생 범위 고르기의 태그별 후보 영상 ID. 화면은 고른 태그의 합집합 크기만 센다.
    tag_candidates: list[TagCandidatesData]
    available: list[DialogRow]
    # 검수 화면이 더 보여 줄 SRT 저장(화면 자막·화면 번역 자막). id는 작업 이름, title은 단추 이름이다.
    exports: list[DialogRow]
    choices: list[DialogRow]
    values: DialogValues
    maximum: float
    locked: bool
    warning: str
    confirmation: str
    confirm_title: str
    confirm_destructive: bool
    translation: TranslationSettingsData | None
    network_busy: bool
    information: str
    task_kind: str
    task_label: str
    subtitle_label: str
    short_label: str
    keep_reviewed: bool


class DialogSnapshot(TypedDict):
    dialog: DialogData | None


def row(identifier, title, detail='', status='', start=0, end=None):
    return dict(id=str(identifier), title=title, detail=detail, status=status, start=start, end=end)


def values(**updates):
    return {**dict(name='', text='', start=0.0, end=0.0, range=False, choice='', members=[], selections=[], fallback=False, key_action="keep", key=""), **updates}
