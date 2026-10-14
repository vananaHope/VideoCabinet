# 화면 계층을 Qt 안의 웹 UI(React + shadcn/ui)로 만들고, 재생은 mpv로 유지한다

첫 버전의 Qt 위젯 화면은 다크 테마와 정리(#32)를 거친 뒤에도 투박하다는 평가를 받았다. 위젯 스타일시트로는 카드, 격자, 빈 상태 같은 현대적인 구성을 낼 수 있는 폭이 좁다. 그래서 ADR-0001의 화면 부분만 바꾼다.

- 재생 엔진(mpv)과 Python 앱 코어는 그대로 둔다. 화면 계층만 교체한다.
- 앱 창은 계속 PySide6다. 재생 외 화면은 그 안의 `QWebEngineView`에 띄우는 React + TypeScript + Tailwind v4 + shadcn/ui 웹 UI로 만든다.
- 웹 UI는 `QWebChannel`로 앱 코어의 공개 메서드만 호출한다.
- 재생 화면은 HEVC·AC3·DTS를 재생해야 하므로 지금처럼 네이티브 mpv 위젯을 쓰고, 웹 화면과 바꿔 보여 준다.

디자인이 깨지는 것을 막기 위해 `@shadcn/lint`의 규칙 6개를 모두 오류로 켠다.

- `no-restyle`, `no-raw-colors`, `no-arbitrary-values`, `no-inline-styles`, `no-unknown-classes`, `require-static-classes`
- 웹 UI 변경은 lint·타입 검사·빌드를 통과해야 완료로 본다.
- 색·간격·둥글기는 테마 토큰으로만 정한다. 특별한 모양은 사용하는 곳에서 덮어쓰지 않고, 변형(variant)을 가진 전용 컴포넌트로 만든다.

빌드한 웹 파일은 앱과 함께 배포하며, 실행 중 네트워크나 CDN에 기대지 않는다. 독립 실행 파일 빌드는 이 결정을 전제로 따로 정한다.

## Considered Options

- **Qt 위젯 유지 + Fluent 계열 위젯 라이브러리**: 가장 싸지만 구성의 자유도가 낮아 투박함이 크게 줄지 않는다.
- **Electron/Tauri로 전면 교체**: ADR-0001에서 기각한 이유(mpv를 창에 넣기 어렵고, 트레이·프로세스 관리를 새로 짜야 함)가 그대로 남는다.
- **Ant Design**: 다크 테마가 기본 제공되지만 관리자 화면 인상이 강하다. 사용자가 shadcn/ui와 lint로 디자인을 강제하는 쪽을 골랐다.

## Consequences

- 개발과 준비 절차에 Node가 더해진다.
- 앱 크기는 Qt WebEngine만큼 커지고, 메모리는 150~300MB쯤 늘어난다.
- 키보드 조작 규칙(창이 앞에 있을 때만, 예약 키, `Ctrl+1`~`Ctrl+6`)은 웹 화면에서도 같게 맞춰야 한다.
- 전환은 시험판(라이브러리 페이지 하나)으로 다음을 확인한 뒤 페이지별로 진행한다.
  - mpv 전환
  - 키보드만으로 조작
  - 한글 IME
  - 시작 속도와 메모리
  - 대량 목록 성능
