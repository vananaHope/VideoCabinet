# 시각 마감 1 전후 스크린샷 (#377)

`before/`는 `main`(`aaeb529`), `after/`는 이 변경의 1100×720 화면이다. 같은 이름이 같은 장면이다.
Linux offscreen에서 `scripts/linux_offscreen_check.py`로 찍었고, 205개 화면 모두 번들 Pretendard가 로드된 상태였다.

| 항목 | 장면(파일 이름 앞부분) | 데이터 |
|---|---|---|
| 가1 구역 탭 폭 | `queue--web-few-all-states-long`, `queue--web-300`, `stats8--8-30-watched_seconds`, `stats0--0-30-watched_seconds`, `folders--web-folders-many`, `folders--web-folders-empty` | 0 · 8 · 300개, 긴 제목 |
| 가2 빈 상태 | `views0--0-medium`, `views5000--5000-no-results`, `recommend--web-recommend-empty`, `queue--web-empty`, `queue--web-rules-empty`, `reelsearch--web-search-empty`, `reelsearch--web-search-none`, `reelsearch--web-reel-empty` | 0개, 결과 0개 |
| 나2 스위치 | `folderwatch--settings-detection-on`, `folderwatch--settings-detection-off`, `folders--web-settings-general`, `backup--web-backup-empty` | 켜짐 · 꺼짐 |
| 나5 입력란 | `reelsearch--web-search-few`, `reelsearch--web-search-long`, `views5000--5000-medium` | 적음 · 긴 텍스트 · 5,000개 |
| 나8 위험 단추 | `dialogs--web-highlights-many-long`, `dialogs--web-tag-manager`, `dialogs--web-video-exclude`(확인은 그대로 채움), `backup--web-backup-preview`, `folders--web-settings-general` | 많음 · 긴 텍스트 |
| 나11 스크롤바 | `recommend--web-recommend-long`, `recommend--web-recommend-full` | 2개 · 160개 |
