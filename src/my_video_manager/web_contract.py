"""웹 공개 계약의 단일 원본. Qt 선언과 TypeScript 생성기가 함께 읽는다."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from . import web_library_data, web_shell_data
from . import web_queue_data
from . import web_reel_data, web_search_data

TABS = (
    ('library', '라이브러리'), ('reel', '모아보기'), ('search', '검색'),
    ('queue', '자막 대기열'), ('statistics', '통계'), ('folders', '폴더 관리'),
    ('settings', '설정'),
)
MENU_ACTIONS = MappingProxyType({
    'play': '재생', 'tags': '태그 편집', 'subtitles': '자막 만들기 / 원어 지정',
    'review': '자막 검수 / SRT 내보내기', 'series': '시리즈 편집',
    'rename': '제목 변경', 'reconnect': '파일 다시 연결', 'exclude': '제외',
})
GEM_ACTIONS = MappingProxyType({'playGem': '추천 재생', 'dismiss': '관심 없음'})
SCAN_LOCKED_ACTIONS = ('rename', 'reconnect', 'exclude')


@dataclass(frozen=True)
class Argument:
    name: str
    python_type: type
    typescript_type: str


@dataclass(frozen=True)
class TypeAlias:
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Constant:
    name: str
    values: tuple
    typescript_type: str | None = None


@dataclass(frozen=True)
class BridgeContract:
    """페이지 하나의 불변 공개 표면. 이름·순서로 페이지의 역할을 추론하지 않는다."""
    name: str
    interface: str
    slots: Mapping[str, tuple[Argument, ...]] = field(default_factory=dict)
    signals: Mapping[str, type] = field(default_factory=dict)
    aliases: tuple[TypeAlias, ...] = ()
    constants: tuple[Constant, ...] = ()
    data_types: tuple[type, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'slots', MappingProxyType(dict(self.slots)))
        object.__setattr__(self, 'signals', MappingProxyType(dict(self.signals)))

    def slot(self, name):
        from PySide6.QtCore import Slot
        return Slot(*(arg.python_type for arg in self.slots[name]), result=str)

    def signal(self, name):
        from PySide6.QtCore import Signal
        return Signal(self.signals[name])


SHELL = BridgeContract(
    name='shell', interface='ShellBridge',
    slots={'ready': (), 'shellSnapshot': (), 'navigate': (Argument('tab', str, 'Tab'),)},
    signals={'shellChanged': str, 'shellStatusChanged': str, 'shellFocusRequested': str},
    aliases=(TypeAlias('Tab', tuple(name for name, _ in TABS)),),
    constants=(Constant('tabs', TABS),),
    data_types=(web_shell_data.ShellData,),
)

LIBRARY = BridgeContract(name='library', interface='LibraryBridge', slots={
    'ready': (), 'snapshot': (),
    'filter': (Argument('query', str, 'string'), Argument('tag', int, 'number')),
    'select': (Argument('id', int, 'number'),), 'details': (Argument('id', int, 'number'),),
    'action': (Argument('name', str, 'Action'), Argument('id', int, 'number')),
    'highlights': (Argument('videoId', int, 'number'),),
    'playHighlight': (Argument('videoId', int, 'number'), Argument('highlightId', int, 'number')),
    'editHighlight': (Argument('videoId', int, 'number'), Argument('highlightId', int, 'number')),
}, signals={
    'libraryChanged': str, 'libraryDetailsChanged': int,
    'libraryFocusRequested': str, 'libraryError': str,
}, aliases=(TypeAlias('Action', (*MENU_ACTIONS, *GEM_ACTIONS)),), constants=(
    Constant('actions', tuple(MENU_ACTIONS.items())),
    Constant('scanLockedActions', SCAN_LOCKED_ACTIONS, 'readonly Action[]'),
), data_types=(web_library_data.TagData, web_library_data.VideoData, web_library_data.GemData,
               web_library_data.DetailsData, web_library_data.HighlightData, web_library_data.LibraryData))

REEL = BridgeContract(name='reel', interface='ReelBridge', slots={
    'ready': (), 'snapshot': (), 'refresh': (),
    'filter': (Argument('tagId', int, 'number'),),
    'select': (Argument('highlightId', int, 'number'),),
    'play': (Argument('highlightId', int, 'number'),),
}, signals={'changed': str, 'focusRequested': str, 'error': str},
    data_types=(web_reel_data.ReelEntryData, web_reel_data.ReelData))

SEARCH = BridgeContract(name='search', interface='SearchBridge', slots={
    'ready': (), 'snapshot': (), 'find': (Argument('query', str, 'string'),),
    'select': (Argument('index', int, 'number'),),
    'play': (Argument('index', int, 'number'),),
}, signals={'changed': str, 'focusRequested': str, 'error': str},
    data_types=(web_search_data.SearchTextData, web_search_data.SearchResultData, web_search_data.SearchData))

# 새 페이지는 독립 묶음을 선언한 뒤 여기에 한 줄 등록한다.
QUEUE = BridgeContract(name='queue', interface='QueueBridge', slots={
    'ready': (), 'snapshot': (), 'rulesSnapshot': (),
    'action': (Argument('name', str, 'QueueAction'), Argument('videoId', int, 'number')),
    'candidates': (Argument('target', str, 'string'),),
    'saveRule': (Argument('target', str, 'string'), Argument('language', str, 'string'),
                 Argument('includeExisting', bool, 'boolean')),
    'removeRule': (Argument('ruleId', int, 'number'),),
}, signals={'queueChanged': str, 'rulesChanged': str, 'queueFocusRequested': str, 'queueDeactivated': str},
    aliases=(TypeAlias('QueueAction', ('promote', 'remove', 'retryFailed', 'retryHeld')),),
    constants=(Constant('queueStates', tuple(web_queue_data.STATES.items())),),
    data_types=(web_queue_data.QueueRowData, web_queue_data.QueueCountData, web_queue_data.QueueDeltaData,
                web_queue_data.QueueTargetData, web_queue_data.QueueRuleData, web_queue_data.QueueRulesData))

CONTRACTS = (
    SHELL,
    LIBRARY,
    QUEUE,
    REEL,
    SEARCH,
)
