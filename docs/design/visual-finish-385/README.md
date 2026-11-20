# 시각 마감 재촬영과 #299 목록 확인 (#385)

시각 마감 묶음 #377~#384가 모두 `main`에 병합되고, 이 브랜치의 진행 막대 트랙 변경(`3729d30`)까지 들어간 화면을 #299와 같은 범위로 다시 찍었다. #299 진단 목록 25개가 고쳐졌는지 이전 화면과 나란히 놓고 확인했다.

- 이전 화면: `docs/design/visual-finish-299/screens/`(1100×720 147장, 최대화 41장)
- 새 화면: `screens/`(1100×720 163장, 최대화 58장, 22MB). 이전 이름 146장 + 새로 더한 장면 17장(아래 5장)
- Windows 실창에서 사람이 볼 항목은 `windows-checklist.md`에 따로 있다.

## 1. 촬영 방법과 한계

| 항목 | 내용 |
|---|---|
| 스크립트 | #299와 같은 `scripts/check_web_*.py --offscreen` 40개 변형(`tools/variants.txt`)을 `scripts/linux_offscreen_check.py`로 3개씩 동시에 돌렸다. |
| 최대화 | `MVM_SHOT_MAX_DIR`: 1100×720 화면을 저장할 때마다 같은 상태에서 창을 1920×1017로 키워 한 장 더 찍었다. |
| 글꼴 | `MVM_SHOT_FONT_LOG`: 저장한 446장 모두 `Pretendard, "Malgun Gothic", sans-serif`, 400·500·600 로드 완료(측정). 대체 글꼴로 찍힌 화면은 없다. |
| 출력 위치 | `.local/s385/<변형>/`. 화면에 임시 폴더 경로가 나오는 장면(폴더 관리·자동 자막 규칙)의 글자 길이를 #299(`.local/…`)와 맞추려고 저장소 `.local` 아래에 찍었다. |
| 고르기 | `tools/select.py`가 #299 `screens/` 이름마다 같은 장면을 찾아 복사한다. 어느 변형에서 왔는지는 `sources.tsv`에 있다. |
| 단언을 늦춘 사본 | 4개 스크립트는 화면과 무관한 단언에서 멈춰 그 뒤 장면을 못 찍었다. `tools/relax.py`가 그 단언만 `print`로 바꾼 사본을 만들어 찍었다(원본 스크립트는 그대로). 아래 표. |
| 다시 찍기 | 저장소 루트에서 `bash docs/design/visual-finish-385/tools/shoot.sh`(약 15분) |
| 실행 환경 | Linux 컨테이너, Qt offscreen, 소프트웨어 그리기. Windows 실창이 아니다. 앱 전역 이벤트 필터를 위젯 단위로 바꿔 거는 우회 때문에 초점·키 단언은 믿을 수 없다. |
| PNG 압축 | `oxipng`·`optipng`가 없어 압축하지 않았다. |

### 단언을 늦춘 사본

| 스크립트 | 멈춘 단언 | 원인 |
|---|---|---|
| `check_web_modified_date.py` 213·260·265행 | 필터 팝오버 높이 ≤ 28rem, 팝오버 안 스크롤 | #381이 팝오버를 화면에 남은 높이까지 쓰게 바꿨다(535px). 단언이 낡았다. |
| `check_web_tag_picker.py` 159행 | 필터 팝오버 높이 ≤ 28rem | 같은 이유 |
| `check_web_preparation.py` 173행 | 첫 `[role=progressbar]`의 `aria-valuenow` = 준비 진행률 | 값이 `0`(대기열 행) ≠ `62`(배너). 선택자가 대기열 행 진행 막대를 먼저 잡는 것으로 추정한다. 화면의 배너 막대는 62%로 그려졌다. #299 때도 같은 자리에서 멈췄다. |
| `check_web_scan_notice.py` 230행 | 검사 실패 문구를 담은 `role=alert/status`가 1개 | 0개였다(두 번 재현). 원인은 확인하지 않았다(6장 후보 6). 같은 실행에서 #299·PR #405가 막혔던 '목록 펼침'은 통과했다. |

### 찍지 못한 장면

| 장면 | 이유 |
|---|---|
| `library-notice--web-many-chips` (#299에 있음) | `check_web_library_place.py`가 그 앞에서 멈춘다. 셸 안내 묶음이 격자 카드(clip 017~027)를 덮는다는 단언이다. #299 때도 같은 스크립트가 중간에 멈췄다. 앞의 3장은 찍혔다. |
| Qt 재생 화면, 트레이 메뉴, 공용 경고 | libmpv가 없고 Windows 실창 전용이다(#299와 같음). |
| 호버·누름, 초점 윤곽선 | offscreen에서 포인터 호버는 세그폴트 원인이고 문서가 초점을 갖지 못한다. |
| 실제 창 최대화(테두리·배율 125·150%·다중 모니터) | 1920×1017 한 크기만 찍었다. |
| `check_web_display_name.py` 긴 제목, `check_web_tag_picker.py` 검사 번들, `check_web_dates.py` 이후 장면 | 각각 Linux 파일 이름 255바이트 제한, `npm.cmd`(Windows 전용), 날짜 글자 단언에서 멈춤. #299와 같다. 긴 제목은 `library_loading --long-content`로 찍었다. |

## 2. 진행 막대

`3729d30`이 트랙을 `bg-muted`에서 `bg-background` + `border border-border`로 바꿨다. 1100×720 새 화면에서 픽셀 값을 읽어 대비를 계산했다(측정).

| 면 | 장면 | 둘레 면 | 트랙 안 `#09090b` / 면 | 트랙 테두리 `#3f3f46` / 면 | 막대 전체 길이 |
|---|---|---|---|---|---|
| 자막 대기열, 카드 면 행 | `screens/1100/queue--web-few-all-states-long.png` | `#18181b` | 1.12:1 | 1.70:1 | 보인다. 길이는 테두리 선이 그린다. |
| 자막 대기열, 선택 행 | 같은 화면 첫 행 | `#3f3f46`(`accent`) | 1.91:1 | 1.00:1(테두리가 면과 같은 색) | 보인다. 어두운 트랙 안쪽이 길이를 그린다. |
| 설정 > 업데이트 진행 | `screens/1100/settings--update-install-2-settings-progress.png` | `#242932`(정보 안내 면) | 1.36:1 | 1.40:1 | 보인다. |
| 자막 준비 배너(셸 안내) | `screens/1100/preparation--03-preparing-one.png` | `#32373f` | 1.66:1 | 1.15:1 | 보인다. |

- 채움 `primary #4f46e5` / 트랙 `#09090b` = **3.16:1**로 3:1을 넘는다. 이전 조합(채움 / `#303036`)은 2.09:1이었다.
- 네 면 모두 1100×720 화면에서 눈으로 막대 끝까지 길이를 읽을 수 있다. 이전 화면에서 카드 면 행 트랙(`#303036` / `#18181b`)은 1.35:1이었고, 새 화면의 테두리는 1.70:1이다.
- **다만 트랙 경계와 둘레 면의 대비는 모든 면에서 1.15~1.91:1로 3:1에 못 미친다.** 막대 길이를 경계만으로 알아봐야 한다고 보면 기준 미달이다. 퍼센트 숫자가 막대 옆에 늘 있다. 테두리는 장식 `border`로 둔다는 결정대로 그대로 둔다(6장 4).

## 3. #299 목록 25개

판정: 고쳐짐(새 화면에서 눈으로 확인) / 일부 / 남음 / 의도적으로 안 함. 근거 경로는 `docs/design/visual-finish-299/screens/` ↔ `docs/design/visual-finish-385/screens/`이고 두 폴더에서 이름이 같다. 이름 하나만 적은 칸은 양쪽에 같은 이름으로 있다.

| 번호 | 요약 | 묶음/PR | 판정 | 근거 화면 | 비고 |
|---|---|---|---|---|---|
| 가1 | 구역 탭 묶음이 페이지 전체 폭 회색 띠 | #377 / #386 | 고쳐짐 | `1100/queue--web-few-all-states-long`, `1100/statistics--8-30-watched_seconds`, `1100/folders-settings--web-folders-many` | 세 화면 모두 내용 폭 |
| 가2 | 빈 상태 네 가지 모양, 다음 동작 없음 | #377 / #386 | 고쳐짐 | `1100/library--0-medium`, `1100/queue--web-empty`, `1100/recommend--web-recommend-empty`, `1100/reel-search--web-search-empty` | 화면 전체가 비면 틀 없이 가운데, 패널 안은 점선 상자. 라이브러리·대기열에 단추. 추천·검색 빈 화면은 단추 없음(머리글 단추·입력란이 있음) |
| 가3 | 인디고 과다(추천 이유 줄, 구역 탭, 대기열 주 단추 2개, 검색 일치) | #378 / #387 | 고쳐짐 | `1100/recommend--web-recommend-full`, `1100/statistics--8-30-watched_seconds`, `1100/queue--web-few-all-states-long`, `1100/reel-search--web-search-few` | ①이유 줄 본문색 ②구역 탭 무채색 ③주 단추 하나 ④일치는 본문색 굵게 + 밑줄. 차트 막대 연한 인디고는 #299에서 범위 밖으로 뺐다. 필터 팝오버 "고른 태그" 칩은 인디고 채움 그대로(6장 후보 5) |
| 가4 | 최대화에서 내용 폭 제한 없음, 추천 카드 커짐 | #380 / #390 | 고쳐짐 | `max/folders-settings--web-settings-general`, `max/queue--web-rules-many`, `max/library--5000-medium`, `max/recommend--web-recommend-full`, `max/reel-search--web-reel-many` | 설정·규칙·모아보기는 왼쪽 1100px 안. 검색 칸 28rem에서 멈춤. 추천은 카드 폭 고정으로 한 줄 아홉 장 가까이, 세로 3.5줄. 모아보기 최대화에서 목록 스크롤바가 화면 가운데(내용 폭 끝)에 온다 |
| 가5 | 상세 패널: 단추 8개가 정보보다 먼저, 정보가 문장 나열 | #381 / #406 | 고쳐짐 | `1100/library--library-24-loaded`, `1100/library--library-24-long-loaded`, `1100/library-detail--detail-many-start` | 제목 → 탭 → 썸네일·정의 목록 → 아래 단추 줄(재생·태그 편집·…). "다른 작업" 메뉴는 열린 화면이 없어 보지 못했다 |
| 가6 | 영상 카드: 카드 속 카드, 빈 띠, 정보 칸 무게, 보통·크게 같은 열 | #381 / #406 | 고쳐짐 | `1100/library--library-24-loaded`, `1100/library--5000-small`, `1100/library-large--library-24-long-large-loaded` | 통계는 라벨 한 줄, "태그 없음", 상세 패널을 연 1100에서 보통 3열·크게 2열 |
| 나1 | 상태 배지가 알약, 태그 칩 구현 네 가지 | #379 / #389 | 고쳐짐 | `1100/library--6-chips-many`, `1100/reel-search--web-reel-long`, `1100/queue--web-few-all-states-long` | 배지 `xs`(4px) 각짐, 칩은 공용 `Chip` 알약. 칩 호버는 보지 못했다. 필터 팝오버 "고른 태그" 칩은 #389가 일부러 남겼다 |
| 나2 | 켜짐·꺼짐을 단추 글자로 | #377 / #386 | 일부 | `1100/folders-settings--web-settings-general`, 새 `1100/folders-watch--settings-detection-on`, 새 `1100/settings--update-install-2-settings-progress` | 자동 감지·백업 썸네일은 스위치. **설정 > 업데이트 "시작할 때 확인: 켜짐"은 단추 글자 그대로**(DESIGN.md Switch 항목과 어긋남, 6장 후보 1) |
| 나3 | 설정 카드 여백·조작 위치 제각각, 번역 값이 가장 큰 글자, 이동 단추가 주 단추 | #384 / #402 | 고쳐짐 | `1100/folders-settings--web-settings-general`, `1100/folders-settings--web-settings-translation`, `1100/folders-settings--web-settings-transcription` | 조작은 제목 줄 오른쪽, 번역은 정의 목록, "자막 대기열 열기"는 윤곽선 |
| 나4 | 키 표시 네 가지, 힌트 자리 다섯 군데 | #379 / #389 | 고쳐짐 | `1100/library--3-menu-default`, `1100/folders-settings--web-settings-keys`, `1100/recommend--web-recommend-full`, `1100/key-guide--24-default-1-library` | 메뉴·키 배치 표·힌트 모두 키 칩. 키 배치 화면의 "예약 키: Ctrl+1~Ctrl+8 · …" 줄과 키 안내 바닥 "Esc · F1 · …" 줄은 글자 그대로다. 키 배치 표 행이 높아져 한 화면에 6.5행 → 5행 |
| 나5 | 입력란 글자 크기(검색 탭 원시 입력란) | #377 / #386 | 고쳐짐 | `1100/reel-search--web-search-few`, `1100/library--library-24-loaded` | 검색 탭은 `Input` `search` variant. 다른 입력란 크기는 이전과 같아 보인다(1100px에서 원래 14px) |
| 나6 | 목록 행 다섯 가지 | #384 / #402 | 고쳐짐 | `1100/dialog-tag--dialog-tags-300`, `1100/dialog--web-highlights-many-long`, `1100/queue--web-rules-many`, `1100/settings--web-backup-many`, `1100/folders-settings--web-folders-many` | 같은 틀·행, 선택은 둥근 면 + 안쪽 링, 태그 대화상자 아래 목록의 굵은 글자·구분선 없어짐 |
| 나7 | 모아보기 지점·구간 시각이 모두 노랑 | #378 / #387 | 고쳐짐 | `1100/reel-search--web-reel-many` | 구간 초록, 지점 노랑. 상세 패널 하이라이트 목록은 찍는 스크립트가 없어 보지 못했다 |
| 나8 | 보조 자리 위험 동작도 채운 분홍 | #377 / #386 | 고쳐짐 | `1100/dialog--web-highlights-many-long`, `1100/folders-settings--web-settings-general` | 하이라이트 삭제·완전 종료가 위험 윤곽선 |
| 나9 | 대기열 진행 막대 길이·색·선택 행 트랙 | #378 / #387, #385 `3729d30` | 고쳐짐 | `1100/queue--web-few-all-states-long` | 퍼센트 칸 고정 폭, 완료 초록·실패 분홍·보류 노랑, 선택 행 트랙 어두움. 트랙 경계 대비는 2장 |
| 나10 | 가장자리 정렬 16·20·24px, 라이브러리 왼쪽 빈 기둥 | #381 / #406, #382 / #403 | 고쳐짐 | `1100/reel-search--web-reel-many`, `1100/recommend--web-recommend-full`, `1100/library--library-24-loaded` | 목록·추천 줄 왼쪽이 머리글과 같은 자리, 폴더 패널 단추는 툴바 맨 앞 |
| 나11 | 추천 줄 스크롤바 화살표 흔적, 상세 패널·격자 스크롤바 나란함 | #377 / #386 | 일부 | `1100/recommend--web-recommend-long`, `1100/library--library-24-long-loaded` | 추천 줄은 앱 공통 스크롤바(화살표 없음). **격자 스크롤바와 상세 패널 스크롤바가 패널 테두리를 사이에 두고 그대로 나란하다**(6장 후보 3) |
| 다1 | 라이브러리 툴바 선이 많음, 칩 없을 때 빈 줄 48px | #381 / #406 | 고쳐짐 | `1100/library--library-24-loaded` | 정렬 방향은 테두리 없는 아이콘 단추(테두리 조작 6 → 5), 칩 줄 2.25 → 2rem. 칩 줄 자리 예약은 규칙대로 남는다 |
| 다2 | 필터 팝오버가 짧아 잘림, 라벨 정렬 | #381 / #406 | 고쳐짐 | `1100/library--5000-filter-panel`, `max/library--5000-filter-panel`, 새 `1100/library--6-panel-default` | 남은 높이까지 쓰고 두 열 격자, "조건 모두 지우기" 줄 고정 |
| 다3 | 폴더 관리: 안내가 목록을 밀어 2.5행, 셸 안내가 페이지 안내를 덮음, 최소 길이 카드 85px | #383 / #405 | 일부 | `1100/folders-notice--web-mixed-open`, 새 `1100/folders-notice--web-failed`, `1100/folders-settings--web-folders-many` | 안내는 목록 위 떠 있는 띠, 섞인 안내에서 목록 약 4행. 셸 안내 묶음은 페이지 안내를 피한다. **그 대신 왼쪽 아래로 가서 "새 영상의 최소 길이" 카드의 제목·설명을 덮는다. 최소 길이 카드 자리는 그대로**(6장 후보 2) |
| 다4 | 모아보기·검색 긴 제목 3줄, 상태 문장 김 | #382 / #403 | 고쳐짐 | `1100/reel-search--web-reel-long`, `1100/reel-search--web-search-onscreen-long` | 제목 두 줄 말줄임, 상태 문장 짧아짐. 툴팁은 보지 못했다 |
| 다5 | 추천은 시청 상태를 글자로 | #382 / #403 | 고쳐짐 | `1100/recommend--web-recommend-full` | 라이브러리와 같은 배지 |
| 다6 | 통계 큰 숫자가 제목보다 작음, 머리글 세 줄 | #383 / #405 | 고쳐짐 | `1100/statistics--8-30-watched_seconds`, `1100/statistics--50000-30-watched_seconds`, 새 `1100/statistics--50000-placeholder` | 숫자 30px(제목 24px), 1100에서 한 줄 3장, 머리글 두 줄 |
| 다7 | 하이라이트 대화상자 메모가 흐린 글자 | #384 / #402 | 고쳐짐 | `1100/dialog--web-highlights-many-long` | 본문 글자색 |
| 다8 | 번역 대화상자 단추 크기·고스트 섞임, 안쪽 스크롤 | #384 / #402 | 고쳐짐 | `1100/dialog--web-translation` | 양식 안 단추가 작은 윤곽선 하나로. #299 제안대로 구역 접기는 하지 않아 1100×720에서 안쪽 스크롤은 남는다 |

**집계:** 고쳐짐 22, 일부 3(나2, 나11, 다3), 남음 0, 의도적으로 안 함 0.

호버·초점·키 동작(칩 호버, 상세 패널 "다른 작업" 메뉴, 스위치 키 조작, 구역 탭 선택과 초점이 함께 보이는 모습, 툴팁)은 이 촬영으로 확인하지 못했다. `windows-checklist.md`에 있다.

## 4. 사용자 결정 4개가 정해진 방식

| #299 결정 | 정해진 것 | 어디 |
|---|---|---|
| 1. 가3-② 구역 탭 선택색 | 무채색. 선택 탭은 묶음(`muted`)에서 파낸 `background` 면 + `foreground` 글자 + `input` 경계 1px | PR #387, `DESIGN.md` `tab-section-selected` |
| 2. 가4 추천 줄 "한 줄 다섯 장" | 카드 폭 고정. `layout.recommendation-card-width` 12.65rem(PR #390) → 12.85rem(PR #403, 가장자리 정렬 뒤 다섯 장이 꼭 맞게). 최대화에서 장수가 늘어난다 | `DESIGN.md` Layout "추천 줄" |
| 3. 다6 `display` 단계 | 키움. 1.25rem / 1.75rem → 1.875rem / 2.25rem, 자간 -0.02em | PR #405, `DESIGN.md` Typography |
| 4. 나1 배지·칩 | 상태 배지는 각지게(`--radius-xs` 0.25rem 새 단계), 태그·조건 칩은 알약(공용 `Chip`) | PR #389, `DESIGN.md` Shapes·Components |

## 5. 새로 더한 장면

| 장면 | 왜 |
|---|---|
| `preparation--03-preparing-one`, `preparation--04-preparing-300-long-title`, `preparation--06-failed-detail` | 자막 준비 진행 막대. #299 때는 스크립트가 그 앞에서 멈췄다 |
| `settings--update-install-2-settings-progress` | 설정 화면 안 업데이트 진행 막대 |
| `settings--web-backup-progress`, `settings--update-settings-available`, `settings--web-settings-recommend-changed` | #384 전후 화면과 같은 장면 |
| `folders-notice--web-failed`, `web-mixed`, `web-scanning`, `web-subtitle-one` | #383의 폴더 안내 띠·검사 중 막대 |
| `folders-watch--settings-detection-on` | 스위치 켜짐 |
| `library--6-panel-default` | 두 열 필터 팝오버 |
| `library--0-large` | 0개 + 크게 |
| `statistics--50000-placeholder`, `statistics--50000-365-inventory`, `statistics--8-7-watched_seconds` | `display` 숫자의 자리 표시·최장 값·7일 |

## 6. 남은 항목 (이슈로 등록함)

1. **설정 > 업데이트 "시작할 때 확인"을 스위치로 바꾸기** → #411
   - 무엇: 켜짐·꺼짐 설정 하나가 아직 "시작할 때 확인: 켜짐" 단추 글자다. DESIGN.md Switch 항목("상태를 단추 글자로 보이지 않는다")과 어긋난다. 나2의 남은 곳.
   - 근거: `screens/1100/settings--update-install-2-settings-progress.png`, `screens/1100/settings--update-1-before.png`
   - 고칠 자리: `frontend/src/components/update-settings.tsx` 94행(`settings-update-automatic-toggle`, `aria-pressed`) → `ui/switch.tsx`

2. **폴더 관리에서 셸 안내 묶음이 "새 영상의 최소 길이" 카드 글자를 덮지 않게** → #412
   - 무엇: 페이지 안내가 띠로 옮겨진 뒤 셸 안내 묶음이 왼쪽 아래로 가는데, 그 자리의 최소 길이 카드 제목·설명을 덮는다. 최소 길이 카드는 설정 > 일반에도 있고 목록 아래 자리를 늘 차지한다(#299 다3의 남은 부분).
   - 근거: `screens/1100/folders-notice--web-mixed-open.png`, `screens/1100/folders-notice--web-failed.png`
   - 고칠 자리: `frontend/src/components/ui/notice.tsx` `NoticeLayer` 모서리 판단(`fixedControls`·`pageNotices`가 카드 글자를 피할 대상에 넣지 않음), `pages/FoldersPage.tsx` 최소 길이 카드 자리

3. **라이브러리 격자 스크롤바와 상세 패널 스크롤바가 나란히 보이는 것 정리** → #413
   - 무엇: 상세 패널 내용이 넘치면 스크롤바 두 개가 패널 테두리 하나를 사이에 두고 붙어 보인다(#299 나11의 남은 부분).
   - 근거: `screens/1100/library--library-24-long-loaded.png`, `screens/1100/library-large--library-24-long-large-loaded.png`
   - 고칠 자리: `frontend/src/pages/LibraryPage.tsx` 격자·패널 사이 간격 또는 `components/detail-panel.tsx` 스크롤 영역(넘칠 때만 손잡이)

4. ~~진행 막대 트랙 경계의 대비를 정할지~~ **정함: 그대로 둔다.** #385 결정 댓글은 트랙 테두리를 장식 `border`(WCAG 1.4.11 예외)로 두고, 막대 길이가 읽히지 않을 때만 결정을 다시 열기로 했다. 네 면 모두 길이가 읽히고(2장), 정보를 담는 경계인 채움/트랙은 3.16:1이며 퍼센트 숫자가 옆에 늘 있다. 이슈로 올리지 않는다. Windows 실창에서 다시 본다(`windows-checklist.md` 6장).

5. **필터 팝오버 "고른 태그" 칩을 공용 Chip으로** → #414
   - 무엇: 필터 팝오버 안 고른 태그가 인디고 채움 큰 알약이라 One Beam(한 화면 인디고 하나)과 공용 칩 규칙에서 벗어난다. #389가 "고르기 조작의 일부"라며 남겼다.
   - 근거: `screens/1100/library--5000-filter-panel.png`, `screens/max/library--5000-filter-panel.png`
   - 고칠 자리: `frontend/src/components/tag-picker.tsx`

6. **폴더 검사 실패가 live region으로 알려지는지 확인** → #415
   - 무엇: `check_web_scan_notice.py` 230행이 검사 실패 문구를 담은 `role=alert/status`를 0개로 센다(두 번 재현, 기대 1). 화면에는 띠(`role=note`)와 셸 안내 두 곳에 같은 문구가 보인다. Linux 우회 탓인지 제품 문제인지 확인하지 않았다.
   - 근거: `screens/1100/folders-notice--web-failed.png`, `tools/relax.py` 사본 실행 로그의 `live 0.0`
   - 고칠 자리: `frontend/src/App.tsx` 105~112행 셸 안내, `components/scan-report.tsx` 51행(`role: "note"`), Windows에서 원본 스크립트 실행

7. **검사 스크립트의 낡은 단언 맞추기** → #416
   - 무엇: #381 뒤 필터 팝오버 높이 28rem 한도가 낡아 `check_web_modified_date.py`(213·260·265행)와 `check_web_tag_picker.py`(159행)가 장면을 찍기 전에 멈춘다. `check_web_preparation.py` 173행은 첫 `[role=progressbar]`가 대기열 행을 잡는 것으로 추정한다.
   - 근거: 1장 "단언을 늦춘 사본" 표, `tools/relax.py`
   - 고칠 자리: 위 세 스크립트

8. **DESIGN.md 대조에서 나온 코드 쪽 어긋남 정리** → #417
   - 무엇: DESIGN.md를 코드와 대조하며(#385) 문서가 아니라 코드를 맞춰야 할 곳이 나왔다. 하이라이트 시각 글자가 세 곳에서 다르다(`highlight-panel.tsx` `text-label-strong`, `dialogs/dialog-parts.tsx` `font-mono text-label`, `reel-search-parts.tsx` 역할 없음). Qt 재생 경고 글자가 `highlight-open`을 빌려 쓴다(`theme.py`, Meaning-Only 규칙상 `status-warning`). 하이라이트 패널 행은 `selectableItem`을 쓰지 않아 호버가 없다. 13개 파일이 전역 규칙과 같은 `focus-visible:outline-*`를 다시 적는다. `aria-invalid:ring-destructive/20`은 링 폭이 없어 그려지지 않는다(`ui/input.tsx`, `ui/button.tsx`). `dialog-parts.tsx` `TextArea`는 `input` 30% 면이 없다. 쓰지 않는 부품(`ui/badge.tsx`, `page-parts.tsx` `ListItem`·`SectionTitle`, `ContextMenuSubContent`)이 남아 있다.
   - 근거: DESIGN.md Typography·Colors·Components 절과 위 파일
   - 고칠 자리: 위 파일들. 대부분 S 크기다.

## 7. 스크린샷 찾는 법

`screens/1100/`(1100×720)과 `screens/max/`(1920×1017)에 `<영역>--<원래 이름>.png`로 있다. 영역 접두어와 데이터는 #299 README 6장과 같다. 이전 화면과 같은 이름이면 같은 장면이다.

| 영역 접두어 | 내용 |
|---|---|
| `library`, `library-small`, `library-large`, `library-detail`, `library-notice`, `library-tagpicker` | 라이브러리 격자·카드 크기·상세 패널·필터·칩·폴더 패널·안내 |
| `recommend` | 추천 |
| `reel-search` | 모아보기·검색 |
| `queue` | 자막 대기열 |
| `statistics` | 통계 |
| `folders-settings`, `folders-notice`, `folders-watch` | 폴더 관리와 설정(일반·키 배치·받아쓰기·번역) |
| `settings` | 설정의 추천·백업·업데이트·버전 정보 |
| `dialog`, `dialog-tag`, `dialog-random` | 대화상자와 태그·무작위 재생 범위 |
| `key-guide` | 키 안내 |
| `preparation` | 자막 준비 대화상자·배너 |

`sources.tsv`는 각 파일이 어느 변형(`tools/variants.txt`의 첫 칸)에서 왔는지 적는다.
