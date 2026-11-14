---
name: my-video-manager
description: 개인 영상 라이브러리의 어두운 웹 셸. 영상이 주인공이고 틀은 물러난다.
colors:
  background: "#09090b"
  foreground: "#fafafa"
  card: "#18181b"
  card-foreground: "#fafafa"
  popover: "#27272a"
  popover-foreground: "#fafafa"
  primary: "#4f46e5"
  primary-foreground: "#ffffff"
  primary-text: "#a5b4fc"
  secondary: "#303036"
  secondary-foreground: "#fafafa"
  muted: "#303036"
  muted-foreground: "#afafb7"
  accent: "#3f3f46"
  accent-foreground: "#fafafa"
  border: "#3f3f46"
  input: "#7c7c85"
  ring: "#818cf8"
  destructive: "#fca5a5"
  destructive-foreground: "#450a0a"
  highlight: "#fde047"
  highlight-open: "#f69b50"
  highlight-range: "#86efac"
  highlight-foreground: "#422006"
  status-success: "#86efac"
  status-success-foreground: "#052e16"
  status-info: "#93c5fd"
  status-info-foreground: "#172554"
  status-warning: "#fcd34d"
  status-warning-foreground: "#451a03"
typography:
  display:
    fontFamily: "Pretendard, Malgun Gothic, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: "1.75rem"
    letterSpacing: "-0.01em"
  page-title:
    fontFamily: "Pretendard, Malgun Gothic, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: "2rem"
    letterSpacing: "-0.02em"
  section-title:
    fontFamily: "Pretendard, Malgun Gothic, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: "1.75rem"
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Pretendard, Malgun Gothic, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.25rem"
    letterSpacing: "0em"
  body-strong:
    fontFamily: "Pretendard, Malgun Gothic, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: "1.25rem"
    letterSpacing: "0em"
  label:
    fontFamily: "Pretendard, Malgun Gothic, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: "1rem"
    letterSpacing: "0em"
  label-strong:
    fontFamily: "Pretendard, Malgun Gothic, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: "1rem"
    letterSpacing: "0em"
rounded:
  sm: "0.5rem"
  md: "0.625rem"
  lg: "0.75rem"
  xl: "1rem"
  full: "9999px"
spacing:
  "1": "0.25rem"
  "2": "0.5rem"
  "3": "0.75rem"
  "4": "1rem"
  "6": "1.5rem"
  "12": "3rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0.5rem 1rem"
    height: "2.25rem"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-foreground}"
    rounded: "{rounded.md}"
    padding: "0.5rem 1rem"
    height: "2.25rem"
  button-ghost-hover:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
  input:
    backgroundColor: "{colors.background}"
    borderColor: "{colors.input}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "0.25rem 0.75rem"
    height: "2.25rem"
  tab-navigation-selected:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.75rem"
  tab-section-selected:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.75rem"
  video-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    borderColor: "{colors.border}"
    rounded: "{rounded.lg}"
  video-card-hover:
    backgroundColor: "{colors.popover}"
    borderColor: "{colors.border}"
    rounded: "{rounded.lg}"
  selectable-item-selected:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.md}"
  status-badge-success:
    backgroundColor: "{colors.status-success}"
    textColor: "{colors.status-success-foreground}"
    typography: "{typography.label-strong}"
    rounded: "{rounded.md}"
    padding: "0.125rem 0.5rem"
  status-badge-highlight:
    backgroundColor: "{colors.highlight}"
    textColor: "{colors.highlight-foreground}"
    typography: "{typography.label-strong}"
    rounded: "{rounded.md}"
    padding: "0.125rem 0.5rem"
  number-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    rounded: "{rounded.xl}"
    padding: "1.5rem"
---

# Design System: my-video-manager

> **토큰 원본은 `src/my_video_manager/web_tokens.json`이다.** 색·간격·둥글기·글자 크기를 바꿀 때는 이 파일만 고치고 `scripts/generate_web_types.py`로 `frontend/src/tokens.css`를 다시 생성한다. `tokens.css`는 생성물이라 직접 고치면 다음 생성 때 덮어써진다. 이 문서의 frontmatter 값은 `web_tokens.json`을 옮겨 적은 것이며, 둘이 어긋나면 `web_tokens.json`이 맞다. 둥글기 단계(`sm`~`xl`)는 `frontend/src/index.css`의 `@theme inline`이 `--radius`에서 계산한다.

## Overview

**Creative North Star: "The Quiet Screening Room" (조용한 상영실)**

불이 꺼진 상영실처럼, 화면에서 가장 밝고 큰 것은 영상(썸네일·재생 화면)이다. 머리글·탭·단추·테두리 같은 틀은 회색조로 물러나서 영상을 고르는 눈을 방해하지 않는다. 색은 의미가 있을 때만 켜진다. 인디고는 지금 고른 것과 초점, 주 동작을 가리키는 빛줄기이고, 노랑·초록·호박색은 하이라이트, 상태 색은 안내에만 쓴다.

밀도는 도구 쪽이다. 하루에도 여러 번 켜고 키보드로 빠르게 오가는 앱이라, 카드 하나에 길이·시청 상태·자막 여부·시리즈·시청 통계·태그가 촘촘히 들어간다. 그만큼 부품은 절제되고 단정해야 한다. 면은 얇은 테두리와 한두 단계의 명도 차이로만 나누고, 쉬는 면에는 그림자를 두지 않는다. 움직임은 짧고 차분하며, 움직임 줄이기 설정에서는 없다.

**Key Characteristics:**
- 어두운 무채색(zinc 계열) 바탕 위에 인디고 하나만 강조색으로 쓴다.
- 썸네일이 주인공이다. 16:9 자리를 미리 잡고, 없으면 필름 아이콘이 자리를 지킨다.
- 쉬는 면은 평평하다. 그림자는 대화상자·메뉴·팝오버처럼 떠 있는 층에만 있다.
- 시간·횟수·날짜는 고정폭 숫자(`tabular-nums`)로 정렬한다.
- 모든 값은 테마 토큰에서 오고, `@shadcn/lint`가 이를 강제한다.

## Colors

어두운 상영실 같은 무채색 바탕에 인디고 빛줄기 하나, 그리고 의미 전용 상태 색이 있다.

### Primary
- **Projector Indigo** (`primary`): 주 동작 단추, 구역 탭의 선택 상태처럼 "지금 이것"을 가리키는 곳에만 쓴다. 위에 오는 글자는 `primary-foreground`.
- **Focus Beam** (`ring`): 키보드 초점 윤곽과 선택된 카드의 테두리·링. 마우스 호버와 구별되는 유일한 신호다.
- **Soft Indigo Text** (`primary-text`): 어두운 바탕 위 인디고 글자(링크 단추, 강조 숫자 카드). 진한 `primary`를 글자에 쓰면 대비가 모자라서 따로 둔다.

### Neutral
면은 바탕 → 카드 → 떠 있는 층 순서로 한 단계씩 밝아지고, 그 위에서 호버는 한 단계, 선택은 그보다 한 단계 더 밝다.
- **Projection Black** (`background`): 앱 바탕과 머리글.
- **Booth Charcoal** (`card`): 카드, 목록 행, 상세 패널, 설정·통계 구역처럼 바탕 위에 쉬는 면. Qt 재생 화면의 머리글·조작 줄·하이라이트 목록.
- **Curtain Gray** (`popover`): 떠 있는 층, 그리고 안에 `muted` 면(배지·태그 칩·썸네일 자리)이 있는 카드·행(영상·추천 카드, 대사 검색·모아보기 결과, 자막 대기열 행)의 호버 면(카드 바로 위 단계). 대화상자, 경고 대화상자, 팝오버, 메뉴, 선택 목록, 차트 툴팁, Qt 트레이 메뉴·공용 경고·재생 키 안내·툴팁. 카드와 그림자 없이도 구별된다(카드 대비 1.19:1).
- **Aisle Graphite** (`muted`, `secondary`): 조용한 면과 호버 면. 썸네일 빈 자리, 자리 표시(`Skeleton`), 키 표시(`Kbd`), 구역 탭 묶음, 보조 단추·태그 칩, 고스트 단추·탭·목록 행·메뉴 밖 행의 호버. 떠 있는 층 위에서도 한 단계 보인다.
- **Spot Graphite** (`accent`): 선택 면. 내비게이션·패널 탭과 설정 분류의 선택, 고른 목록 행·폴더·대기열 행, 메뉴·선택 목록의 현재 항목, 보조 단추 호버와 구역 탭 묶음 안 호버(묶음 면이 이미 `muted`라서), Qt 눌린 단추·트레이 메뉴 현재 항목·고른 하이라이트. 호버(`muted`)와 같은 면을 쓰지 않는다.
- **Dim Rail** (`border`): 장식 구분선. 구분선, 머리글·패널·설정 구역·쉬는 카드의 테두리, 떠 있는 층 테두리, 스크롤바 손잡이. 꼭 필요한 경계가 아니므로 WCAG 1.4.11의 3:1 예외이고 어둡게 둔다.
- **Steel Hairline** (`input`): 조작 경계. 입력란·선택 목록·윤곽선 단추·Qt 단추처럼 경계가 곧 조작 대상의 모양인 요소의 테두리와 윤곽선 배지의 링. 바탕·카드·떠 있는 층 어디서나 3:1 이상이다. 입력 요소의 면은 이 색 30%(`bg-input/30`, 호버 50%)다.
- **Usher Gray** (`muted-foreground`): 보조 글자(설명, 길이, 시리즈 이름, 비선택 탭, 입력란 안내 글자). 선택 면(`accent`)과 입력란 면 위에서도 4.5:1 이상이다.
- **Screen White** (`foreground`): 본문 글자.
- **내용 카드 vs 조작 경계:** 영상·추천·대사 검색 결과 카드는 썸네일·제목으로 식별되는 내용 묶음이라 쉬는 테두리가 장식(`border`)이고 호버에도 그대로다. 호버는 면이 면 단계의 다음 칸(`card` → `popover`, 1.19:1)으로 밝아진다. `muted`가 아닌 까닭은 카드 안 `muted` 배지(아직 안 봄)·태그 칩이 호버 때 카드 면에 묻히지 않게 하려는 것이다. 출처 배지가 있는 대사 검색 결과, 태그 칩·썸네일 자리가 있는 모아보기 결과, 대기 배지·진행 막대가 있는 자막 대기열 행도 같은 이유로 호버가 `popover`다(배지 면 / 호버 면 1.14:1, 선택 면 `accent` 위 1.26:1). 안에 `muted` 면이 없는 목록 행만 호버가 `muted`다. 이 구분은 공용 `selectableItem`의 `inner: "muted"`가 맡는다. 선택·초점은 `ring`으로 바뀐다. `input` 3:1은 경계가 곧 조작 대상인 요소에만 쓴다.

### Highlight (하이라이트 전용)
- **Marker Yellow** (`highlight`): 지점 하이라이트와 "즐겨 보는" 배지.
- **Open Range Amber** (`highlight-open`): 시작만 찍고 끝나지 않은 구간.
- **Range Green** (`highlight-range`): 구간 하이라이트.
- 위 세 색 위의 글자는 `highlight-foreground`.

### Status (안내·배지 전용)
- **Mint** (`status-success`): 다 본 영상, 작업 완료.
- **Sky** (`status-info`): 보다 만 영상, 정보 안내.
- **Amber** (`status-warning`): 확인이 필요한 경고.
- **Rose** (`destructive`): 오류, 파일 없음, 되돌릴 수 없는 동작. 어두운 바탕에서 읽히도록 밝은 장미색이고, 위 글자는 진한 `destructive-foreground`.
- 각 상태 색에는 짝이 되는 진한 `-foreground`가 있다. 배지는 색 면 + 진한 글자, 안내(Notice)는 10% 면 + 40~60% 테두리 + 색 아이콘으로 쓴다.

### Named Rules
**The One Beam Rule.** 강조색은 인디고 하나다. 선택·초점·주 동작이 아닌 곳에 인디고를 칠하지 않는다.

**The Meaning-Only Color Rule.** 하이라이트 색과 상태 색은 그 의미에만 쓴다. 장식이나 구역 구분에 빌려 쓰지 않는다.

**The Lit Ladder Rule.** 면 단계는 `background` → `card` → `popover`이고, 놓인 면 위의 호버는 `muted`, 선택은 `accent`다. 같은 역할은 같은 토큰을 쓰고, 호버와 선택은 같은 면을 쓰지 않는다. 고를 수 있는 목록 항목(설정 분류·머리글·패널 탭·폴더·대화상자 목록·태그 고르기·대기열 행·검색 결과·영상 카드)은 공용 `selectableItem` variant 하나로 이 둘을 칠한다. 안에 `muted` 면이 있는 항목은 호버만 한 칸 위 `popover`다. 바탕·카드·떠 있는 층 위에서 본문·보조 글자는 4.5:1, 조작 경계(`input`)와 초점·선택 윤곽(`ring`)은 3:1 이상이다. 색을 바꾸면 `tests/test_web_contrast.py`와 `tests/test_theme.py`가 이 기준을 다시 잰다.

## Typography

**Body Font:** Pretendard (with Malgun Gothic, sans-serif)

**Character:** 앱에 번들한 한국어 글꼴 Pretendard(SIL OFL 1.1) 하나로 모든 위계를 만든다. 글꼴을 섞지 않고 역할 토큰의 크기·굵기(400·500·600)·자간으로만 위계를 나눈다. 글꼴 파일은 npm 프로덕션 의존성 `pretendard`의 정적 woff2를 웹 번들에 넣는다. 굵기마다 첫 렌더용 부분 집합(라틴·기호·자주 쓰는 한글 2,780자, `font-display: block`)을 미리 읽고 첫 렌더 전에 기다려(상한 1초) 대체 글꼴이 보였다가 바뀌지 않게 한다. 부분 집합에 없는 원본의 나머지 모든 글자(한글 음절·확장 라틴·기호 등)는 같은 글꼴의 전체 파일이 `unicode-range`(`swap`)로 맡아 그 글자가 화면에 나올 때만 읽고, 두 face의 `unicode-range`는 `npm run fonts`가 woff2 cmap에서 생성한 `fonts.css`에 둔다. 줄 높이와 카드 칸이 고정이라 바뀌어도 배치가 밀리지 않는다. 실행 중 네트워크에서 받지 않는다. 대체 글꼴은 맑은 고딕이다. 고정폭 표시(`font-mono`)도 같은 글꼴에 고정폭 숫자(`tnum`)를 켠다. Qt 화면(재생·트레이 메뉴·공용 경고)도 같은 글꼴을 쓴다. Qt는 woff2를 읽지 못해 웹 빌드가 같은 패키지의 정적 TrueType(토큰 굵기마다, otf는 Qt 힌팅에서 작은 글자 가로획이 사라져 쓰지 않는다)을 `web/qt-fonts/`에 두고, 앱이 창을 만들 때 Qt 글꼴 데이터베이스에 등록한다. 파일이 없거나 읽지 못하면 맑은 고딕으로 뜨고 앱 로그에 남긴다. 재생 기호(⏮ ⏸ ⏭ 등)만 컬러 이모지가 되지 않게 단색 기호 글꼴(Segoe UI Symbol)로 그린다. 글꼴을 바꾸려면 `web_tokens.json`의 `font-sans`·`bundled-font`를 고치고 `npm run fonts`로 `fonts.css`를 다시 만든다(`index.css`는 생성된 `fonts.css`를 import한다).

### Hierarchy
글자 위계는 역할 토큰으로 정한다. 원본은 `web_tokens.json`의 `typography.roles` 한곳이고, 역할마다 크기·줄 높이·굵기·자간을 함께 둔다. `scripts/generate_web_types.py`가 이를 Tailwind `text-<역할>` 유틸리티(크기·줄 높이·굵기·자간을 한 번에 정함)로 `tokens.css`에 만들고(`--check`가 드리프트를 막는다), 굵기는 번들 글꼴에 파일이 있는 400·500·600만 받는다. 화면에서는 `text-<역할>` 하나만 쓰고 `font-*`·`leading-*`·`tracking-*`를 덧붙이지 않는다. 같은 역할·같은 변형이면 어느 화면이든 같은 값이다.

| 역할 | 크기 / 줄 높이 | 굵기 | 자간 | 쓰는 곳 |
|---|---|---|---|---|
| `display` 큰 숫자 | 1.25rem / 1.75rem | 600 | -0.01em | 통계 숫자 카드(`StatisticsCard`, `NumberCard`). `tabular-nums`와 함께 쓴다. |
| `page-title` 페이지 제목 | 1.5rem / 2rem | 600 | -0.02em | `PageHeader`의 `h1`. |
| `section-title` 구역 제목 | 1.125rem / 1.75rem | 600 | -0.01em | 구역 제목(`SectionTitle`), 빈 상태 제목, 대화상자 제목, 통계 차트 제목, 설정 분류 제목. Qt 재생 머리글 제목·하이라이트 패널 제목. |
| `body` 본문 | 0.875rem / 1.25rem | 400 | 0 | 앱 기본 글자(`body`). 설명·목록 글자·검색 결과 대사. Qt 재생 화면의 보조 글자. |
| `body-strong` 본문 강조 | 0.875rem / 1.25rem | 600 | 0 | 카드·목록·검색 결과의 항목 제목, 카드 안 소제목(설정·백업의 `h3`), 입력 라벨, 표 머리글, 안내 제목, 메뉴 묶음 라벨, 앱 이름. |
| `label` 라벨 | 0.75rem / 1rem | 400 | 0 | 길이·날짜·개수 같은 작은 메타 글자, 키 안내 설명, 컴팩트 안내, 차트 축·도움말. |
| `label-strong` 라벨 강조 | 0.75rem / 1rem | 500 | 0 | 상태 배지(`StatusBadge`·`Badge`), 키 표시(`Kbd`), 하이라이트 시각, 카드 통계 값, 작은 묶음 제목. |

자간은 큰 글자에만 조금 줄인다. Pretendard는 큰 크기에서 글자 사이가 벌어져 보여 제목·큰 숫자만 -0.01~-0.02em으로 조이고, 본문·라벨은 글꼴 기본 자간 그대로 둔다. 단추·탭·입력란·선택 목록·메뉴 항목 같은 조작 글자는 역할이 아니라 shadcn 부품의 크기(`text-sm font-medium`, 입력란 `text-base`)를 그대로 쓴다.

**줄 높이에 묶인 높이.** 한 줄짜리 칸과 자리 표시는 역할 줄 높이를 따른다(`index.css`의 `h-line-body`·`h-line-label`·`h-line-display`, 라벨 두 줄 `lines-label-2`, 상태 배지 `h-badge` = 라벨 한 줄 + 위아래 0.125rem). 라이브러리 카드 정보 칸 높이는 `web_tokens.json` `layout.library-card-info-height`(10rem: 여백 0.5rem×2 + 제목 한 줄 1.25 + 배지 줄 1.25 + 시리즈 한 줄 1 + 통계 묶음 2.875 + 태그 줄 1.25 + 간격, 남는 자리는 태그 줄이 아래에 붙는다)이고, 카드와 가상 격자 줄 높이 계산(`library-grid.tsx`)이 같은 토큰을 읽는다. 줄 높이를 바꾸면 이 토큰도 함께 다시 잰다(`tests/test_type_roles.py`가 작게·보통·크게에서 잘림을 확인한다).

**Qt 재생 화면.** `theme.set_type_role`이 같은 역할 토큰을 읽는다. 크기·굵기는 스타일시트의 `typeRole` 규칙, 자간은 Qt 스타일시트에 속성이 없어 위젯 글꼴(1/64px 단위)에 둔다. 한 줄 라벨이라 줄 높이는 글꼴 기본값을 쓴다.

**`cn()`과 역할 클래스.** tailwind-merge는 모르는 `text-*`를 글자 색으로 보므로, `lib/utils.ts`가 생성된 역할 이름 목록(`lib/type-roles.ts`)을 글자 크기 묶음으로 알려 준다. 역할을 더하면 생성기가 이 목록도 함께 만든다.

### Named Rules
**The Tabular Numbers Rule.** 길이·횟수·시간·날짜·통계 숫자는 `tabular-nums`로 쓴다. 목록에서 숫자 폭이 흔들리지 않게 한다.

**The Body-Is-Small Rule.** 기본 크기는 0.875rem이다. 정보 밀도가 이 앱의 성격이므로, 본문을 키워 여백을 메우지 않는다.

## Layout

- **기준 창:** 1100×720. 최대화에서도 자연스러워야 한다.
- **셸:** 맨 위 머리글(좌우 1rem, 위아래 0.75rem, 아래 테두리)에 앱 이름, 내비게이션 탭 8개, 키 안내 단추가 한 줄로 놓인다. 나머지는 페이지 영역이다. 셸 안내는 페이지를 밀지 않고 페이지 영역 모서리(가장자리에서 1rem)에 떠 있는 묶음으로 쌓인다. 기본은 오른쪽 아래이고, 지금 페이지의 고정 조작 요소(툴바·작업 단추 줄처럼 스크롤로 옮길 수 없는 것)를 덮으면 그것을 가장 적게 덮는 모서리(왼쪽 아래 → 오른쪽 위 순)로 옮긴다. 폭은 28rem(`max-w-md`), 높이는 페이지 영역의 1/3까지이고 넘치면 묶음 안에서 스크롤한다. 머리 줄에 안내·오류 개수와 접기 단추가 있다. 모서리는 탭 전환·창 크기·묶음 크기와 페이지의 배치 변경 신호(`useLayoutChange`: 분류·구역 전환, 비동기 준비 완료. 공용 안내는 생기고 사라질 때와 펼치기·접기·더 보기에서 스스로 보낸다)에서만 다시 재고, 목록 스크롤에는 재지 않는다.
- **라이브러리:** 툴바 아래 필터 칩 줄은 칩이 없어도 한 줄 높이를 늘 차지하고, 칩이 많으면 그 줄 안에서 가로로 넘긴다. 페이지 안내는 격자 위쪽에 떠 있는 띠(격자 높이의 절반까지)라 목록을 밀지 않는다. 폴더 패널은 격자 옆 자리를 차지해 열 수가 바뀔 수 있지만, 열고 닫아도 선택 카드는 같은 세로 위치에 남는다. 예외: 같은 위치에 두려면 스크롤이 맨 위보다 위나 맨 끝보다 아래여야 하는 경우(열이 늘어 선택 카드가 새 첫 줄이 되는 경우 등)는 빈 여백을 만들지 않고 스크롤을 가능한 범위로 제한한다. 차이는 제한한 만큼뿐이고 선택 카드는 계속 보인다.
- **페이지:** 기본 창에서는 각 페이지가 높이에 맞춰 내부 목록만 스크롤한다. 창이 작아 목록 최소 높이와 안내가 넘칠 때만 페이지 영역 전체가 세로로 스크롤한다.
- **라이브러리 격자:** 가상화된 격자. 카드 폭은 작게 12rem · 보통 16rem · 크게 22rem 세 단계이고, 줄 높이는 15.5rem이다. 썸네일은 16:9 자리를 먼저 잡아 이미지가 늦게 와도 배치가 밀리지 않는다.
- **추천 줄:** 한 줄에 다섯 장 폭을 유지하고 그 줄 안에서만 가로로 이동한다. 스크롤바 자리를 늘 예약해 줄 높이가 같다.
- **대화상자:** 공용 틀(`components/ui/dialog.tsx`)의 폭은 확인·짧은 입력 512px(`compact`), 업무 대화상자 640px(`default`), 목록·키 안내 896px(`wide`)이고, 화면 가장자리에서 16px 띄우며 창보다 길면 틀 안에서 스크롤한다. 재생 중에는 컨테이너 배치로 내용 크기에 맞추고 목록 높이를 18rem으로 제한해 영상을 가리지 않는다.
- **간격 리듬:** 기본 단위 0.25rem. 요소 사이는 0.5rem(`gap-2`)이 가장 흔하고, 묶음 사이는 0.75~1rem, 카드·행 안쪽은 1rem, 큰 카드·대화상자 안쪽은 1.5rem이다.

### Named Rules
**The Reserved Space Rule.** 기다리는 내용(썸네일, 패널, 통계, 안내)은 도착하기 전에 자리를 확보한다. 데이터가 들어와도 배치가 튀지 않는다.

## Elevation & Depth

쉬는 면은 평평하다. 깊이는 그림자가 아니라 면의 명도 단계(`background` → `card` → `popover`, 그 위 호버 `muted` → 선택 `accent`)와 얇은 테두리로 나눈다. 떠 있는 층은 그림자 없이도 카드보다 밝은 면으로 구별된다. 그림자는 바탕 위에 떠서 다른 내용을 가리는 층(대화상자, 경고 대화상자, 필터 팝오버, 메뉴)에만 쓰고, 그 뒤에는 `background` 80% 덮개를 깐다. 입력란과 윤곽선 단추의 아주 옅은 그림자(`shadow-xs`)는 shadcn 기본값을 그대로 둔 것이다.

### Shadow Vocabulary
- **Floating layer** (`shadow-lg`): 대화상자·팝오버·키 안내·떠 있는 안내(라이브러리 띠·셸 안내 묶음).
- **Menu** (`shadow-md`): 드롭다운·컨텍스트 메뉴·선택 목록.
- **Hairline** (`shadow-xs`): 입력란, 윤곽선 단추.
- 통계 차트 툴팁만 shadcn 기본값 `shadow-xl`을 쓴다.

### Named Rules
**The Flat-At-Rest Rule.** 카드·목록 행·패널은 호버나 선택에도 그림자를 얻지 않는다. 호버는 면 한 단계(목록 행은 `muted`, 안에 `muted` 면(배지·태그 칩·썸네일 자리)이 있는 카드·행은 면 단계의 다음 칸 `popover`)이고 쉬는 테두리는 그대로 두며, 선택은 `ring` 테두리와 링(목록 행은 `accent` 면을 더한다)으로 표시한다.

## Shapes

부드럽지만 단정한 둥글기다. 기준 `--radius`는 0.75rem이고, 크기에 따라 단계를 고른다.

- 단추·입력란·탭·상태 배지·작은 썸네일: `md`(0.625rem) 또는 `sm`(0.5rem)
- 영상 카드·목록 행·안내·구역 탭 묶음: `lg`(0.75rem)
- 대화상자·팝오버·숫자 카드·빈 상태: `xl`(1rem)
- 알약 모양: 진행 막대, 스크롤바 손잡이 같은 가는 막대만 `full`. 상태 배지는 알약이 아니라 `md`다.
- 테두리는 1px 한 겹이다. 빈 상태만 점선 테두리를 쓴다.
- 재생 중 컨테이너 모드의 대화상자는 창을 채우므로 모서리가 각지다.

## App Icon

앱 아이콘은 인디고 판 위의 흰 "자막 서랍" 하나다(앱 이름 "VideoCabinet", #343에서 고른 D안). 원본은 `assets/icon/`에 두고, 산출물(`src/my_video_manager/app.ico`, 웹 이미지, 출처 매니페스트)은 `python scripts/app_icon.py`로 만들어 함께 커밋한다. 산출물을 손으로 고치지 않는다.

- **모양:** 둥근 사각 판 위에 위가 열린 서랍. 판은 캔버스를 여백 없이 채우고(256px 기준 모서리 반지름 36) 바깥 테두리 한 겹(256px 기준 10)을 두른다. 서랍은 앞면(256px 기준 180×92, 반지름 12)과 그 위의 열린 테두리(사다리꼴 띠)로 이루어진다. 앞면에 자막 두 줄(긴 줄·짧은 줄)과 오른쪽을 가리키는 작은 재생 삼각형을 판 색으로 뚫는다. 시안의 "서랍 안 어두운 인디고 패널"은 두지 않는다.
- **색:** 판 `primary`(#4f46e5) 하나, 서랍 `primary-foreground`(#ffffff), 테두리 `input`(#7c7c85). 그라데이션·그림자·질감은 쓰지 않는다. 서랍과 판은 6.3:1이다. 자막 줄과 삼각형은 판과 같은 색이라 인디고는 한 가지뿐이다.
- **어두운 작업 표시줄 대비(테두리를 고름):** 인디고 판은 밝은 작업 표시줄(#f3f3f3)과 5.7:1이지만 어두운 작업 표시줄(#202020)과는 2.6:1이라 가장자리 3:1 기준에 못 미친다. 기준을 낮추는 대신 이전 아이콘과 같은 `input` 중간 회색 테두리를 두른다. 이 회색은 밝은(3.7:1)·어두운(3.9:1) 작업 표시줄 모두와 3:1을 넘는 거의 유일한 토큰 색이라, 테마에 따라 아이콘을 바꾸지 않고 한 모양으로 두 배경을 만족한다. 기준을 다시 정하면 어두운 작업 표시줄에서 판의 윤곽이 서랍만 남기고 흐려지고, 앱 아이콘과 트레이가 기대던 픽셀 검사(가장자리 띠 대비)를 버려야 한다.
- **작은 크기:** 16·20·24·32px은 벡터를 줄이지 않고 픽셀에 맞춰 손본 PNG(`app-icon-<크기>.png`)를 원본으로 둔다. 반투명 픽셀 없이 세 색만 쓴다. 테두리는 24px 이하 1px·32px 2px, 테두리와 서랍 사이 판은 1px 이상이다. 자막 줄은 16px 1px·20~32px 2px 두께이고, 서랍의 열린 테두리는 1px(32px은 계단 2px)이다. 재생 삼각형은 모든 크기에 남긴다(16px은 2×3px). 24·32px은 앞면 모서리 한 픽셀씩을 판 색으로 깎아 둥글게 보인다. 40·48·64·256px은 벡터를 그 크기로 렌더링한다.
- **검사:** `tests/test_app_icon.py`가 산출물만 읽어 확인한다. 8개 크기가 모두 있고 각 크기가 제 원본에서 나왔는지, 16~32px의 바깥 가장자리 띠가 두 작업 표시줄 색과 3:1 이상인 비율(90% 이상), 반투명 픽셀 비율(2% 이하), 서랍 마크 면적(판과 3:1 이상 구별되는 안쪽 픽셀, 캔버스의 12~45%. 손본 원본은 22~32%)을 본다. 원본 내용 해시가 매니페스트와 다르면 낡은 산출물로 실패한다. 기준값은 `scripts/app_icon.py` 상수다.

### Tray Icon

트레이(알림 영역) 아이콘은 앱 아이콘을 단순화한 모양이다. 같은 판과 테두리에 서랍 앞면과 자막 두 줄만 남기고, 열린 테두리와 재생 삼각형은 뺀다. 알림 영역의 16px 안에서 그 자리를 앞면과 자막 줄에 돌려 크게 읽힌다.

- **모양:** 앱 아이콘과 같은 둥근 사각 판·테두리 위에 흰 서랍 앞면 하나. 앞면은 테두리 안쪽 판 1px만 남기고 가로를 거의 다 쓰며, 자막 두 줄은 16·20px 2px, 24px 3px, 32px 4px 두께다. 24·32px은 앞면 모서리 한 픽셀씩을 깎는다.
- **색:** 앱 아이콘과 같은 판 `primary`(#4f46e5)·서랍 `primary-foreground`(#ffffff)·테두리 `input`(#7c7c85) 세 색. 어두운 작업 표시줄 대비도 앱 아이콘과 같은 회색 테두리로 푼다(밝은 3.7:1·어두운 3.9:1).
- **원본과 산출물:** 16·20·24·32px(화면 배율 100·125·150·200%) 손본 PNG `assets/icon/tray-icon-<크기>.png`가 원본이고 벡터 원본은 없다. 같은 `python scripts/app_icon.py`가 `src/my_video_manager/tray.ico`를 만들어 매니페스트의 `tray` 항목에 적는다.
- **변형 없음:** Windows 테마에 따라 바꾸지 않고, 작업 중 배지 같은 상태 표시도 넣지 않는다. 긴급 탈출로 창을 숨겼을 때도 같은 아이콘이다.
- **검사:** 판과 테두리가 앱 아이콘과 같으므로 기준도 같다. 가장자리 대비(두 작업 표시줄 3:1 이상 90%)·반투명(2% 이하)·실루엣 면적(50% 이상)·서랍 마크 면적(12~45%. 손본 원본은 32~40%)·원본 해시를 본다.

### Named Rules

**The Subtitle Drawer Rule.** 앱 아이콘은 판·테두리·서랍 세 색과 자막 서랍 하나뿐이다. 인디고는 판 하나이고, 자막 줄과 삼각형은 판 색으로 뚫는다. 작은 크기는 손본 원본을 따로 두고, 원본을 바꾸면 산출물을 다시 만들어 함께 커밋한다.

**The Plain Drawer Tray Rule.** 트레이 아이콘은 앱 아이콘과 같은 판·테두리 위에 서랍 앞면과 자막 두 줄뿐이다. 테마·상태에 따라 바꾸지 않는다.

## Components

### Buttons
절제된 단추. 색이 있는 단추는 화면에 하나 정도다.
- **Shape:** `md` 둥글기(0.625rem). 기본 높이 2.25rem, 크기는 xs 1.5rem · sm 2rem · 기본 2.25rem · lg 2.5rem과 같은 크기의 정사각 아이콘 단추.
- **Primary:** `primary` 면 + `primary-foreground` 글자. 호버에서 면이 90%로 옅어진다.
- **Secondary / Outline / Ghost:** 보조 동작은 `secondary` 면(호버에 `accent`로 한 단계), 윤곽선 단추는 `input` 테두리 + `input` 30% 면(호버 50%), 고스트는 호버에만 `muted` 면이 생긴다.
- **Destructive:** 되돌릴 수 없는 동작은 `destructive` 면, 덜 강한 경우는 `destructive` 윤곽선.
- **Link:** `primary-text` 글자, 호버에 밑줄.
- **Focus:** 키보드 초점은 `ring` 색 2px 윤곽선을 2px 띄워 두른다(위험 단추 포함, `box-shadow` 링 없음). `index.css`의 전역 `:focus-visible` 규칙 하나가 모든 조작 요소에 같은 모양을 주므로 부품은 초점 규칙을 따로 적지 않는다. 비활성은 50% 불투명도.

### Navigation (Tabs)
- **Navigation:** 머리글의 페이지 탭. 비선택은 `muted-foreground` 글자, 호버에 `muted` 면, 선택은 그보다 밝은 `accent` 면 + `accent-foreground` 글자. 강조색을 쓰지 않아 영상보다 튀지 않는다. 마지막 탭(설정)은 오른쪽 끝으로 민다. 툴팁에 단축키(`Ctrl+1`~`Ctrl+8`)가 보인다.
- **Section:** 페이지 안 구역 전환. `muted` 묶음 면 안에서 선택 탭만 `primary` 면이고, 비선택 탭 호버는 묶음보다 한 단계 밝은 `accent` 면이다.
- **Panel:** 테두리 묶음 안에서 호버는 `muted`, 선택 탭은 `accent` 면이다.
- **Selectable Item:** 설정 분류(`Button`의 `item`·`item-selected` variant), 머리글·패널 탭, 폴더 트리, 대화상자 목록, 태그 고르기 행, 대기열 행·규칙, 대사 검색·모아보기 결과, 통계의 많이 본 영상 행, 영상·추천 카드는 `components/ui/selectable-item.ts`의 `selectableItem`으로 호버 `muted`·선택 `accent`를 칠한다. 안에 `muted` 배지·태그 칩·썸네일 자리가 있는 항목(영상·추천 카드, 검색·모아보기 결과, 대기열 행)은 `inner: "muted"`로 호버를 `popover`로 올린다. 쓰는 곳은 배치만 더하고 색을 덮어쓰지 않는다.

### Cards / Containers
- **Video Card:** `card` 면, 장식 `border` 테두리, `lg` 둥글기. 위는 16:9 썸네일(빈 자리는 `muted` 면 + 필름 아이콘), 아래는 고정 높이 정보 칸(제목 → 길이·시청 상태·자막·즐겨 보는 배지 → 시리즈 → 시청 통계 → 태그). 호버는 면이 `popover`로 한 단계 밝아지고(테두리는 장식 `border` 그대로, 안쪽 `muted` 배지·태그 칩은 계속 구별된다), 선택은 `ring` 테두리 + 1px 링이다.
- **List Item:** `card` 면, `lg` 둥글기, 안쪽 1rem. 선택은 `ring` 테두리 + `accent` 면.
- **Number Card:** `card` 면, `xl` 둥글기, 안쪽 1.5rem. 라벨 → 큰 숫자(Display) → 설명.
- **Empty State:** 점선 테두리, `xl` 둥글기, 가운데 정렬 제목·설명·동작.

### Inputs / Fields
- **Style:** `input` 테두리, 투명에 가까운 면(`input` 30%), `md` 둥글기, 높이 2.25rem.
- **Focus:** 단추와 같은 전역 초점 윤곽선(`ring` 2px, 2px 간격)이다. 테두리 색은 바뀌지 않는다.
- **Error / Disabled:** 오류는 `destructive` 테두리와 옅은 링, 비활성은 50% 불투명도.

### Chips (Status Badge)
- **Style:** `md` 둥글기, Label 글자, 상태 색 면 + 짝이 되는 진한 글자. 다 본 영상은 Mint, 보다 만 영상은 Sky, 파일 없음은 Rose, 아직 안 봄은 `muted`, 즐겨 보는은 Marker Yellow, "자막 있음"은 `input` 링만 있는 윤곽선.

### Notice (Signature Component)
앱의 공용 안내다. 위계는 오류 → 경고 → 성공 → 정보 네 가지이고, 여러 개가 겹치면 이 순서로 쌓으며 같은 문구는 한 번만 보인다.
- **Style:** `lg` 둥글기, 상태 색 10% 면 + 40~60% 테두리 + 색 아이콘, 글자는 `foreground`.
- **Placement:** 기본은 제자리에 쌓인다. 목록을 밀면 안 되는 자리는 떠 있는 배치를 쓴다. 라이브러리 페이지 안내는 격자 위쪽 띠(`NoticeStack layout="band"`), 셸 안내는 페이지 영역 모서리 묶음(`NoticeLayer`)이다. 떠 있는 안내는 `popover` 면·`xl` 둥글기·`shadow-lg`이고, 닫거나 접어서 아래 내용을 다시 볼 수 있다.
- **Behavior:** 긴 문구는 두 줄까지 보이고 "전체 보기"로 펼친다. 기본 세 개까지 보이고 나머지는 "더 보기"로 펼친다. 한 번 생긴 안내(요청 실패, 작업 결과)만 닫을 수 있고, 현재 상태에서 나온 안내는 원인이 사라지면 함께 사라진다.
- **Compact / Inline:** 좁은 자리용 작은 크기와, 목록 행에 한 줄로 들어가는 인라인 안내가 있다.

### Dialogs
- 모든 대화상자(확인·키 입력·키 안내·무작위 태그·업무 대화상자·재생 중 컨테이너)는 공용 틀 `components/ui/dialog.tsx` 하나를 쓴다. 화면 코드는 덮개·면·둥글기·여백·그림자·전환을 적지 않고 크기(`compact`·`default`·`wide`)와 배치(`center`·`container`)만 고른다.
- `popover` 면, `xl` 둥글기, 안쪽 1.5rem, 줄 사이 1rem, `shadow-lg`, 뒤에 `background` 80% 덮개. 머리글은 Title 제목 아래 0.5rem 띄워 `muted-foreground` 설명을 둔다.
- **단추 줄:** 틀의 마지막 줄이다. 대화상자를 끝내는 동작은 오른쪽 아래 끝에 [취소·닫기 = 윤곽선][확인 = 주 단추] 순서로 두고, 위험한 확인은 위험 변형이다. 단추가 하나면(닫기·캡처 취소) 그 하나가 오른쪽 아래다. 선택한 항목에 대한 보조 동작(태그 떼기·이름 변경·검수 동작 등)과 짧은 안내는 같은 줄 왼쪽에 둔다.

### Keyboard Key (Kbd)
- `muted` 면, `sm` 둥글기, Label 글자, `muted-foreground`. 키 안내와 툴팁에서 키를 보여 준다.

### Motion
전환 시간·곡선은 `web_tokens.json`의 `motion` 한곳에 있고(#259), `index.css`의 `@theme inline`이 Tailwind 기본 전환 값과 `animate-*` 유틸리티로 잇는다.

- **Quick** (`motion-duration-quick`, 100ms): 단추·탭·카드·입력란의 hover 색 전환(`transition-colors`)과 탭 내용 전환(`animate-tab-enter`).
- **Enter** (`motion-duration-enter`, 150ms): 떠 있는 층과 안내가 열릴 때. 대화상자·경고 대화상자·키 안내·덮개와 안내(Notice)는 투명도만(`animate-fade-enter`), 메뉴·우클릭 메뉴·선택 목록·필터 팝오버는 투명도와 트리거 쪽에서 커지는 작은 크기 변화(`animate-layer-enter`, `motion-enter-scale` 0.97).
- **곡선** (`motion-ease`): `cubic-bezier(0.23, 1, 0.32, 1)`. 처음에 빨리 다가와 바로 반응한 느낌을 준다.
- **Press** (`motion-enter-scale`, 0.97): 누르는 동안(`:active`) 모든 조작 요소(단추·탭·설정 분류·카드·목록 행·메뉴 항목)가 이 크기로 작아진다. `index.css`의 전역 규칙 하나가 맡고, 색·면은 올림과 같으며 비활성 요소는 작아지지 않는다. 전환 없이 바로 바뀐다. 줄어드는 기준점은 누른 자리(`lib/press-origin.ts`, 키보드로 누르면 가운데)라 원래 영역 가장자리에서 누르고 같은 자리에서 놓아도 그 요소가 click을 받는다.

**The Instant Close Rule.** 열 때만 전환하고 닫힘은 즉시다. 닫히는 층이 초점 가두기·포인터 차단으로 다음 입력을 막지 않는다. 열리는 도중에도 키·클릭은 바로 새 화면이 받는다.

**The Composite-Only Rule.** 투명도와 transform만 움직인다. 높이·너비·위치처럼 배치를 다시 계산하는 속성과 블러는 전환하지 않는다. `transition-all`은 쓰지 않는다.

**The Reduced Motion Rule.** `prefers-reduced-motion: reduce`이면 `index.css`의 전역 규칙 하나가 앱의 모든 전환·애니메이션(`animate-pulse` 포함)을 끈다. 진행 상태는 움직임 없이 막대·문구로 보인다. 첫 진입과 재생 복귀에는 탭 내용 전환이 없다(복귀 첫 프레임이 반투명하지 않게).

## Do's and Don'ts

### Do:
- **Do** 색·간격·둥글기·글자 크기를 바꿀 때는 `src/my_video_manager/web_tokens.json`을 고치고 `scripts/generate_web_types.py`로 `tokens.css`를 다시 만든다(**The Token Source Rule**).
- **Do** 모든 색을 테마 토큰 유틸리티(`bg-card`, `text-muted-foreground`, `border-ring` 등)로 쓴다.
- **Do** 특별한 모양이 필요하면 쓰는 곳에서 덮어쓰지 말고, `cva` variant를 가진 전용 컴포넌트를 만든다.
- **Do** 누름은 전역 규칙의 `motion-enter-scale` 축소 하나로 보인다. 부품마다 누름 색을 따로 칠하지 않는다.
- **Do** 선택과 키보드 초점은 `ring`(#818cf8)으로, 호버는 면 한 단계(목록 행 `muted`, 안에 `muted` 면(배지·태그 칩·썸네일 자리)이 있는 카드·행 `popover`)로 구별한다. 선택 면은 `accent`다.
- **Do** 썸네일·카드·패널의 크기를 내용이 오기 전에 확보한다.
- **Do** 1100×720 offscreen 스크린샷(`scripts/check_web_*.py --offscreen`)으로 결과를 확인한다.

### Don't:
- **Don't** `frontend/src/tokens.css`를 직접 고치지 않는다. 생성물이라 다음 생성 때 덮어써진다.
- **Don't** 원시 색 값, 임의 값(`w-[123px]`), 인라인 스타일, shadcn 기본 부품의 재스타일을 쓰지 않는다. `@shadcn/lint`가 오류로 막고, 인라인 비활성 주석도 쓰지 않는다.
- **Don't** 쉬는 면(카드·행·패널)에 그림자를 주지 않는다. 그림자는 떠 있는 층에만 쓴다.
- **Don't** 인디고를 장식이나 구역 구분에 쓰지 않는다. 하이라이트·상태 색도 그 의미에만 쓴다.
- **Don't** 실행 중 네트워크에서 글꼴·이미지·스크립트를 불러오지 않는다. 앱은 오프라인으로 동작한다.
