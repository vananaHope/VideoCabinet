"""라이브러리 목록의 썸네일 아이콘을 디코딩 없이 보관한다."""

from PySide6.QtGui import QIcon


class ThumbnailIcons:
    def __init__(self):
        self._icons = {}
        self._keys = {}

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
            self._icons[key] = QIcon(name)
        return self._icons[key]

    def retain(self, paths):
        names = {str(path) for path in paths}
        for name in self._keys.keys() - names:
            self._icons.pop(self._keys.pop(name), None)
