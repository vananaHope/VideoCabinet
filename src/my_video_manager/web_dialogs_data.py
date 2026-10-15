"""대화상자에 필요한 값만 전달하는 웹 계약. 도메인 객체는 노출하지 않는다."""
from typing import TypedDict


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


class DialogData(TypedDict):
    id: str
    kind: str
    title: str
    description: str
    rows: list[DialogRow]
    available: list[DialogRow]
    choices: list[DialogRow]
    values: DialogValues
    maximum: float
    locked: bool
    warning: str
    confirmation: str


class DialogSnapshot(TypedDict):
    dialog: DialogData | None


def row(identifier, title, detail='', status='', start=0, end=None):
    return dict(id=str(identifier), title=title, detail=detail, status=status, start=start, end=end)


def values(**updates):
    return {**dict(name='', text='', start=0.0, end=0.0, range=False, choice='', members=[]), **updates}
