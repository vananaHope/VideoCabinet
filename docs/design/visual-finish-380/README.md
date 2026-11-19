# 시각 마감 4 전후 스크린샷 (#380)

- `max-before/`는 `main`(`aaeb529`)의 최대화(1920×1017) 화면, `max-after/`는 이 변경의 최대화 화면이다.
- `1100-before/`는 묶음 1(#377, PR #386)까지 적용한 1100×720 화면, `1100-after/`는 이 변경의 1100×720 화면이다. 기본 창의 모양이 같은지 보는 쌍이다.

같은 이름이 같은 장면이다. Linux offscreen에서 `scripts/linux_offscreen_check.py`(`MVM_SHOT_MAX_DIR`)로 찍었고, 기록한 화면 모두 번들 Pretendard가 로드된 상태였다.

| 항목 | 장면(파일 이름 앞부분) | 데이터 |
|---|---|---|
| 추천 줄 카드 폭 고정 | `recommend--web-recommend-full`, `recommend--web-recommend-few`, `recommend--web-recommend-long`, `recommend--web-recommend-placeholder` | 적음 · 160개 · 긴 텍스트 · 자리 표시 |
| 내용 최대 폭: 설정 | `folders--web-settings-general`, `folders--web-settings-keys`, `folders--web-settings-translation`, `backup--web-backup-empty` | — |
| 내용 최대 폭: 자동 자막 규칙 | `queue--web-rules-many`(처리 상태 표 `queue--web-few-all-states-long`은 제한하지 않음) | 4 · 8개 |
| 내용 최대 폭: 모아보기·검색 | `reelsearch--web-reel-many`, `reelsearch--web-reel-long`, `reelsearch--web-search-few`, `reelsearch--web-search-long` | 2 · 503개 · 긴 텍스트 |
| 라이브러리 검색 칸 | `views5000--5000-medium`, `views5000--5000-filter-panel` | 5,000개 |
