# Windows 실창 확인 목록 (#385)

시각 마감 묶음(#377~#384)과 #385 진행 막대 변경 뒤, Linux offscreen 스크린샷으로 볼 수 없는 것을 사람이 Windows 실창에서 확인한다. 데스크톱을 쓰는 검사는 한 번에 하나만 돌린다(`~/.agent-orchestra/bin/desktop_lock.py run ... -- <명령>`, 스크립트가 없으면 `<명령>`만).

## 1. 전체 pytest (Release 직전, #292 Further Notes)

- PR과 `main` push마다 GitHub Actions `Windows tests`가 전체 pytest를 10조각으로 돈다(실창·CUDA 제외). Release 전에는 `main`의 마지막 실행이 초록인지 본다.
- 로컬 Windows에서 한 번에 돌릴 때: `powershell -ExecutionPolicy Bypass -File scripts/run_tests.ps1`(`pytest -n auto -q`). 실창 검사까지 포함하려면 `MVM_REAL_WINDOW_TESTS=1`을 켜고 데스크톱 잠금 안에서 돌린다.
- 이번 브랜치에서 새로 생긴 테스트: `tests/test_design_doc.py`(문서 값 = 토큰), `tests/test_web_queue_page.py::test_progress_fill_stands_out_from_track_on_selected_and_resting_rows`(웹 셸이라 Windows에서만 실행).

## 2. Qt 화면의 글꼴 (Pretendard 등록)

- [ ] 재생 화면 조작 줄·머리글 제목·하이라이트 패널 글자가 웹 화면과 같은 Pretendard다(맑은 고딕으로 대체되면 앱 로그에 남는다).
- [ ] 트레이 메뉴 글자와 현재 항목 면(`accent`).
- [ ] 공용 오류·종료 경고(`native_dialogs`)의 글자와 단추.
- [ ] 재생 기호(⏮ ⏸ ⏭)가 컬러 이모지가 아니라 단색 기호다.
- 명령: `scripts/check_playback_controls.py --real`, `scripts/check_onscreen_playback.py --real --output <임시 폴더>`.

## 3. 호버·누름

offscreen에서는 포인터 호버가 세그폴트 원인이라 찍지 않았다.

- [ ] 영상·추천 카드, 검색·모아보기 결과, 대기열 행의 호버가 `popover` 면이고 안쪽 배지·태그 칩이 묻히지 않는다.
- [ ] 목록 행·탭·고스트 단추의 호버 `muted`, 선택 `accent`가 구별된다.
- [ ] 누르는 동안 조작 요소가 0.97로 작아지고, 영역 밖에서 놓으면 취소된다.
- [ ] 재생 화면 조작 단추 호버(#409에서 다른 창이 가로채던 문제 수정).

## 4. 배율과 최대화

offscreen 최대화는 1920×1017 한 크기 근사다.

- [ ] 배율 100·125·150%에서 최대화: 설정·모아보기·검색·대기열 규칙이 내용 최대 폭(68.75rem)에서 왼쪽에 붙고, 추천 줄은 카드 폭이 고정된 채 장수만 는다.
- [ ] 다중 모니터(배율이 다른 두 화면)로 창을 옮긴 뒤 최대화·복원해도 글자가 흐려지지 않고 배치가 맞다.
- [ ] 1100×720 기본 창에서 모든 탭에 바깥 스크롤이 없다.

## 5. 탭·단축키·mpv 왕복·대화상자·트레이

- [ ] `Ctrl+1`~`Ctrl+8` 탭 이동, F1 키 안내, 긴급 탈출 뒤 트레이로 다시 열기.
- [ ] 라이브러리 → Enter로 재생 → Esc로 목록 복귀(선택 카드 위치 유지). 명령: `scripts/check_return_transition.py`, `scripts/check_video_click.py`.
- [ ] 대표 대화상자(태그 편집, 하이라이트, 번역, 확인 창)의 초점 이동·Esc 닫기·단추 줄 위치.
- [ ] 트레이 메뉴 열기·항목 실행·종료 확인.

## 6. 진행 막대 (#385 변경)

- [ ] 자막 대기열에서 진행 중인 행의 막대 전체 길이가 트랙 테두리로 읽힌다(쉬는 행·선택 행 둘 다).
- [ ] 설정 > 업데이트 내려받기 진행, 자막 기능 준비 진행 막대도 같은 모양이다.
- [ ] 실창에서 테두리가 있어도 길이가 안 읽히면 #385 결정 댓글대로 결정을 다시 연다.
