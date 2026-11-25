# 웹 셸

웹 계약·개발 서버·새 페이지 추가는 [개발 문서](../development.md#웹-빌드와-개발-서버)를 보세요.

## 날짜 표시

화면의 날짜 모양은 `frontend/src/lib/dates.ts` 한 곳에서만 만듭니다. 날짜 `2026. 10. 21.`, 날짜와 시각
`2026. 10. 21. 15:04`(24시간제), 차트 축 같은 짧은 날짜 `10. 21.`이며 컴퓨터 시간대를 따릅니다.
날짜만 있는 값(`2026-10-21`)은 시간대와 상관없이 그 달력 날짜로 보입니다. 브리지는 화면에 보일 날짜를
ISO 문자열(필터 칩은 `range` 구조)로 넘기고 Python에서 표시용 날짜 문자열을 만들지 않습니다.
시각만 보이는 곳(자동 재시도 `15:04`)과 파일 이름은 예외입니다.
웹 셸은 웹 엔진보다 먼저 `QLocale`을 한국어로 고정하므로 Windows 표시 언어가 영어여도 날짜 입력 칸이
연·월·일 순서입니다. 구분 기호는 Windows의 한국어 간단한 날짜 형식(예: `yyyy-MM-dd`)을 따릅니다.

```powershell
.venv/Scripts/python.exe scripts/check_web_dates.py --offscreen
.venv/Scripts/python.exe scripts/check_web_dates.py --offscreen --videos 0
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-232 -- .venv/Scripts/python.exe scripts/check_web_dates.py --verify
```

영어(미국) `QLocale`에서 시작해 `.local/screens-232/`에 1100×720 화면(카드·상세·필터 칩과 날짜 입력 칸·모아보기·
통계 30일/365일·축 눈금·툴팁·설정의 백업·업데이트·번역 정책 만료 전/뒤)을 남기고, 보이는 글자에 ISO 날짜·`월/일/연`·
`오전/오후` 모양이 없는지 봅니다. `--verify`는 실창에서 날짜 입력 칸에 연·월·일 순서로 타자해 값이 그대로 들어가는지 확인합니다.
번역 정책은 기본 모델 만료일의 전날·다음 날로 찍으므로 검사 날짜와 상관없고, `--now 2026-11-01T03:00:00+00:00`처럼 검사 시각을 정할 수도 있습니다.

## 웹 대화상자

태그 편집·모든 태그 관리, 시리즈, 하이라이트 목록·편집,
자막 만들기·원어 지정, 자막 검수·구간 재생성·SRT 저장, 번역 CLI 선택을 웹으로 엽니다.
`web_dialogs_entries.py`의 진입 어댑터는 웹 대화상자만 엽니다. 제목 변경·영상 제외도 웹에서 처리하며, 제외 목록·관심 없음 복원은 폴더 관리의 해당 구역으로 이동합니다.
번역 CLI 선택지와 표시 이름은 `translation_cli.TRANSLATION_CLI_CHOICES`에서 읽습니다.

`web_dialogs_host.py`는 기존 웹 뷰 한 개의 대화상자 수명과 포커스를 관리하고,
`web_dialogs_models.py`는 `AppCore` 공개 메서드를 호출합니다. `web_dialogs_contract.py`의
`DIALOGS` 계약을 생성하면 웹 `DialogsLayer`가 같은 데이터·명령을 사용합니다.
태그 변경은 즉시 저장하고, 나머지 편집은 저장·취소로 확정합니다. 태그 후보를
명시적으로 선택하지 않은 Enter는 입력한 이름을 추가하며, IME 조합 Enter는 추가하지 않습니다.
검수 중에는 줄 ID·선택·스크롤을 유지하고 재생성 대기·진행 중에는 수정을 잠급니다.
부분 번역 내보내기는 경고 시점의 스냅샷을 Windows 기본 `QFileDialog`로 저장합니다.

웹 셸이 보일 때는 페이지 위의 React 모달 층을 사용합니다. 재생처럼 셸이
숨겨진 경우에는 같은 웹 뷰를 메인 창 소유의 window-modal `QDialog`에 잠시 옮깁니다.
mpv는 계속 재생하며 검수 장면 이동도 가능합니다. 닫으면 뷰를 원래 레이아웃에 돌려놓고
페이지 상태를 복원하며, 재생 중이면 `PlaybackPage.focus_content()`를 호출합니다.
React가 보고한 콘텐츠 크기로 컨테이너를 맞추고 메인 창 크기를 넘지 않습니다.
숨은 페이지의 레이아웃 크기는 고정해 가상화 격자의 재측정·스크롤 이동을 막습니다.
셸이 다시 보이면 열린 대화상자를 유지한 채 뷰를 즉시 셸로 돌려놓습니다.
추가 `QWebEngineView`, 프로필, 페이지를 만들지 않습니다.

`ShellModals`는 페이지 구현을 수정하지 않고 열린 `dialog`·`alertdialog`를 감지해
`dialogs.modalState()`로 알립니다. 실제 모달만 `Ctrl+1~8`·`Alt+S`의 셸 동작을 막고 키 이벤트는 입력·키 캡처로 전달하며,
Esc·Tab·Enter는 해당 모달이 처리합니다. 탐색·재생 진입·웹 재로드는 이전 모달 상태를 비웁니다.
`highlight-range`는 웹 구간 표시와 Qt 재생 진행 막대가 함께 쓰는 의미 색 토큰입니다.

검사는 독립 합성 데이터만 만들며 사용자 라이브러리를 변경하지 않습니다.
생성한 임시 영상·DB는 종료 시 정리합니다. 공용 모달 검사는 `frontend/checks/`에서
실제 Radix Dialog·Popover와 `ConfirmDialog`를 별도로 빌드해 사용하며 제품 번들에는 포함하지 않습니다.

```powershell
.venv/Scripts/python scripts/check_web_dialogs.py --offscreen
# 실창은 공유 데스크톱 잠금 안에서만 실행(vstack 플러그인의 지휘가 시작 때 이 경로에 둠. 경로 이름은 agent-orchestra 때의 것)
python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner issue-53 -- .venv/Scripts/python scripts/check_web_dialogs.py --real
```

1100×720 웹 화면과 검사 JSON은 `.local/screens-53/`에 남습니다. 실창 검사는
mpv 진행·재생 키 복귀·단일 뷰·라이브러리 선택/스크롤·Windows 저장창 열기/취소와
working set, 재부모화, DOM 커밋·레이아웃·프레임 시점을 측정합니다. 프레임 콜백은
화면 출력 기회이므로 모니터에 실제로 표시된 첫 픽셀이나 순간 깜빡임을 증명하지 않습니다.
`--windows-ime`를 더하면 실제 한국어 레이아웃에서 OS 키 입력을 추가 검사합니다.
OS가 자동화 키를 전달하지 않는 환경에서는 이 검사가 실패하며, 합성 composition 검사는
기본 실행에서 계속 검증합니다. 실제 IME·한자 후보·순간 깜빡임·저장창 덮어쓰기는 사람이 확인합니다.

## 폴더 관리·설정

태그 관리·번역 CLI 선택은 Python 진입점에서 공용 웹 대화상자를 엽니다.
설정의 완전 종료는 공용 `ConfirmDialog`의 `destructive` 확인을 거칩니다.

## 자막 대기열

`web_queue_page.py`는 활성 페이지에서만 500ms 주기로 조회합니다. 변경된 행·삭제 ID만 보내며
순서와 개수는 달라졌을 때만 보냅니다. 웹은 행별 구독을 사용해 진행률 변화로 다른 행을
다시 렌더하지 않습니다. 큐 도메인과 공개 작업은 그대로 사용합니다.
