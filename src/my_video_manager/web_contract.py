"""웹 공개 계약의 단일 원본. Qt 선언과 TypeScript 생성기가 함께 읽는다."""

TABS = (
    ('library', '라이브러리'), ('reel', '모아보기'), ('search', '검색'),
    ('queue', '자막 대기열'), ('statistics', '통계'), ('folders', '폴더 관리'),
    ('settings', '설정'),
)
ACTIONS = {
    'play': '재생', 'tags': '태그 편집', 'subtitles': '자막 만들기 / 원어 지정',
    'review': '자막 검수 / SRT 내보내기', 'series': '시리즈 편집',
    'rename': '제목 변경', 'reconnect': '파일 다시 연결', 'exclude': '제외',
    'playGem': '추천 재생', 'dismiss': '관심 없음',
}
SCAN_LOCKED_ACTIONS = ('rename', 'reconnect', 'exclude')
SLOTS = {
    'ready': (), 'snapshot': (), 'filter': (('query', str), ('tag', int)),
    'select': (('id', int),), 'details': (('id', int),),
    'action': (('name', str), ('id', int)),
    'shellSnapshot': (), 'navigate': (('tab', str),),
}
SIGNALS = {
    'libraryChanged': str, 'libraryDetailsChanged': int,
    'libraryFocusRequested': str, 'libraryError': str, 'shellChanged': str,
}


def bridge_slot(name):
    from PySide6.QtCore import Slot
    return Slot(*(kind for _, kind in SLOTS[name]), result=str)


def bridge_signal(name):
    from PySide6.QtCore import Signal
    return Signal(SIGNALS[name])
