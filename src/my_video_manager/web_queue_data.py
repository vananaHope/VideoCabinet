"""자막 대기열 웹 전송 값. 도메인 판단은 AppCore에 남긴다."""
from typing import TypedDict

from .web_contract_types import GenerationData


STATES = {'queued': '대기', 'transcribing': '받아쓰는 중', 'reading': '읽는 중', 'translating': '자막 처리 중',
          'held': '보류', 'completed': '완료', 'failed': '실패'}


class QueueRowData(TypedDict):
    # 행 식별자. 같은 영상도 작업 종류가 다르면 다른 행이다.
    key: str
    videoId: int
    queueKind: str
    title: str
    state: str
    progress: float
    message: str
    taskLabel: str
    stateLabel: str


class PreparationData(TypedDict):
    state: str
    message: str
    phase: str
    asset: str
    completed: int
    total: int
    kind: str
    summary: str
    percent: int | None
    percentLabel: str
    guidance: str


class QueueCountData(TypedDict):
    state: str
    label: str
    count: int


class QueueData(GenerationData):
    """대기열 전체 상태. rows는 처리 순서대로다."""
    canRetryFailed: bool
    rows: list[QueueRowData]
    counts: list[QueueCountData]


class QueueTargetData(TypedDict):
    key: str
    label: str


class QueueRuleData(TypedDict):
    id: int
    target: str
    label: str
    language: str


class QueueRulesData(TypedDict):
    targets: list[QueueTargetData]
    rules: list[QueueRuleData]


def row_key(video_id, queue_kind) -> str:
    return f'{video_id}:{queue_kind}'


def row_data(entry) -> QueueRowData:
    return dict(key=row_key(entry.video_id, entry.queue_kind), videoId=entry.video_id, queueKind=entry.queue_kind,
                title=entry.title, state=entry.state,
                progress=entry.progress, message=entry.error or '', taskLabel=entry.task_label,
                stateLabel='받아쓰는 중' if entry.state == 'transcribing'
                else f'{entry.task_label} · 처리 중' if entry.state == 'translating'
                else f'{entry.task_label} · {STATES[entry.state]}')


def counts_data(entries) -> list[QueueCountData]:
    counts = dict.fromkeys(STATES, 0)
    for entry in entries:
        counts[entry.state] += 1
    return [dict(state=state, label=label, count=counts[state]) for state, label in STATES.items()]


def rules_data(core) -> QueueRulesData:
    tags = {tag.id: tag.name for tag in core.tags()}
    targets = [dict(key=f'folder:{folder.path}', label=f'폴더: {folder.path}')
               for folder in core.watched_folders()]
    targets += [dict(key=f'tag:{id}', label=f'태그: {name}') for id, name in tags.items()]
    rules = [dict(id=rule.id,
                  target=f'folder:{rule.folder}' if rule.folder else f'tag:{rule.tag_id}',
                  label=str(rule.folder) if rule.folder else f'태그: {tags.get(rule.tag_id, rule.tag_id)}',
                  language=rule.spoken_language or '자동 감지') for rule in core.auto_subtitle_rules()]
    return dict(targets=targets, rules=rules)
