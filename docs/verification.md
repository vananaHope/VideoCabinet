# 검증 문서

화면 검사 스크립트와 사람이 실제 창에서 확인할 항목을 모았습니다. `--offscreen` 검사는 1100×720 화면을 `.local/` 아래에 남기고, 실창 검사(`--verify`·`--real`)는 공유 데스크톱 잠금 안에서 한 번에 하나만 실행합니다. `~/.agent-orchestra/bin/desktop_lock.py`가 없으면 그 뒤의 명령만 실행합니다. 환경 준비는 [개발 문서](development.md)를 보세요.

## 라이브러리

폴더·복합 필터·카드 크기는 `scripts/check_web_library_views.py --offscreen --count 5000`으로
1100×720 화면과 캐시 조건 판정/Settings 저장·JSON 응답을 포함한 브리지 시간을 확인합니다.
`--count 0`은 빈 상태, `--source <읽기 전용 영상 파일>`은 실제 320px/640px 디스크 크기 비교를 추가합니다.
`--verify --source <영상 파일>`은 데스크톱 잠금 안에서 실창 트리 키보드·mpv Enter/Esc 왕복 상태를 검사합니다.
앱 데이터는 worktree 밖 임시 폴더이고 출력은 `.local/screens-114/`입니다.
조건은 `library_views.py`에서 `LibrarySnapshot`의 공용 시청 결과와 자막 존재 인덱스를 사용합니다.
웹은 생성 계약의 보기 조건을 보내고 결과 ID·칩·폴더 트리를 표시합니다. 조건 변경은 자막 본문이나
영상 상세를 읽지 않으며 목록 갱신에서 만든 인덱스를 재사용합니다.
검색 조건의 태그 영역은 공용 `components/tag-picker.tsx`(여러 개 고름·즉시 실행, 뺄 태그 ID)이며
태그 목록은 `AppCore.tag_usage()`가 붙은 영상 수 순서와 검색용 정규화 이름(`key`)을 함께 보냅니다.
입력한 질의의 key는 `lib/tag-name-key.ts`가 동기로 만듭니다. 이 함수는 `generate_web_types.py`가 코어 `tags.tag_name_key_tables()`에서
생성한 `lib/tag-name-key-data.ts`(Python Unicode 버전의 할당 범위·제거 문자·공백·casefold 표)만 적용하며,
검사 스크립트가 전체 코드 포인트와 문맥에서 코어 `tag_name_key`와 같은지 비교합니다. 규칙을 바꿀 때는 `tags.py`를 고치고 다시 생성합니다.
즉시 실행·뺄 태그는 태그 편집 대화상자가 씁니다. 대화상자 데이터(`DialogData.tags`)에 같은 `tag_usage()` 목록을 싣고
붙은 태그(`rows`)를 뺄 태그로 넘기며, `listAll`로 전체 목록을 늘 펼치고 `onCreate`로 없는 이름을 새 태그로 붙입니다.
대화상자의 Esc는 `tagPickerKeepsEscape`로 조각이 먼저 처리할 Esc를 넘겨받지 않습니다. 조각 단독 동작은 `frontend/checks/tag-picker-fixture.tsx` 검사 번들로도 확인합니다.
`scripts/check_web_tag_picker.py --offscreen`은 `.local/screens-195/`에 태그 0개·몇 개·300개·검색·모두 보기·
고른 태그 40개 화면과 패널 배치 측정을 남기고, `--verify`는 데스크톱 잠금 안의 실창에서
키보드만으로 검색 → 고르기 → 칩 빼기와 실제 한국어 IME 조합 중 Enter 무시를 확인합니다.
`scripts/check_web_tag_dialog.py --offscreen`은 `.local/screens-191/`에 태그 편집 대화상자의 등록 태그 0개·모두 붙음·몇 개·300개·긴 이름
화면과 배치 측정, 붙이기·새 태그·조합 중 Enter·Esc 순서를 확인하고, `--verify`는 데스크톱 잠금 안의 실창에서 키보드만으로
고르기·새 태그 만들기·Esc 순서와 실제 한국어 IME 조합 중 Enter 무시를 확인합니다.
썸네일 크기 버전은 `.640.jpg` 파일명, 실패 진행 커서는 공용 Settings의 `thumbnail.cursor`에 저장합니다.
기존 `videos.thumbnail` 열과 Settings 형식은 그대로이며 대기 대상 부분 인덱스만 추가하므로 그 변경은 DB 버전을 올리지 않았습니다.

화면 검증과 대량 목록 측정은 Windows에서 `scripts/check_web_library.py`를 사용합니다.
`--prepare --count 24 --source <테스트 영상 폴더>`는 원본을 `.local/issue46/`로 복사하고 데모 데이터를 등록합니다.
`--prepare --count 5000`은 합성 영상 5,000개를 공개 코어 API로 등록합니다.
`--count`를 지정하면 웹 기본 상태의 1100×720 스크린샷과 측정 JSON을
`.local/screens-46/`에 남깁니다. `--verify`는 웹 키보드·composition 이벤트·복사본 mpv 복귀를 추가 확인합니다.
`--verify-shell`은 각 탭 스크린샷과 웹/mpv 왕복을, `--long-content`는 긴 제목·태그를 확인합니다.
`--profile-search`는 빠른 검색에 글자를 일정 간격(40·80·150ms)으로 연속 입력해 키마다 입력란 반영 시간과
마지막 키부터 결과·칩 반영 시간, 보기 요청 수, 그 사이 도착한 전체 목록 수를 `quick_search`에 남깁니다.
offscreen은 소프트웨어 그리기(약 20fps)라 프레임 시간이 부풀므로 비교는 데스크톱 잠금 안의 실창에서 합니다.
Linux 클라우드 세션에서는 웹 셸이 세그폴트하므로 `python scripts/linux_offscreen_check.py scripts/check_web_<이름>.py --offscreen --output <폴더>`로 스크린샷만 얻습니다(Linux 전용 우회, 초점·키 단언은 믿을 수 없음. 머리말 참고).
실제 Windows 한국어 IME의 조합·후보 선택은 사람이 별도로 확인해야 합니다.
`--verify-library --count 24 --long-content`는 테스트 복사본으로 하이라이트 0·32개,
시각 재생·Esc 복귀·기존 편집 저장을 확인합니다. 이 검사는 `.local/issue46/`의 데모
하이라이트를 다시 구성합니다. `--output .local/screens-48`로 증거 저장 위치를 지정할 수 있습니다.
`--profile-refresh`는 Python 처리, 라이브러리 JSON 파싱, 파싱 뒤 웹 프레임 대기를 나누어 기록합니다.

## 폴더 관리·설정

배치는 `scripts/check_web_scan_notice.py --offscreen`이 `.local/screens-201/`에 안내 없음·오류 1·150개·자막 경고 1·300개·섞임·긴 경로·검사 중·검사 실패·결과 닫음 화면으로 남깁니다.

```powershell
.venv/Scripts/python scripts/check_web_folder_watch.py --offscreen
```

실제 감시로 실행 중 추가·끄기·다시 켜기를 확인하고 설정·폴더 관리 이미지를 `.local/screens-132/`에 만듭니다.

검사와 비교 이미지(실제 데스크톱 없이 1100×720, 웹 기본 상태):

```powershell
.venv/Scripts/python scripts/check_web_folders_settings.py --offscreen
```

이미지와 결과 JSON은 `.local/screens-51/`에 생성합니다. `--offscreen` 없이 실행하면 캡처 없이
실제 Windows 창의 WebEngine 포커스·키 입력·재생 왕복을 검사합니다. 병렬 작업 중에는 공용
`~/.agent-orchestra/bin/desktop_lock.py run`으로 잠금을 잡고 실행합니다.
이 검사는 QTest 키 입력과 테스트 재생 어댑터를 사용합니다. Windows 한국어 IME, 기본 파일 선택
대화상자에서의 실제 경로 선택과 실제 mpv 영상·음성은 사람이 추가 확인합니다.

설정의 추천 기간 배치와 키보드 저장·추천 탭 반영은 `scripts/check_web_settings_recommend.py --offscreen`이 `.local/screens-204/`에 기본값·모두 바꾼 값·여러 칸 오류·긴 설명 화면으로 남깁니다.

설정의 업데이트 상태별 이미지(셸 새 버전 알림·내려받기·설치 전 확인·다음 실행 결과 포함)는 `scripts/check_web_update.py --offscreen`이 `.local/screens-140/`에 만듭니다.

## 재생 조작 줄과 영상 클릭

재생 화면은 Qt이므로 조작 줄은 웹 검사 대신 아래 검사로 확인합니다.

```powershell
.venv/Scripts/python.exe scripts/check_playback_controls.py --offscreen
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python.exe scripts/check_playback_controls.py --real
```

첫 명령은 가짜 플레이어와 코어의 받아쓰기·다듬기 결과로 1100×720 창의 기본 줄이 글자를 줄이지 않고 넘치지 않는지,
가장 넓은 줄(열린 구간 '구간 끝내기'·목록 밖 긴 속도 99.75×·다듬은 자막·자막 꺼짐·일시정지)과 1040 폭의 줄이 `compact_order` 순서(하이라이트·속도 단추 먼저)로만 줄여
넘치지 않는지, 줄인 단추에도 툴팁·접근성 이름이 있는지 확인하고 `.local/playback-controls/`에 위젯 이미지를 남깁니다.
모아보기 중의 가장 넓은 줄(⇤ ⇥ ↻ 반복 켜짐·구간 끝내기·99.75×·다듬은 자막)은 1100 폭에서, 같은 줄에 '모아보기 목록'·'⛶ 전체 화면 끄기'가 더해진 전체 화면 구성은 1100·1280 폭에서(일반 재생 가장 넓은 줄의 전체 화면 구성도 1100에서) 재며,
시간 표시와 단추가 눌려 잘리지 않는지 보고,
상태별 남은 폭을 결과 JSON의 `slack`에, 글자를 더 줄여 확보할 수 있는 폭을 `reducible`에 남깁니다.
뒤 이슈가 조작 줄에 단추(🔀)를 더하면 `compact_order`에 자리를 정하고 이 검사의 가장 넓은 상태에 그 단추를 넣습니다.
두 번째 명령은 합성 영상과 실제 mpv, Windows 마우스·키 입력으로 단추 클릭 뒤 재생 키, Tab 이동과 단추 초점에서의 →·Enter(재생 명령)·Space(단추 누르기),
키 안내 닫기 단추(앱 창 활성 유지), 전체 화면 조작 줄의 '전체 화면 끄기'·'목록으로'를 확인합니다. 실창 스크린샷은 찍지 않습니다.

영상 클릭은 실제 mpv 위에서 따로 확인합니다.

```powershell
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python.exe scripts/check_video_click.py
```

mpv는 `wid`로 넣은 자기 창을 비활성(`WS_DISABLED`)으로 만들어 마우스 입력을 부모인 Qt 영상 표면에 넘깁니다.
그래서 클릭은 mpv 입력 바인딩이 아니라 표면의 Qt 마우스 이벤트로 받고, 한 번/두 번 클릭은 `video_click.py`의 판정기가
Windows 두 번 클릭 판정 시간으로 가릅니다(Windows는 두 번째 누름을 `MouseButtonDblClick`으로만 보냅니다).
메뉴가 열린 채 영상을 누르면 Qt가 메뉴를 닫은 뒤 같은 `timestamp`를 단 누름을 표면에 다시 보내므로(replay), 그 누름은 클릭으로 세지 않습니다.
검사는 창 모드·전체 화면의 한 번/두 번 클릭, 클릭 뒤 재생 키, 전체 화면 커서 이동 → 조작 줄,
키 안내·재생 메뉴·속도 목록이 열린 상태의 클릭, 영상 전환 직후의 클릭, 클릭 직후 긴급 탈출 → 빠른 복원을 확인하고
mpv 영상 창이 비활성인지 단언합니다. 결과는 `.local/video-click/real-result.json`에 남깁니다.
대기 중인 한 번 클릭은 누름을 받은 엔진에 속하며, 창을 숨기거나 최소화하거나 목록으로 돌아가면 버립니다.

## 외부 자막·추천·모아보기·검색

영상 상세의 정보 탭에는 외부 자막 파일 이름, 언어별 줄 수와 읽기 경고가 나옵니다.
파일이 없으면 짧은 안내를 표시하고, 일부 블록만 읽힌 파일은 줄 수와 경고를 함께 표시합니다.
긴 파일 이름은 말줄임하며 마우스를 올리면 전체 이름을 확인할 수 있습니다.
검색의 외부 자막 결과에는 출처와 언어 칩(확인할 수 없으면 **언어 모름**)을 표시합니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_external_subtitles.py --offscreen
```

이 검사는 `.local/screens-66/`에 1100×720 화면(0개·여러 언어·실패·부분 성공·긴 이름·30개 파일·검색 선택/복귀)을 저장하고,
재검사 갱신과 검색 키보드 재생·복귀를 확인합니다. 실제 mpv 검사는 데스크톱 잠금 아래
`--verify`로 실행하며 실창 스크린샷은 찍지 않습니다.

추천(`Ctrl+2`)은 `web_recommend_page.py`의 웹 페이지이며 `AppCore.recommendations()`의 줄 목록을 보여 줍니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_recommend.py --offscreen
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-196 -- .venv/Scripts/python.exe scripts/check_web_recommend.py --verify --no-screenshots
```

첫 명령은 `.local/screens-196/`에 1100×720 화면(추천 0개·이어 보기 한 줄·여덟 줄 × 20개 위/아래·취향 맞춤·관심 없음 안내·우클릭 메뉴·
긴 기준 제목/카드 제목/이유·추천 영역을 뺀 라이브러리)과 배치 측정을 남깁니다. 전용 줄(이어 보기·다음 화·하이라이트 복습)의 우선 배정,
넘친 영상의 일반 줄 배정, 표시 순서, 줄 사이 왕복 키 이동·관심 없음·되돌리기를 확인합니다.
같은 종류의 『제목』을 봤다면 세 줄에서도 각 줄의 선택 기억·탭 재진입·가짜 재생 왕복이 섞이지 않는지 확인합니다.
두 번째 명령은 짧은 검증 영상을 만들어 실창에서 `Ctrl+2`, 실제 mpv 재생 왕복, 긴급 탈출 뒤 트레이 열기,
재생 중 창 닫기 뒤 트레이 열기가 같은 탭·같은 카드로 돌아오는지 확인합니다.

추천 기간은 설정의 '추천' 절(`recommendation-periods.tsx`)에서 바꾸며, 이름·설명·기본값·허용 범위는 `RECOMMENDATION_PERIODS`에서 받습니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_settings_recommend.py --offscreen
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-204 -- .venv/Scripts/python.exe scripts/check_web_settings_recommend.py --verify
```

첫 명령은 `.local/screens-204/`에 1100×720 화면(기본값·모두 바꾼 값·여러 칸 오류 위/아래·긴 이름과 설명)과 배치 측정을 남기고,
키보드 입력 + Enter 저장, 기본값 단추, 추천 탭 재진입 반영을 확인합니다. 두 번째 명령은 실창에서 `Ctrl+8` → Tab·Enter로
새로 추가됨 기간을 바꾸고 `Ctrl+2`로 추천 탭에 반영되는지, 기본값 단추로 되돌아오는지 확인합니다.

모아보기(`Ctrl+3`)와 검색(`Ctrl+4`)도 웹 페이지입니다.
모아보기는 기존 `ReelControls`의 재생·반복·복습 흐름을 쓰며, 검색은 장면 재생 후
`Esc`로 돌아왔을 때 검색어·결과·선택을 보존합니다. 검색 입력의 `↓`/`Enter`는
결과로 이동하고, 목록의 `Enter`는 선택한 장면을 재생합니다.
검색 탭의 첫 응답 전에 입력한 초안도 유지합니다. 초기 상태는 입력란을 덮지 않고, 브리지가 준비되면
최신 초안을 검색합니다. IME 조합 중이면 조합이 끝날 때까지 검색을 보내지 않습니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_reel_search.py --offscreen
.venv/Scripts/python.exe scripts/check_web_reel_search.py --verify --no-screenshots
```

첫 명령은 `.local/screens-49/`에 1100×720 웹 화면을
만듭니다(모아보기 0·2·503개·긴 메모/태그, 검색 입력 전·결과 없음·색인 준비·2개·500개 상한).
모아보기 완료 안내와 검색 오류 안내도 웹에서 확인합니다. 긴 메모는 목록에서 3줄로
줄여 보이며, 이 모아보기 페이지에 전체 메모를 펼치는 동작은 없습니다. 전체 메모는
라이브러리의 해당 영상 하이라이트 편집에서 확인할 수 있습니다.
두 번째 명령은 짧은 검증 영상을 작업 폴더에 생성해 실제 mpv 왕복, 키보드 조작,
조합 이벤트 중 검색 억제, 자동 전환·반복·복습을 검사합니다. 여러 작업자가 같은
데스크톱을 쓰는 환경에서는 반드시 `~/.agent-orchestra/bin/desktop_lock.py run`
아래에서 두 번째 명령을 실행합니다. 실제 한국어 IME 자판 입력과 다중 모니터·배율별
포커스 복귀는 별도 수동 확인 항목입니다.

웹의 일치 강조는 `search_matching.py`의 `match_spans`를 공유하고, 비동기 색인 준비는
`search_preparation.py`가 담당합니다. `search.py`는 Qt 의존성 없이 출처 이름과 결과 상한을
정의하며, 웹은 상한을 payload의 `limit`으로 받습니다.

## 통계

```powershell
.venv/Scripts/python scripts/generate_web_types.py --check
.venv/Scripts/python -m pytest -n auto -q
$env:QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu' # 아래 화면 검사 스크립트용. pytest에는 conftest.py가 적용
.venv/Scripts/python scripts/check_web_statistics.py --offscreen --count 0 --empty-library
.venv/Scripts/python scripts/check_web_statistics.py --offscreen --count 0
.venv/Scripts/python scripts/check_web_statistics.py --offscreen --count 8
.venv/Scripts/python scripts/check_web_statistics.py --offscreen --count 50000
```

1100×720의 기간 4개·지표 2개 및 요일/시간대·현황 화면을 `.local/screens-52/`에 저장합니다.
`--verify`는 실제 창에서 키보드 선택과 실제 mpv 재생·복귀를 검사하며 화면 캡처는 하지 않습니다.
여러 작업자가 공유하는 데스크톱에서는 반드시 `~/.agent-orchestra/bin/desktop_lock.py run` 안에서 실행합니다.

## 백업

`scripts/check_web_backup.py --offscreen`은 1100×720 화면과 키보드·진행·실패·예약 취소 흐름을 검사합니다.
`--startup applied|rejected|deferred`로 마지막 시작 결과를 각각 별도 프로세스에서 검사합니다.

## 자막 다듬기

`scripts/check_web_refinement.py --offscreen`은 1100×720 화면과 공개 UI 흐름을 검사합니다.
`--real`은 `~/.agent-orchestra/bin/desktop_lock.py run` 안에서 실행하며 실제 mpv 자막과 전환 키를 확인합니다.

## 자막 대기열

```powershell
.venv/Scripts/python scripts/check_web_queue.py --offscreen
.venv/Scripts/python scripts/check_web_queue.py --verify
```

`--offscreen`은 1100×720 웹 이미지와 300행 측정 결과를 `.local/screens-50/`에 저장합니다.
`--verify`는 캡처 없이 실제 WebEngine 포커스·키보드·확인 대화상자·트레이 경로를 검사합니다.
공유 데스크톱에서는 `~/.agent-orchestra/bin/desktop_lock.py run` 아래에서 실행합니다.
측정은 같은 AppCore 조회에 첫 행 진행률만 바꾸며, DB 포함 비용·표시 계층 비용·웹 DOM 반영과
다음 프레임 대기 시간을 구별합니다. 실 OS 한국어 IME 후보창과 시스템 트레이 메뉴의 실제 클릭은
사람이 직접 확인합니다. 합성 composition 검사는 조합 중 저장 방지만 확인합니다.

## 직접 확인할 항목

자동 테스트는 실제 mpv 화면을 포함하지 않습니다. 변경 후 아래를 실제 창에서 확인합니다.

- 한글·공백이 있는 감시 폴더와 하위 폴더를 추가해 썸네일과 제목이 표시되는지.
- MKV/HEVC 영상 및 AC3·DTS 음성이 창 안에서 영상·소리와 함께 재생되는지.
- 마우스 더블클릭과 방향키 + Enter로 영상을 열 수 있는지.
- 재생 중 표의 모든 키, Esc로 목록 복귀, 다른 앱에 포커스를 옮긴 뒤 키 입력이 이 앱을 조작하지 않는지.
- 창 모드에서 '목록으로'와 Esc로 돌아올 때 영상과 목록 사이에 빈 배경·이전 화면이 끼지 않는지. 하이라이트 목록·자막 등 재생 중 웹 대화상자를 열고 닫은 뒤에도 확인합니다.
- 대화상자를 Esc로 닫고 **같은 호출에서 즉시** 목록으로 돌아오는 경로는 창 모드·최대화 각 10회 확인합니다. 닫은 뒤 안정화하고 복귀하는 검사로 대신하지 않습니다. 대화상자 없는 일반 복귀의 이전 재생 화면 재노출은 10회, 일반·Esc·마지막 시청 정렬의 공백·겹침은 각 5회 이상 확인합니다.
- `scripts/check_return_transition.py`는 실제 mpv와 합성 자료를 만들고 FFmpeg 입력 단계에서 앱 클라이언트 좌표·크기만 잘라 60fps로 녹화합니다. TOPMOST와 활성 창을 검증하며 데스크톱 전체를 저장하지 않습니다. `gdigrab title=`은 GPU 자식 화면 갱신을 놓칠 수 있어 쓰지 않습니다. 아래 명령을 **desktop_lock** 안에서 실행하고, `--maximized` 및 `--kind plain/esc/sorted`를 바꿔 각 경로를 검사합니다. 한 잠금은 15분 안에 끝냅니다.

  ```powershell
  python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-250 -- .venv/Scripts/python.exe scripts/check_return_transition.py --kind dialog --count 10 --output .local/return-window
  .venv/Scripts/python.exe scripts/check_return_transition.py --analyze-only --output .local/return-window
  ```

  프레임 번호를 60으로 나눈 값 대신 녹화의 실제 PTS를 씁니다. `capture.log`의 입력 `start` 시각과 `phases.json`의 `wall_time`으로 복귀 요청을 맞추고, `frame-analysis.json`·`contact.png`를 직접 대조합니다. 자홍색은 합성 영상, 청록색은 목록 썸네일이며 `inspect`는 사람이 확인할 후보입니다. 대화상자를 **여는 동안** 보인 프레임과 **복귀 요청 뒤**의 결함을 구분합니다. 계측 자료는 `.local`에 두고 커밋하지 않습니다.
- 복귀 준비는 rAF 완료와 내용 있는 FBO, raster 덮개 flush, 웹 표면 교체 **후 새 토큰의 rAF 완료**, 그 뒤 주 창 UpdateRequest 처리 완료를 구분합니다. Qt UpdateRequest 완료는 DWM의 창별 present 확인 신호가 아니므로 실창 프레임 판정을 생략하지 않습니다. 덮개 도중 새 재생·키 입력·창 크기 변경·최대화·종료를 실행해 덮개가 남거나 초점을 가져가지 않는지도 확인합니다.
- 라이브러리를 아래로 스크롤한 뒤 '마지막 시청' 정렬에서 영상을 재생하고 돌아왔을 때 맨 위가 잠깐 보이지 않고, 기존 규칙대로 선택·스크롤·키보드 초점이 복원되는지.
- 복귀 직후 바로 다른 영상을 재생하거나 앱을 완전 종료해도 종료 중인 mpv가 새 영상·위치 보고에 섞이지 않고 시청이 한 번만 저장되는지. 모아보기 마지막 항목의 자동 복귀도 확인합니다.
- 최대화 → 전체 화면 → 전체 화면 끄기 및 전체 화면 모아보기 완료 복귀에서 창 크기가 중간에 바뀌는지. 이 창 상태 전환은 웹 복귀 준비와 별도로 확인합니다.
- 종료·재실행 후 라이브러리와 감시 폴더가 유지되는지.
- 감시 폴더 해제·직접 추가·파일 다시 연결·제외와 복원·제목 변경·최소 길이 설정이 다음 실행에도 유지되는지.
- 테스트 파일을 이름 변경·이동하거나 치운 뒤 검사하면 같은 영상으로 연결되거나 파일 없음으로 표시되는지.
- Insert/Delete 표시가 진행 막대와 목록에 반영되고 Home/End로 이동하는지.
- 열린 구간에서 Esc·창 닫기를 실행한 뒤 다시 열면 마지막 위치까지 저장되어 있는지.
- 하이라이트 목록에서 한글 메모, 시각 편집, 삭제와 재실행 후 보존을 확인하고 편집 중 Delete/Home/End가 글 편집에만 쓰이는지.
- 영상과 하이라이트의 태그 편집에서 붙지 않은 등록 태그 목록 고르기, 검색, 없는 이름 Enter로 새 태그, Esc 순서, Tab 이동·Space 버튼 조작과 태그 떼기가 동작하는지.
- 전체 태그 이름 변경·삭제가 양쪽에 반영되고, 태그 필터와 재실행 후 저장이 유지되는지.
- 실제로 5% 이상 본 뒤 목록의 보다 만 표시와 3초 전 이어보기, 다 본 뒤 처음부터 재생되는지.
- 앞으로 건너뛰기·되감기·배속·일시정지를 섞어도 시청 비율과 마지막 정지 위치가 구별되는지.
- 테스트용 데이터로 재생 중 강제 종료한 뒤 마지막 저장분과 이어볼 위치가 복구되는지.
- 영상에서 자막 요청 → 재생 중 처리 완료 → `/` 표시 전환 → 원어 지정 후 다시 생성되는지.
- 번역 전 `.` 안내, 번역 완료 후 `.` 원어/한국어 전환과 `/` 표시 전환이 각각 동작하는지.
- 번역 CLI 선택을 바꾼 뒤 재시작해도 유지되고, 실패·보류 재시도가 저장한 묶음부터 이어지는지.
- 긴 실제 영상과 평소 배속에서도 GPU 받아쓰기를 함께 켰을 때 재생이 매끄러운지.

- 번호 붙은 영상의 시리즈 표시와 편집 저장·재검사, 새 화 추가 후 순서를 확인하는지.
- PgUp/PgDn으로 시리즈와 일반 목록을 이동하고 경계에서 유지되며 이어보기·열린 구간 종료가 적용되는지.
- 모아보기 태그 필터와 Home/End 항목 이동, 같은 영상의 자동 전환·반복이 깜박임 없이 이어지는지.
- 지점 길이·구간 끝·영상 EOF(마지막 10초 안의 지점 포함)에서 다음 항목·영상으로 자동 전환되는지(webm·DTS mkv 포함).
- PgDn은 다음 영상의 첫 하이라이트, PgUp은 현재 영상의 첫 하이라이트로 이동하고 이미 첫 항목이면 이전 영상으로 이동하는지.
- 한국어 자판의 `₩`(백슬래시) 키로 반복을 켜고 끌 수 있고 상태 표시가 바뀌며, 끄거나 모아보기를 나갈 때까지 유지되는지.
- 항목 전환에도 배속·자막 표시가 유지되고, 원어/번역 선택은 같은 영상에서 유지되며 다른 영상은 원어부터 시작하는지.
- 모아보기 중 Enter·방향키·쉼표·슬래시가 동작하고, Insert/Delete로 만든 하이라이트가 목록 갱신 뒤 나타나며 열린 구간은 전환 때 닫히는지.
- Esc가 재생 → 모아보기 목록 → 라이브러리 순서로 돌아가고, 3초 재생 또는 짧은 항목 완주 뒤 마지막 복습 시각만 갱신되며 다 봄·보다 만·이어볼 위치는 그대로인지.
- 제외한 영상의 하이라이트는 숨겨지고 되돌리면 다시 나타나며, 일반 재생의 Home/End·PgUp/PgDn 동작은 유지되는지.
