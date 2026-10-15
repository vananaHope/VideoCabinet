"""두 화면이 공유하는 검색 강조 구간. 코어 검색은 Qt를 참조하지 않는다."""
from PySide6.QtCore import QTextBoundaryFinder

from .search import search_key


def match_spans(text: str, query: str) -> list[tuple[int, int]]:
    """Qt 문자소 경계로 정규화하고 원문 Python 슬라이스 구간을 돌려준다."""
    needle = search_key(query)
    if not needle:
        return []
    # Qt 경계는 UTF-16 단위다. 결합 문자·한글 자모를 한 묶음으로 정규화한다.
    encoded = text.encode('utf-16-le')
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    normalized, positions = '', []
    start, original_start = 0, 0
    while (end := finder.toNextBoundary()) != -1:
        cluster = encoded[start * 2:end * 2].decode('utf-16-le')
        original_end = original_start + len(cluster)
        key = search_key(cluster)
        normalized += key
        positions.extend([(original_start, original_end)] * len(key))
        start, original_start = end, original_end
    spans, offset, previous = [], 0, 0
    while (index := normalized.find(needle, offset)) >= 0:
        start, end = positions[index][0], positions[index + len(needle) - 1][1]
        offset = index + len(needle)
        if start < previous:  # ß → ss처럼 같은 원문 문자가 여러 번 대응할 수 있다.
            continue
        spans.append((start, end))
        previous = end
    return spans
