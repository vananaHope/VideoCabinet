"""목록과 추천 카드가 공유하는 썸네일 아이콘 캐시."""

from PySide6.QtGui import QIcon


class ThumbnailIcons:
    def __init__(self, largest_size):
        self._icons = {}
        self._keys = {}
        self._largest_size = largest_size

    def get(self, path):
        name = str(path)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        key = (name, mtime)
        previous = self._keys.get(name)
        if previous != key:
            self._icons.pop(previous, None)
            self._keys[name] = key
        if key not in self._icons:
            icon = QIcon(name)
            # 파일 아이콘은 첫 크기 요청으로 로드된다. 카드가 먼저 읽어도
            # 라이브러리 목록의 큰 썸네일까지 표시할 수 있는 크기로 초기화한다.
            icon.actualSize(self._largest_size)
            self._icons[key] = icon
        return self._icons[key]

    def retain(self, paths):
        names = {str(path) for path in paths}
        for name in self._keys.keys() - names:
            self._icons.pop(self._keys.pop(name), None)
