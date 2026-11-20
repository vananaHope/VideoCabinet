# 시각 마감 5: 라이브러리 전후 화면 (#381)

Linux 컨테이너의 Qt offscreen(소프트웨어 그리기)에서 `scripts/check_web_library_loading.py`·`check_web_library_views.py`로 찍었다. Windows 실창이 아니다.

- `before/`: 변경 전(main `575603a`), 1100×720.
- `after/`: 변경 후, 1100×720. `max-`로 시작하는 파일은 같은 상태를 1920×1017(최대화 근사)로 찍은 것이다.

| 장면 | 파일 |
|---|---|
| 긴 제목·태그 24개, 작게·보통·크게 | `loading-small-…`, `loading-medium-…`, `loading-large-…` |
| 짧은 제목 24개 | `loading-plain-library-24-loaded.png` |
| 5,000개 보통 · 폴더 패널(깊고 긴 폴더) · 필터 팝오버 | `views-5000-medium.png`, `views-5000-folders-deep-long.png`, `views-5000-filter-panel.png` |
| 영상 0개 | `after/loading-zero-library-0-loaded.png` |
