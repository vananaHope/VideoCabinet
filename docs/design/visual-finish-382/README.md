# 시각 마감 6 전후 스크린샷 (#382)

- `1100-before/`는 `main`(`575603a`)의 1100×720 화면, `1100-after/`는 이 변경의 1100×720 화면이다. 같은 이름이 같은 장면이다.
- Linux offscreen에서 `scripts/check_web_recommend.py --offscreen`과 `scripts/check_web_reel_search.py --offscreen`으로 찍었다. Linux에서는 앱 전역 이벤트 필터가 PySide6 세그폴트를 일으켜, 스크린샷을 찍는 동안만 `QApplication.installEventFilter`를 비워 실행했다(화면 배치와는 무관하다).

| 항목 | 장면(파일 이름 앞부분) | 데이터 |
|---|---|---|
| 추천 카드 시청 상태 배지, 자리 표시와 같은 정보 칸 높이 | `recommend--web-recommend-full`, `recommend--web-recommend-placeholder` | 160개 · 자리 표시 |
| 추천 줄 왼쪽 가장자리 | `recommend--web-recommend-empty`, `recommend--web-recommend-few`, `recommend--web-recommend-full`, `recommend--web-recommend-long` | 0 · 적음 · 160개 · 긴 텍스트 |
| 모아보기 결과 행 제목 두 줄 제한, 상태 문장 | `reelsearch--web-reel-long`, `reelsearch--web-reel-many` | 긴 텍스트 · 503개 |
| 검색 결과 행 제목 두 줄 제한 | `reelsearch--web-search-long`, `reelsearch--web-search-onscreen-long`, `reelsearch--web-search-cap` | 긴 텍스트 · 최대 개수 |
| 모아보기·검색 왼쪽 가장자리 | `reelsearch--web-reel-empty`, `reelsearch--web-reel-few`, `reelsearch--web-search-empty`, `reelsearch--web-search-few` | 0 · 2개 |
