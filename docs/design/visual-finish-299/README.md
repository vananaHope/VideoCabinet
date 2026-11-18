# 시각 마감 진단 (#299)

상위 스펙 #292의 마지막 하위 이슈 #299의 1~3단계 준비 자료다. 기반 조각(#294 글꼴, #295 면·대비, #296 대화상자 틀, #297 Qt 글꼴, #298 글자 단계)과 #268(누름·초점)이 모두 `main`에 병합된 뒤(`aaeb529`)의 화면을 찍어 진단했다.

- 이 문서는 **진단과 제안**이다. 제품 코드는 고치지 않았다.
- 고칠 항목과 순서는 사용자 확인 뒤에 정한다(#299 3단계). 하위 이슈 등록은 그다음이다(4단계).
- 기준: `PRODUCT.md`, `DESIGN.md`(북극성 "조용한 상영실", One Beam · Meaning-Only Color · Lit Ladder · Flat-At-Rest · Tabular Numbers · Body-Is-Small · Reserved Space · Token Source), `docs/agents/common-findings.md` 3·4번, #292의 User Stories.

## 1. 진단 방법과 한계

| 항목 | 내용 |
|---|---|
| 도구 | **Impeccable 스킬 없이 했다.** 이 환경에는 Impeccable `critique`·`audit` 스킬이 설치돼 있지 않다(`skills-lock.json`에 없음). 저장소의 `.impeccable/design.json`과 `DESIGN.md` 규칙을 기준으로 스크린샷을 한 장씩 열어 보고, 같은 형식(휴리스틱 점수 → 잘된 점 → 우선순위 문제 / audit 5개 차원)으로 적었다. 자동 감지기(`impeccable detect`)는 돌리지 않았다. |
| 쓰지 않은 흐름 | new-work · redesign, `bolder` · `overdrive` · `delight`. 현재 체계를 다듬는 제안만 있다. |
| 스크린샷 | 기존 `scripts/check_web_*.py --offscreen` 40개 변형을 그대로 실행해 얻었다. 1100×720 147장, 최대화 41장을 골라 `screens/`에 넣었다(전체는 각 400여 장). |
| 최대화 | 스크립트가 1100×720 화면을 저장할 때마다 같은 상태에서 창을 1920×1017(FHD 100% 배율 최대화 창의 안쪽 크기 근사)로 키워 한 장 더 찍었다. |
| 글꼴 | 저장되는 화면마다 웹 문서에서 `getComputedStyle(body).fontFamily`와 `document.fonts.check()`(400·500·600)를 기록했다. **416번 모두 `Pretendard, "Malgun Gothic", sans-serif`이고 세 굵기가 로드된 상태**였다. 대체 글꼴로 찍힌 화면은 없다. |
| 실행 환경 | Linux 컨테이너, Qt offscreen, 소프트웨어 그리기. Windows 실창이 아니다. |

### 이 환경에서 안 된 것

- **웹 셸 세그폴트:** Linux offscreen에서는 `MainWindow`의 앱 전역 이벤트 필터로 QWebEngine 안쪽 QQuick 객체가 넘어오면 PySide6가 죽는다(`tests/conftest.py`가 같은 이유로 웹 셸 테스트를 건너뛴다). 제품 코드는 그대로 두고, 실행 보조 스크립트에서 전역 필터를 위젯 단위 필터로 바꿔 걸어 찍었다. 이 때문에 초점·키 전달에 기대는 단언 일부가 실패했다(아래 표). 실패 전까지 저장된 화면은 정상이다.
- **`WINDIR`·맑은 고딕:** 스크립트가 offscreen에서 `%WINDIR%\Fonts\malgun.ttf`를 읽는다. Linux에는 없어 임시 폴더로 대신했다. 대체 글꼴(맑은 고딕)은 등록되지 않았지만, 화면 글자는 모두 번들 Pretendard로 그려졌다.
- **찍지 못한 화면**

| 화면 | 이유 |
|---|---|
| Qt 재생 화면(조작 줄·하이라이트 패널·키 안내), 트레이 메뉴, 공용 오류·종료 경고 | libmpv가 없고 Windows 실창 전용이다. `check_playback_controls.py` 등은 돌리지 않았다. #297의 글꼴 적용은 사람이 실창에서 확인해야 한다. |
| 최대화의 "실제" 모습 | 창 테두리·배율(125·150%)·다중 모니터는 offscreen으로 볼 수 없다. 1920×1017 한 크기만 찍었다. |
| 호버·누름 상태 | offscreen에서 포인터 호버가 세그폴트 원인이라 찍지 않았다(#268에서 이미 맞춘 영역이다). |
| `check_web_tag_picker.py`의 검사 번들 화면 | `npm.cmd`를 부른다(Windows 전용). 그 앞의 11장은 찍혔다. |
| `check_web_display_name.py`의 긴 제목 장면 | 합성 파일 이름이 Linux 파일 이름 길이 제한(255바이트)을 넘는다. 긴 제목은 다른 스크립트(`library_loading --long-content`)로 찍었다. |
| `check_web_refinement.py`, `check_web_startup_scan.py`, `check_web_random_shortcut.py`, `check_web_random_continuous.py`, `check_web_library.py` | `--output` 인수가 없거나 `--source` 실제 영상·재생 화면이 필요해 돌리지 않았다. 같은 탭은 다른 스크립트로 찍었다. |

- **중간에 실패한 스크립트(스크린샷은 실패 전까지 저장됨):** `dialogs`(22장 뒤 초점 대기 시간 초과), `folders_settings`(10장 뒤 키 캡처 대화상자), `backup`, `scan_notice`, `dates`, `external_subtitles`, `preparation`, `library_random`, `library_random_tags`, `random_scope`, `library_place`. 모두 초점·키 입력 단언이고 화면 문제가 아니다.

## 2. Critique

### 전체 인상

기반은 탄탄하다. 어두운 무채색 면 단계, Pretendard, 역할 글자 토큰, 한 가지 초점 윤곽선이 모든 탭에 일관되게 들어가 있고 `npm run lint`(@shadcn/lint 6규칙)와 토큰 생성 검사(`--check`)가 통과한다. "상용 앱처럼 보이지 않는" 인상은 색이나 글꼴이 아니라 **부품이 화면마다 조금씩 다른 것**과 **윤곽선·상자가 많은 것**, 그리고 **최대화에서 폭 제한이 없는 것**에서 나온다.

가장 큰 기회 세 가지:

1. 같은 역할인데 모양이 여러 개인 부품을 하나로 모으기(빈 상태 4가지, 태그 칩 4가지, 키 표시 4가지, 목록 행 5가지).
2. 인디고와 윤곽선을 덜어 내기. 지금은 한 화면에 인디고가 3~4군데, 3:1 테두리 상자가 10개 넘게 보인다. 영상보다 틀이 먼저 보인다.
3. 최대화 폭 다루기. 설정·양식·목록이 1,900px까지 늘어나 라벨과 조작이 화면 양 끝으로 갈라진다.

### 휴리스틱 점수 (Nielsen 10, 각 0~4)

| # | 휴리스틱 | 점수 | 근거 |
|---|---|---|---|
| 1 | 시스템 상태 보이기 | 3 | 안내 위계·진행 막대·자리 표시가 일관된다. 대기열 진행 막대는 상태와 무관하게 같은 색이다. |
| 2 | 현실 세계와의 일치 | 3 | 용어집을 따른다. 켜짐/꺼짐을 단추 글자로 보여 주는 곳이 있다. |
| 3 | 사용자 제어와 자유 | 3 | 취소·되돌리기·Esc가 일관된다. |
| 4 | 일관성과 표준 | 2 | 빈 상태·칩·키 표시·목록 행·구역 탭 폭이 화면마다 다르다. 이 진단의 중심이다. |
| 5 | 오류 예방 | 3 | 위험 동작 확인이 일관된다. |
| 6 | 기억보다 인식 | 3 | 키 안내(F1)가 좋다. 페이지 안 키 힌트 문장은 위치가 제각각이다. |
| 7 | 유연성과 효율 | 4 | 키보드만으로 끝까지 간다. |
| 8 | 미적·간결한 디자인 | 2 | 윤곽선 단추 벽, 카드 속 카드, 전체 폭 회색 띠, 인디고 과다. |
| 9 | 오류 인식·복구 | 3 | 안내 문구와 다시 시도가 있다. |
| 10 | 도움말 | 3 | 빈 상태가 설명은 주지만 다음 동작 단추가 없다. |
| | **합계** | **29 / 40** | 기능은 상용 수준, 겉모습 일관성이 아래로 당긴다. |

### 잘된 점 (건드리지 않는다)

- 면 단계(`background` → `card` → `popover`)와 호버·선택 구분이 모든 탭에서 같다.
- 초점 윤곽선과 선택 링이 한 가지 모양이다(#268).
- 대화상자 틀(제목·설명·단추 줄 위치)이 22개 장면에서 같다(#296).
- 키 안내 대화상자는 `Kbd`와 표가 정돈돼 있다.
- 안내(Notice)의 색·아이콘·접기 동작이 일관된다.
- 숫자는 대부분 `tabular-nums`다.
- 기본 글자 14px 밀도가 유지된다.

### 인지 부하·감정

- 라이브러리 상세 패널은 영상을 고르자마자 단추 8개가 먼저 보인다. 가장 자주 쓰는 "재생" 하나만 색이 있지만, 나머지 7개가 같은 무게의 윤곽선이라 훑기 어렵다.
- 통계는 한 화면에 구역 탭 묶음이 3개(기간·구역·차트 기준)라 "지금 무엇을 고른 상태인지"를 세 번 읽어야 한다.
- 빈 화면이 큰 점선 상자라 "아직 만들다 만 자리"처럼 보인다. 처음 설치한 사람이 보는 첫 화면이 이 모양이다.

## 3. Audit

| 차원 | 점수(0~4) | 요약 |
|---|---|---|
| 접근성 | 3 | 대비는 #295에서 맞췄고 `tests/test_web_contrast.py`가 지킨다(이 환경에서는 건너뜀). 초점 한 가지. 진행 막대가 색만으로 상태를 구별하지 않는 점은 좋지만 실패도 같은 색이라 정보가 없다. 검색 일치 표시가 색+굵기뿐이다. |
| 성능 | 측정 안 함 | offscreen 소프트웨어 그리기라 재지 않았다. 이 진단의 제안은 배치·색·부품 변경이고 가상 격자 계산을 건드리지 않는다. |
| 테마·토큰 | 3 | lint 통과, 원시 색·임의 값 없음. 다만 lint가 못 잡는 이탈이 있다: 공용 부품 대신 원시 `<input>`·`<span>`에 직접 스타일(검색 입력란, 태그 칩 3곳, 체크박스·라디오 4곳), shadcn 기본값이 남은 곳(`Badge` 알약, 메뉴 단축키 `tracking-widest`, 입력란 `text-base`). |
| 반응(창 크기) | 2 | 1100×720은 잘림 없이 맞는다. 최대화는 내용 폭 제한이 없어 늘어나기만 한다. 1100에서 상세 패널이 열리면 카드가 2열 1.3줄, 폴더 관리에 안내가 쌓이면 목록이 2.5행이다(common-findings 3번). |
| 안티 패턴 | 3 | 그라데이션·글로우·유리 효과 없음. 남은 것: 카드 속 카드(영상 카드의 시청 통계 상자), 윤곽선 단추 벽, 큰 점선 빈 상자, 전체 폭 회색 띠. |
| **합계** | **11 / 16** (성능 제외) | |

## 4. 고칠 곳 목록

크기: **S** 한 파일·variant 하나, **M** 부품 하나와 쓰는 화면 2~4곳, **L** 여러 부품·배치 토큰. 순서는 권장 순서다. 스크린샷 경로는 `screens/` 기준이다.

### 가 — 가장 먼저 눈에 띄는 것

| 번호 | 어디 | 무엇이 문제인가 | 근거 | 고칠 자리 | 크기 |
|---|---|---|---|---|---|
| 가1 | 구역 탭 묶음 (자막 대기열·통계·폴더 관리) | 탭이 2~3개뿐인데 묶음 면이 페이지 전체 폭이라 굵은 회색 띠처럼 보인다. 같은 variant가 통계 오른쪽 위(기간)·차트 안에서는 내용 폭이다. | `1100/queue--web-few-all-states-long.png`, `1100/statistics--8-30-watched_seconds.png`, `1100/folders-settings--web-folders-many.png` | `components/page-parts.tsx` `tabList` `section` variant(내용 폭으로) | S |
| 가2 | 빈 상태 (모든 탭) | 모양이 네 가지다. 라이브러리는 틀 없는 가운데 글자, 추천·대기열은 페이지를 다 채우는 점선 상자, 검색·모아보기는 위쪽 작은 점선 상자, 상세 패널은 흐린 제목의 점선 상자. 다음 동작 단추가 하나도 없다(#292 스토리 24). | `1100/library--0-medium.png`, `1100/recommend--web-recommend-empty.png`, `1100/queue--web-empty.png`, `1100/reel-search--web-search-empty.png` | `page-parts.tsx` `EmptyState`(variant 정리, `action` 채우기), `library-grid.tsx` `GridMessage`를 `EmptyState`로 | M |
| 가3 | 인디고 쓰임 (추천·통계·대기열·검색) | One Beam 규칙과 어긋나는 곳. ① 추천 카드마다 이유 줄이 인디고 글자다(한 화면에 10줄 이상). ② 통계는 인디고 구역 탭이 한 화면에 3묶음이고 차트 막대도 인디고 계열이다. ③ 대기열 아래 주 단추가 2개다. ④ 검색 일치 글자가 인디고다. | `1100/recommend--web-recommend-full.png`, `1100/statistics--8-30-watched_seconds.png`, `1100/queue--web-few-all-states-long.png`, `1100/reel-search--web-search-few.png` | `recommendation-card.tsx`(이유 줄 `muted-foreground`), `QueuePage.tsx`(주 단추 하나), `reel-search-parts.tsx` `mark`. **②는 구역 탭 선택색을 `primary`에서 무채색으로 바꾸는 것이라 DESIGN.md 규칙 변경이다 → 사용자 결정 필요** | S (②는 M) |
| 가4 | 최대화 폭 (설정·대기열 규칙·모아보기·검색·라이브러리 툴바·추천) | 내용 최대 폭이 없다. 설정 카드는 라벨과 조작이 1,400px 떨어지고, 대기열 규칙의 선택 목록 하나가 페이지 전체 폭이며, 라이브러리 제목 검색 칸이 1,150px로 늘어난다. 추천은 "한 줄 다섯 장" 규칙 때문에 카드가 366px로 커져 2.5줄만 보인다. | `max/folders-settings--web-settings-general.png`, `max/queue--web-rules-many.png`, `max/library--5000-medium.png`, `max/recommend--web-recommend-full.png`, `max/reel-search--web-reel-many.png` | `web_tokens.json` `layout`에 내용 최대 폭 토큰 추가 → 설정·양식·읽는 목록에 적용. 검색 칸 최대 폭. **추천 줄을 "카드 폭 고정, 최대화에서 더 많이"로 바꾸는 것은 DESIGN.md Layout 규칙 변경 → 사용자 결정 필요** | M |
| 가5 | 라이브러리 상세 패널 | 제목 바로 아래 단추 8개(윤곽선 7 + 주 단추 1)가 썸네일·정보보다 먼저 온다. 단추 줄이 2칸·1칸·1칸·2칸·2칸으로 들쭉날쭉하다. 정보는 "라벨: 값" 문장 나열이라 줄이 맞지 않는다. 안쪽 스크롤 영역이 1100×720에서 240px뿐이라 썸네일 하나로 거의 찬다. #292 스토리 28(제목 → 정보 → 동작 순). | `1100/library--library-24-long-loaded.png`, `1100/library--6-library.png`, `1100/library-detail--detail-many-start.png` | `components/detail-panel.tsx`(순서, 자주 쓰는 동작만 단추로 두고 나머지는 한 줄 보조 단추·메뉴, 정보는 두 열 정의 목록) | M |
| 가6 | 영상 카드 | ① 카드 안에 테두리 상자(시청 통계)가 또 있다(카드 속 카드, 스토리 16). ② 태그가 없으면 통계 아래에 빈 띠가 남는다. ③ "보통"에서 정보 칸(160px)이 썸네일(202px)에 가까운 무게라 썸네일이 주인공이 아니다. ④ 1100+상세 패널에서 "보통"과 "크게"가 같은 모양(둘 다 2열)이다. | `1100/library--library-24-loaded.png`, `1100/library--5000-small.png`, `1100/library-large--library-24-long-large-loaded.png` | `components/video-card.tsx` `VideoStatistics`(안쪽 테두리·면 빼고 한 줄로), `web_tokens.json` `layout.library-card-info-height`와 `library-grid.tsx` 줄 높이를 함께(가상 격자 계산 방식은 그대로) | M |

### 나 — 부품 일관성

| 번호 | 어디 | 무엇이 문제인가 | 근거 | 고칠 자리 | 크기 |
|---|---|---|---|---|---|
| 나1 | 상태 배지·태그 칩 | DESIGN.md는 "상태 배지는 알약이 아니라 `md`"라고 하지만 높이 20px에 둥글기 10px라 실제로는 알약이다. 태그 칩은 구현이 네 가지다(카드 `VideoTags` span, 상세 패널 `Button xs`, 모아보기 테두리 있는 span, 필터 칩 `Button xs`). shadcn `Badge`는 `rounded-full` 그대로다. 상태(배지)와 분류(태그)가 같은 모양이라 구별되지 않는다. | `1100/library--6-chips-many.png`, `1100/reel-search--web-reel-long.png`, `1100/queue--web-few-all-states-long.png` | `page-parts.tsx` `StatusBadge` 둥글기(작은 단계 토큰 필요 여부 확인), 공용 `TagChip` 하나로 모으기(`video-tags.tsx`, `ReelPage.tsx`, `library-filters.tsx`) | M |
| 나2 | 켜짐·꺼짐 (설정 자동 감지, 백업 썸네일 포함) | 상태를 "자동 감지: 켜짐" 같은 단추 글자로 보여 준다. 스위치 부품이 없다. | `1100/folders-settings--web-settings-general.png`, `1100/settings--web-backup-empty.png` | `components/ui/`에 shadcn `Switch` 추가(토큰만 사용), `automatic-detection.tsx`·`backup-settings.tsx` | S |
| 나3 | 설정 카드 | 안쪽 여백이 두 가지(`px-4 py-3` / `p-6`)이고 조작 위치가 오른쪽·아래로 섞여 있다. 번역 구역은 값("Codex (CLI)")이 화면에서 가장 큰 글자다. "자막 대기열 열기"처럼 이동만 하는 단추가 주 단추다(스토리 35). | `1100/folders-settings--web-settings-general.png`, `1100/folders-settings--web-settings-translation.png`, `1100/folders-settings--web-settings-transcription.png` | 공용 설정 행 부품(제목·설명·조작 한 줄) 하나, `SettingsPage.tsx`와 구역 컴포넌트 6개 | M |
| 나4 | 키 표시 | 네 가지다. 키 안내는 `Kbd`, 메뉴 단축키는 자간 넓은 글자(shadcn 기본 `tracking-widest`), 키 배치 표는 일반 글자, 페이지 안 키 힌트는 문장. 힌트 문장 위치도 다섯 군데다(추천 머리글 아래, 대기열 오른쪽 위, 모아보기 단추 옆, 검색 입력란 아래, 폴더 패널 바닥). 스토리 36. | `1100/key-guide--24-default-1-library.png`, `1100/library--3-menu-default.png`, `1100/folders-settings--web-settings-keys.png`, `1100/recommend--web-recommend-full.png` | `ui/dropdown-menu.tsx`·`ui/context-menu.tsx` 단축키 칸, `key-bindings-editor.tsx`, 공용 키 힌트 부품(`Kbd` 사용, 자리 한 곳) | M |
| 나5 | 입력란 글자 크기 | 입력란은 16px(`text-base`), 선택 목록·단추는 14px이라 같은 줄에서 글자 크기가 다르다. 검색 탭 입력란은 공용 `Input`이 아니라 원시 `<input>`(48px, 18px, `card` 면)이다. 스토리 21. | `1100/library--library-24-loaded.png`, `1100/reel-search--web-search-few.png`, `1100/queue--web-rules-many.png` | `ui/input.tsx`(14px), `Input`에 큰 크기 variant를 두고 `reel-search-parts.tsx`가 사용 | S |
| 나6 | 목록 행 | 다섯 가지다. 대화상자 목록(각진 모서리·각진 선택 링), 태그 대화상자 한 창 안의 두 목록(위는 여백 행, 아래는 굵은 글자 + 구분선), 폴더 목록, 대기열 규칙, 백업 목록. 행 높이·구분선·선택 모서리가 제각각이다. | `1100/dialog-tag--dialog-tags-300.png`, `1100/dialog--web-highlights-many-long.png`, `1100/queue--web-rules-many.png`, `1100/settings--web-backup-many.png` | 공용 목록 틀·행 부품 하나(`selectableItem` 위에), `dialogs/dialog-parts.tsx`, `queue-rules.tsx`, `FoldersPage.tsx`, `backup-settings.tsx` | M |
| 나7 | 하이라이트 색 (모아보기) | 모아보기는 지점·구간 시각이 모두 노랑이다. 영상 하이라이트 대화상자는 지점 노랑·구간 초록으로 맞게 나눈다. Meaning-Only Color, 스토리 31. | `1100/reel-search--web-reel-many.png` ↔ `1100/dialog--web-highlights-many-long.png` | `pages/ReelPage.tsx`(시각 글자색을 종류에 따라), 가능하면 대화상자와 같은 부품 | S |
| 나8 | 위험 단추 | 보조 자리의 위험 동작("하이라이트 삭제")도 채운 분홍이라 주 단추 옆에 색 단추가 둘이다. DESIGN.md는 "덜 강한 경우는 `destructive` 윤곽선"이다. | `1100/dialog--web-highlights-many-long.png` | 쓰는 곳의 variant 선택(확인 대화상자의 확인만 채움, 나머지는 윤곽선) | S |
| 나9 | 대기열 진행 막대 | 퍼센트 글자 폭(0% ↔ 100%)에 따라 막대 길이가 행마다 다르다. 실패·완료·보류도 진행 중과 같은 인디고다. 선택한 대기 행은 트랙이 밝아져 꽉 찬 회색 막대처럼 보인다. 스토리 32. | `1100/queue--web-few-all-states-long.png` | `components/queue-list.tsx`(퍼센트 칸 고정 폭, 끝난 상태는 막대 대신 배지만, 트랙 색) | S |
| 나10 | 가장자리 정렬 | 페이지 머리글은 왼쪽 16px, 모아보기·검색 목록은 20px, 추천 줄은 24px에서 시작한다. 라이브러리는 폴더 패널 단추 하나를 위해 격자 왼쪽에 44px 기둥이 내내 비어 있다. | `1100/reel-search--web-reel-many.png`, `1100/recommend--web-recommend-full.png`, `1100/library--library-24-loaded.png` | 각 페이지의 목록 여백(선택 링 자리를 안쪽 여백 대신 음수 여백·`ring-inset`으로), 폴더 단추를 툴바로 | S |
| 나11 | 스크롤바 | 추천 줄마다 가로 스크롤바가 늘 보이고 양 끝에 작은 화살표 흔적이 남는다. 상세 패널 스크롤바와 격자 스크롤바가 바로 옆에 나란하다. | `1100/recommend--web-recommend-long.png`, `1100/library--library-24-loaded.png` | `index.css` 스크롤바 규칙(단추 조각 숨김), 추천 줄은 자리만 예약하고 넘칠 때만 손잡이 | S |

### 다 — 화면별 잔손질

| 번호 | 어디 | 무엇이 문제인가 | 근거 | 고칠 자리 | 크기 |
|---|---|---|---|---|---|
| 다1 | 라이브러리 툴바 | 3:1 테두리 조작이 한 줄에 6개라 선이 많다. 칩이 없을 때 툴바와 격자 사이 빈 줄이 48px이다(자리 예약 규칙은 유지하되 높이만 재검토). | `1100/library--library-24-loaded.png` | `LibraryPage.tsx` 툴바(정렬 방향을 아이콘 단추로, 라벨 정리), 칩 줄 높이 토큰 | S |
| 다2 | 라이브러리 필터 팝오버 | 화면에 여유가 있는데 팝오버가 짧아 내용이 중간에서 잘린다(주 단추가 반만 보임). 라벨과 선택 목록 정렬이 줄마다 다르다. | `1100/library--5000-filter-panel.png`, `max/library--5000-filter-panel.png` | `components/library-filters.tsx`(높이 한도, 두 열 격자) | S |
| 다3 | 폴더 관리 | 안내가 쌓이면 폴더 목록이 2.5행만 보인다. 셸 안내 묶음이 페이지 안내 글자를 덮는다. "새 영상의 최소 길이" 카드가 목록 아래에 늘 85px을 차지한다(설정 > 일반에도 같은 카드가 있다). | `1100/folders-notice--web-mixed-open.png`, `1100/folders-settings--web-folders-many.png` | `FoldersPage.tsx`(안내를 라이브러리처럼 떠 있는 띠로, 최소 길이 카드 자리), `NoticeLayer` 모서리 판단에 페이지 안내 포함 | M |
| 다4 | 모아보기·검색 결과 행 | 긴 제목이 줄 제한 없이 3줄까지 간다(메모는 3줄 제한). 아래 상태 문장이 길다. | `1100/reel-search--web-reel-long.png`, `1100/reel-search--web-search-onscreen-long.png` | `reel-search-parts.tsx` `ResultRow`(제목 줄 제한), `ReelPage.tsx` 상태 문장 | S |
| 다5 | 추천 카드 ↔ 영상 카드 | 같은 정보(시청 상태)를 라이브러리는 배지로, 추천은 글자로 보여 준다(스토리 29). | `1100/recommend--web-recommend-full.png` ↔ `1100/library--library-24-loaded.png` | `recommendation-card.tsx`가 `StatusBadge` 사용 | S |
| 다6 | 통계 | 숫자 카드의 큰 숫자(20px)가 페이지 제목(24px)보다 작아 주인공 숫자가 약하다. 머리글이 제목·설명·기간 세 줄이다. | `1100/statistics--8-30-watched_seconds.png`, `1100/statistics--50000-30-watched_seconds.png` | `web_tokens.json` `typography.roles.display`(크기 한 단계) — **글자 단계 토큰 변경이라 사용자 결정 필요**, `StatisticsPage.tsx` 머리글 | S |
| 다7 | 대화상자 안 목록 글자 | 영상 하이라이트 대화상자의 메모는 흐린 글자, 모아보기의 같은 메모는 본문 글자다. | `1100/dialog--web-highlights-many-long.png` ↔ `1100/reel-search--web-reel-many.png` | `dialogs/dialog-parts.tsx` | S |
| 다8 | 번역 대화상자 | 양식이 길어 안쪽에서 스크롤하고, 단추 크기(기본·xs)와 고스트 단추가 섞여 있다. | `1100/dialog--web-translation.png` | `dialogs/TranslationForm.tsx`(구역 접기 없이 간격·단추 크기만 정리) | S |

### 사용자 결정이 필요한 항목

체계를 바꾸는 것이라 확인 없이 진행하지 않는다.

1. **가3-②** 구역 탭 선택색을 인디고에서 무채색으로(DESIGN.md `tab-section-selected`). 바꾸지 않으면 통계처럼 탭 묶음이 여러 개인 화면에서 인디고가 계속 여러 군데다.
2. **가4** 추천 줄 "한 줄 다섯 장" 규칙을 "카드 폭 고정"으로(DESIGN.md Layout). 바꾸지 않으면 최대화에서 추천 카드가 계속 커진다.
3. **다6** `display` 글자 단계를 키울지.
4. **나1** 상태 배지를 각지게(작은 둥글기) 해서 태그 칩과 구별할지, 둘 다 알약으로 두고 DESIGN.md 문구를 실제에 맞출지.

### 목록에서 뺀 것 (#292 Out of Scope)

앱 이름·아이콘, 밝은 테마, 강조색 교체, 화면 구조 개편·탭 추가, 전환 효과·모션 토큰, 로딩·자리 표시·초점 복원 규칙, 재생 엔진·자막 렌더링·썸네일 생성, 시각 회귀 도구. 차트 막대 색(인디고 계열)은 데이터 색을 새로 정해야 해서 강조색 논의에 닿으므로 뺐다.

## 5. 하위 이슈 묶음 제안

모두 UI 작업(Claude 구현, Codex 검토)이다. 앞 묶음이 공용 부품을 바꾸므로 뒤 묶음은 앞 묶음에 `blocked_by`를 건다.

| 순서 | 묶음 | 항목 | 선행 | 크기 |
|---|---|---|---|---|
| 1 | 공용 부품 정리 1: 구역 탭 폭·빈 상태·스위치·입력란 글자·스크롤바·위험 단추 위계 | 가1, 가2, 나2, 나5, 나8, 나11 | 없음 | M |
| 2 | 색 의미 정리: 인디고 쓰임·하이라이트 색·진행 막대 | 가3, 나7, 나9 | 1 (결정 1 필요) | S~M |
| 3 | 배지·태그 칩·키 표시 통일 | 나1, 나4 | 1 (결정 4 필요) | M |
| 4 | 최대화 내용 폭 | 가4 | 1 (결정 2 필요) | M |
| 5 | 라이브러리 마감: 카드·상세 패널·툴바·필터 | 가5, 가6, 다1, 다2, 나10(라이브러리) | 1, 3 | L |
| 6 | 추천·모아보기·검색 마감 | 다4, 다5, 나10(나머지) | 2, 3 | S |
| 7 | 자막 대기열·통계·폴더 관리 마감 | 다3, 다6 | 1, 2 (결정 3 필요) | M |
| 8 | 설정·대화상자 마감: 설정 행·목록 행·번역 대화상자 | 나3, 나6, 다7, 다8 | 1, 3 | M |
| 9 | 마지막: 전체 탭 재촬영(1100×720·최대화·데이터 개수별), DESIGN.md·`.impeccable/design.json` 최종 갱신 | — | 1~8 모두 | S |

묶음마다 완료 조건은 #292의 웹 UI 공통 조건이다: `frontend/`에서 lint·typecheck·build, 토큰 생성기 `--check`, 바뀐 탭의 1100×720 전후 스크린샷, 데이터 개수별(0·적음·최대·긴 텍스트) 배치 확인. Qt 화면과 실창 확인은 사람이 한다.

## 6. 스크린샷 찾는 법

`screens/1100/`(1100×720)과 `screens/max/`(1920×1017)에 `<영역>--<원래 이름>.png`로 있다.

| 영역 접두어 | 내용 | 데이터 |
|---|---|---|
| `library`, `library-small`, `library-large`, `library-detail`, `library-notice`, `library-tagpicker` | 라이브러리 격자·카드 크기·상세 패널·필터·칩·폴더 패널·안내 | 0 · 3 · 6 · 24 · 5,000개, 긴 제목·태그 |
| `recommend` | 추천 | 빈 화면 · 적음 · 8줄 160개 · 긴 제목 · 자리 표시 · 메뉴 |
| `reel-search` | 모아보기·검색 | 0 · 2 · 503개, 긴 제목·메모·대사, 결과 없음·오류 |
| `queue` | 자막 대기열 | 0 · 8(모든 상태, 긴 제목) · 300개, 규칙 0 · 4개, 확인 창 |
| `statistics` | 통계 | 0 · 8 · 50,000회, 7·30·90·365일, 계산 실패 |
| `folders-settings`, `folders-notice`, `folders-watch` | 폴더 관리와 설정(일반·키 배치·받아쓰기·번역) | 폴더 0 · 1(긴 경로) · 80개, 오류 150개, 외부 자막 경고 300개 |
| `settings` | 설정의 추천·백업·업데이트·버전 정보 | 백업 0 · 여러 개, 업데이트 상태별 |
| `dialog`, `dialog-tag`, `dialog-random` | 대화상자 22종과 태그·무작위 재생 범위 | 목록 0 · 많음 · 긴 텍스트 |
| `key-guide` | 키 안내(탭마다) | 기본 · 키 여러 개 · 긴 키 이름 |
| `preparation` | 자막 준비 배너 | — |
