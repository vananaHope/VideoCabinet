"""라이브러리 페이지 브리지 계약과 작업 목록."""

from types import MappingProxyType

from . import web_library_data
from .library_views import CHOICES, FILTER_DEFAULTS, LibraryViewOptions, default_options, LibraryFolder, LibraryChipRange, LibraryChip
from .web_contract_types import Argument, BridgeContract, Constant, TypeAlias

MENU_ACTIONS = MappingProxyType({
    'play': '재생', 'tags': '태그 편집', 'subtitles': '자막 만들기 / 원어 지정',
    'review': '자막 검수 / SRT 내보내기', 'series': '시리즈 편집',
    'rename': '제목 변경', 'reconnect': '파일 다시 연결', 'exclude': '제외',
})
SCAN_LOCKED_ACTIONS = ('rename', 'reconnect', 'exclude')

LIBRARY = BridgeContract(name='library', interface='LibraryBridge', slots={
    'ready': (), 'snapshot': (), 'videos': (Argument('ids', str, 'string'),),
    'filter': (Argument('query', str, 'string'), Argument('tag', int, 'number')),
    'view': (Argument('options', str, 'string'),),
    'select': (Argument('id', int, 'number'),), 'clearSelection': (), 'details': (Argument('id', int, 'number'),),
    'action': (Argument('name', str, 'Action'), Argument('id', int, 'number')),
    'highlights': (Argument('videoId', int, 'number'),),
    'playHighlight': (Argument('videoId', int, 'number'), Argument('highlightId', int, 'number')),
    'editHighlight': (Argument('videoId', int, 'number'), Argument('highlightId', int, 'number')),
    'randomPlay': (), 'randomPlayAll': (), 'randomTagCandidates': (), 'randomPlayTags': (Argument('tagIds', str, 'string'),),
}, signals={
    'thumbnailsChanged': str, 'libraryChanged': str, 'libraryDetailsChanged': int,
    'libraryFocusRequested': str, 'libraryError': str, 'libraryKeyBindingsChanged': str,
}, aliases=(TypeAlias('Action', tuple(MENU_ACTIONS)),), constants=(
    Constant('actions', tuple(MENU_ACTIONS.items())),
    Constant('scanLockedActions', SCAN_LOCKED_ACTIONS, 'readonly Action[]'),
    Constant('libraryChoices', CHOICES),
    Constant('libraryFilterDefaults', FILTER_DEFAULTS),
    # 첫 데이터가 오기 전 툴바를 같은 자리에 그릴 때 쓰는 기본 보기 조건(#260).
    Constant('libraryViewDefaults', default_options(), 'LibraryViewOptions'),
), data_types=(web_library_data.TagData, web_library_data.TagUsageData, web_library_data.TagCandidatesData, web_library_data.VideoData,
               LibraryViewOptions, LibraryFolder, LibraryChipRange, LibraryChip,
               web_library_data.ExternalSubtitleTrackData, web_library_data.ExternalSubtitleFileData,
               web_library_data.DetailsData, web_library_data.HighlightData, web_library_data.LibraryKeyBindingsData,
               web_library_data.LibraryData, web_library_data.LibraryVideosData, web_library_data.LibraryEntryData))
