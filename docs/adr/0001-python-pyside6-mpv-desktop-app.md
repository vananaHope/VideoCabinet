# Python + PySide6 + mpv 데스크톱 앱으로 만든다

라이브러리에는 강의뿐 아니라 영화·예능도 들어오므로 mkv/HEVC/AC3·DTS 같은 파일을 가리지 않고 재생해야 한다. 브라우저·Electron 내장 플레이어는 이런 코덱의 상당수를 재생하지 못하므로 재생 엔진으로 mpv(libmpv)를 쓴다. mpv를 창 안에 쉽게 넣을 수 있고, AI 자막 생성(faster-whisper)도 Python 생태계라서 UI·재생·자막을 Python 하나로 묶을 수 있는 PySide6(Qt)를 택했다. 개인용 Windows 앱이며, 한 언어로 유지해 바이브 코딩으로 고치기 쉽게 하는 것이 목표다.

## Considered Options

- **Electron/Tauri + 웹 UI + Python 서버**: UI는 만들기 쉽지만 mpv를 창에 넣기 까다롭고 언어가 둘로 나뉜다.
- **.NET(WPF) + libmpv/LibVLC**: 견고하지만 AI 자막 쪽은 결국 별도 Python 프로세스가 필요하다.

> 화면 계층은 [ADR-0004](0004-web-ui-layer-with-shadcn-inside-qt.md)로 바뀌었다(재생 외 화면은 Qt 안의 웹 UI). 재생(mpv)과 Python 코어 결정은 그대로다.
