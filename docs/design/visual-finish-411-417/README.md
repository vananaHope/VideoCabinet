# 시각 마감 잔여 이슈 #411~#414·#416·#417 전후 화면

Linux 컨테이너 Qt offscreen 1100×720에서 찍었다(`scripts/linux_offscreen_check.py`). Windows 실창이 아니다.
`before-*`는 이 수정 전(대부분 `docs/design/visual-finish-385/screens/1100/`의 같은 장면), `after-*`는 수정 뒤,
`compare-*`는 왼쪽이 전, 오른쪽이 후인 잘라 붙인 사진이다.

| 이슈 | 사진 |
|---|---|
| #411 업데이트 '시작할 때 확인' 스위치 | `before-411-update.png`, `after-411-update-on.png`, `after-411-update-off.png` |
| #412 폴더 관리 안내 묶음과 최소 길이 카드 | `before/after-412-folders-mixed-open.png`, `before/after-412-folders-failed.png` |
| #413 격자·상세 패널 스크롤바 간격 | `before/after-413-library-long.png`, `before/after-413-library-long-large.png`, `compare-413-library-long-crop.png` |
| #414 태그 고르기 Chip·무채색 선택 | `compare-414-tags-picked.png`, `compare-414-tags-frequent.png`, `after-414-tags-frequent.png` |
| #417 하이라이트 시각·패널 행·TextArea | `compare-417-highlight-panel.png`, `compare-417-dialog-highlights.png`, `compare-417-reel.png`, `compare-417-dialog-textarea.png`, `after-417-highlight-panel.png` |

`compare-417-highlight-panel.png`은 하이라이트를 DB에 직접 넣어 찍어 탭 머리의 개수(0)가 갱신되지 않았다. 행 모양만 본다.
