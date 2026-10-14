# 이슈 #43 웹 라이브러리 시험판 검증 보고

2026-10-14, Windows x64, Python 3.10.6, Node 22.16.0, PySide6 6.10.2에서 확인했다.
구현 커밋은 `28da75f`이며, 준비 절차·측정 스크립트·이 보고서는 후속 커밋으로 분리했다.

## 구현 결과

- `MVM_WEB_UI=1`일 때만 React 라이브러리로 전환한다. 기본 Qt 경로와 다른 페이지·mpv는 유지했다.
- 제목·태그 필터, 숨겨진 보석, 가상 썸네일 격자, 선택 상세, 기존 Qt 대화상자, 작업 메뉴, 빈 상태를 옮겼다.
- 단일 `LibraryBridge` QObject의 슬롯은 JSON 문자열과 원시 값만 주고받는다. 목록 변경·상세 변경·포커스 복귀·오류는 Signal로 알린다.
- `web_library_data.py`의 순수 변환 함수와 TypedDict가 데이터 계약의 원본이며 `scripts/generate_web_types.py`가 TypeScript 타입을 생성한다. setup·pytest가 계약 드리프트를 검사한다.
- 썸네일은 `mvm-thumb://video/<id>`에서 코어 공개 `video()`로 조회한 파일만 제공한다. URL 경로 입력·잘못된 ID·제외 영상은 거부한다. 패키지 자산·썸네일·명시한 개발 서버 외 요청과 외부 탐색도 차단한다.
- `MVM_WEB_DEV_URL`의 Vite 서버와 패키지의 오프라인 빌드를 모두 확인했다. 빌드는 커밋하지 않으며 `setup.ps1`이 생성하고 package-data가 포함한다.
- Qt·웹이 기존 대화상자와 검사 수명주기를 공유하도록 `LibraryOperations`와 관심 없음 되돌리기 대화상자 함수를 분리했다. 도메인 규칙·DB 구조·`playback.py`·`settings.py`·트레이는 변경하지 않았다.

## 자동 검증

| 검사 | 결과 |
|---|---|
| 기존 Qt 기준 테스트 | 893 passed |
| 전체 pytest | 922 passed in 166.10s: 기존 893 + 새 29 |
| `npm run lint` | 통과, @shadcn/lint 여섯 규칙 모두 error, 비활성화·예외 없음 |
| `npm run typecheck` | 통과 |
| `npm run build` | 통과 |
| 브리지 타입 `--check` | 통과 |
| 개발 모드 실창 검증 | WebChannel·썸네일·메뉴·mpv 전환 통과 |

최종 setup 로그: `.local/setup-43.log`. 전체 테스트 로그: `.local/pytest-43.log`.
Windows 샌드박스 안에서는 Vite 하위 프로세스 실행이 EPERM으로 막혀, 허용된 정상 실행 환경에서 빌드했다.

실제로 `frontend/src/lint-probe.tsx`에 다음 위반을 추가하고 `npm run lint`의 종료 코드 **1**을 확인한 뒤 파일을 제거했다.

```tsx
export const LintProbe = () => <div className="bg-red-500" />
```

```text
1:47  error  "bg-red-500" uses the raw Tailwind palette and no declared theme color is close to it.
shadcn/no-raw-colors
✖ 1 problem (1 error, 0 warnings)
Intentional violation exit: 1
```

전체 원문은 `.local/screens-43/lint-violation.txt`에 있다. 위반을 제거한 뒤 lint가 다시 통과했다.

## 키보드와 실제 창

`scripts/check_web_library.py --mode web --count 24 --verify`는 Windows 플랫폼의 실제 QWebEngineView와 복사한 실제 영상으로 검증한다. 세부 결과는 `.local/screens-43/web-24-verify.json`에 남는다.

- 방향키 선택, Enter 재생, 메뉴 키·Shift+F10 메뉴, 검색→태그→추천→격자의 Tab 이동.
- 웹에 포커스가 있는 상태의 Ctrl+1~Ctrl+6과 Alt+S. 기존 앱 전역 eventFilter가 먼저 처리한다.
- 실제 mpv Enter·카드 더블클릭 재생과 Esc 복귀. 0이 아닌 스크롤 위치에서도 선택·스크롤·격자 포커스가 유지된다.
- 태그·원어 자막·검수·시리즈·제목 변경 버튼에서 기존 Qt 대화상자를 열고 취소.
- 관심 없음 후 추천에서만 제거되고 라이브러리와 그 선택은 유지됨. 공개 코어 API로 되돌린 뒤 추천 복귀.
- DOM compositionstart/update/end와 InputEvent로 미완성 `ㅎ`을 입력했을 때 필터와 목록이 바뀌지 않고 입력값도 유지됨. 조합 중 Enter는 재생하지 않으며 조합 완료 `한글`에서만 필터 결과를 갱신함.

실제 Windows 한국어 IME의 한/영 전환·후보 선택은 **미확인**이다. 기본 Computer Use native pipe가 없고 Orca의 `press-key Hangul`도 지원하지 않았다. 관리자는 실창 IME를 사람이 확인할 항목으로 남기고 위 composition 자동 검증으로 보완하도록 지시했다. 이 자동 검증을 실제 IME 검증으로 간주하지 않는다.

## 비교 측정

같은 PC와 같은 데모 DB에서 Qt와 오프라인 웹을 순차 실행했다. 창의 클라이언트 크기는 1100×720이다. 시작 시간은 Python 스크립트 진입부터 첫 목록과 렌더 프레임 확인 후 250ms의 공통 안정화 대기까지이며, 프로세스 생성 이전 비용은 포함하지 않는다. 시작은 각 조건 1회이므로 정밀한 평균값으로 해석하지 않는다.

메모리는 앱과 자식 QtWebEngineProcess의 `WorkingSet64` 합계다. Windows 작업 관리자 **세부 정보 → 작업 집합(메모리)**와 같은 카운터이며 기본 탭의 전용 작업 집합과는 다르다. 공유 페이지가 프로세스 사이에 중복 합산될 수 있다. 측정용 PowerShell은 제외했다. PrivateMemorySize64도 원본 JSON에 보존했다.

| 항목 | Qt 24개 | 웹 24개 | Qt 5,000개 | 웹 5,000개 |
|---|---:|---:|---:|---:|
| 시작~표시 (ms) | 1368.71 | 1901.65 | 1564.99 | 1995.73 |
| 프로세스 작업 집합 합계 (MiB) | 144.47 | 430.22 | 181.72 | 537.40 |
| 목록 갱신 5회 중앙값 (ms) | 21.02 | 55.10 | 161.96 | 206.17 |
| 스크롤 프레임 간격 중앙값 (ms) | 16.00 | 33.30 | 16.00 | 33.20 |
| 스크롤 프레임 간격 p95 (ms) | 16.71 | 33.40 | 16.68 | 33.40 |

목록 갱신은 코어 조회부터 Qt repaint 또는 웹의 두 requestAnimationFrame 확인까지다. 웹에는 WebChannel·JS 관찰 왕복이 포함된다. 스크롤은 180px씩 120회 이동하며 Qt는 16ms QTimer, 웹은 requestAnimationFrame의 간격을 기록했다. 두 렌더러의 프레임 스케줄러가 달라 순수 렌더 CPU 비용의 비교는 아니다. 별도로 저장한 `scroll_step_ms`는 자동화 제어 왕복이 포함되므로 프레임률로 사용하지 않았다.

5,000개에서 웹 DOM에 렌더링된 카드는 12개였으며 화면과 overscan 범위에 따라 바뀐다. 웹은 이 환경에서 Qt보다 메모리를 약 356MiB 더 사용하고 목록 갱신 중앙값은 약 44ms 늘었다. 스크롤 간격에도 더 큰 변동이 있어 후속 페이지 전환의 성능 판단 근거로 남긴다. 현재 코드는 시험판의 기능 동등성을 목표로 하며 성능 동등성을 주장하지 않는다.

원본 결과: `.local/screens-43/{qt,web}-{24,5000}.json`. 데모 5,000개는 합성 파일을 공개 코어 API로 등록했으며 측정에서 실제 디코딩·스캔 비용은 제외했다. 데모 24개에는 지정된 원본 폴더에서 복사한 테스트 영상도 포함한다. 원본 폴더는 읽기만 했다.

## 스크린샷

- Qt: `.local/screens-43/qt-24.png`
- 웹: `.local/screens-43/web-24.png`
- 대량 목록: `.local/screens-43/qt-5000.png`, `.local/screens-43/web-5000.png`

모두 같은 데이터와 1100×720 클라이언트 크기이며 Git에서 제외했다. WebEngine은 windows 플랫폼으로 촬영했다.

## 추가 의존성과 선택

모든 프런트엔드 직접 의존성은 정확한 버전으로 고정하고 `package-lock.json`을 커밋했다. Python 추가 패키지는 없다. 기존 PySide6 6.10.2의 Addons에 WebEngine, Essentials에 WebChannel이 포함돼 있다. 시스템 수준 설치도 추가하지 않았다.

| 의존성 | 버전 |
|---|---|
| React / react-dom / @types/react / @types/react-dom | 19.3.0 |
| Vite | 8.3.4 |
| @vitejs/plugin-react | 6.1.2 |
| TypeScript | 5.9.3 |
| Tailwind CSS / @tailwindcss/vite | 4.3.3 |
| @shadcn/lint | 0.2.1 |
| ESLint | 9.39.1 |
| @typescript-eslint/parser | 8.71.2 |
| @tanstack/react-virtual | 3.14.19 |
| radix-ui | 1.8.1 |
| class-variance-authority | 0.7.1 |
| clsx | 2.1.1 |
| tailwind-merge | 3.7.0 |
| lucide-react | 1.57.0 |
| @types/node | 26.6.5 |

shadcn CLI 4.21.4를 일회 실행해 Button·Input·Badge·ContextMenu 소스를 생성했다. 런타임 의존성은 생성 컴포넌트와 Radix다. 기본 코드의 raw color·임의 값·미등록 애니메이션을 테마·정적 클래스에 맞춰 조정했다.

- ESLint는 공식 flat config 예시를 그대로 적용하고 TypeScript parser와 6규칙을 한 설정에서 확인하기 쉬워 선택했다. 임의 값·inline 스타일에 대한 예외 없이 동적 가상 행 높이와 위치만 CSS 사용자 정의 속성으로 전달한다.
- TanStack Virtual은 행 단위 가상화와 overscan·scrollToIndex를 제공하고 DOM 및 카드의 디자인을 강제하지 않아 선택했다.
- 숫자만 호스트로 쓰면 Chromium이 IP 주소로 정규화하므로 스킴을 `mvm-thumb://video/<id>`로 정했다.
- mpv 전환 시 숨은 웹 페이지가 사이드바 없는 폭으로 재배치되면 스크롤이 줄어든다. 재생 시작 전에 위치를 저장하고 격자 폭 재계산을 보류한 뒤 복귀 레이아웃에서 위치와 포커스를 복원한다.

## 사람이 직접 확인할 항목

- Windows 한국어 IME의 실제 조합·후보 선택·Backspace·Enter·검색 필터 조합. 자동 이벤트 검증과 구분한다.
- 평소 영상의 긴 재생, HEVC/AC3/DTS 음성·화면 품질, 여러 모니터·배율·창 크기에서 키보드와 포커스 표시.
- 측정된 메모리 증가와 스크롤 변동을 수용하고 다음 페이지의 웹 전환을 진행할지 판단.
- 관리자에게 요청된 별도 교차 검토. 이 작업에서는 push·PR·병합을 하지 않았다.
