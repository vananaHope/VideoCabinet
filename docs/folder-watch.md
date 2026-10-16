# 실행 중 폴더 변경 감지 코어 (#132 앞부분)

`AppCore.create_folder_watch(on_batch_ready, *, watcher=None, **options)`는
`FolderWatch`를 한 번 생성한다. 생성만으로 감시나 스레드를 시작하지 않는다.
앱 수명 연결, 검사 작업자 연결, 설정 UI는 #131 병합 뒤 마무리 작업에서 구현한다.

```python
watch = core.create_folder_watch(enqueue_scan)
watch.start()
# enqueue_scan(folders)는 기존 검사 실행기에 요청을 넣는다.
# 실행기는 나중에 core.scan(folders=folders)를 한 번 호출한다.
core.set_automatic_detection_enabled(False)
core.set_automatic_detection_enabled(True)
watch.stop()
```

- `start()` / `stop()`은 앱의 감시 수명을 시작·종료하며 반복 호출할 수 있다.
- `core.automatic_detection_enabled()` / `core.set_automatic_detection_enabled(bool)`은
  `Settings`의 `library.automatic_detection_enabled`를 읽고 쓴다. 기본값은 `True`다.
  컨트롤러의 `set_enabled(bool)` / `enabled`도 같은 설정을 사용한다.
- 비활성화는 감시·대기 묶음·타이머를 취소한다. 다시 켜면 시작된 앱 수명 안에서만
  감시를 재개한다. 꺼져 있던 동안의 변경을 소급 검사하지 않는다.
- `core.add_watched_folder()` / `core.remove_watched_folder()`가 감시 대상을 즉시 갱신한다.
  컨트롤러의 `set_folders(Iterable[Path])`는 어댑터 연결에 쓰는 공개 API다.
- 위 수명·설정·폴더 변경 API는 하나의 소유 스레드에서 직렬 호출한다.
  이벤트 수신과 타이머는 다른 스레드에서 안전하게 들어올 수 있다.
- `on_batch_ready(tuple[Path, ...])`는 기본 타이머 스레드에서 호출된다.
  **짧은 enqueue 또는 Qt queued signal만 실행**해야 한다. 검사를 직접 실행하거나
  콜백에서 감시 수명을 바꾸지 않는다. 묶음은 분리하지 않고 한 번의 지정 검사로 넘긴다.
  마무리 작업은 수동 검사와의 실행기 공유, 이미 전달된 요청의 종료/해제 처리를 맡는다.
- 콜백 전달 실패는 로그를 남기고 묶음을 보존해 재시도한다. 전달 전에 실패하도록
  구현해야 중복 enqueue를 피할 수 있다. 파일 접근 실패도 검사하지 않고 다시 확인한다.
  `start()` / 감시 대상 갱신 실패는 자원을 정리하고 호출자에게 예외를 전달한다.
  호출자가 오류를 표시하고 명시적으로 `start()`를 재시도할 수 있다.

## 이벤트와 안정화

`watchdog==6.0.0`을 고정했다. Windows의 `ReadDirectoryChangesW` 기반 재귀 감시를
사용하므로 Qt 이벤트 루프나 하위 폴더별 Qt 감시 등록 없이 코어를 검증할 수 있다.
유휴 중 전체 폴더를 반복 순회하는 방식도 피한다.
[공식 Windows 구현 설명](https://python-watchdog.readthedocs.io/en/latest/installation.html)과
[고정 패키지 배포본](https://pypi.org/project/watchdog/6.0.0/)을 확인했다.
기존 `scripts/bundle_licenses.py`가 wheel의 Apache-2.0 `LICENSE`와 `COPYING`을 수집한다.

기본 디바운스는 0.5초이며, 변경 폴더 안의 파일 크기·`mtime_ns`를 1초마다 확인한다.
5초 동안 서명이 같으면 준비된 묶음을 한 번 전달한다. 파일 내용·미디어 정보·지문은
이 단계에서 읽지 않는다. 변경이 없으면 타이머도 없다. 디렉터리 이동은 자식 이벤트가
없어도 해당 하위 트리의 모든 파일을 확인한다. 중복·상하위 폴더는 한 번만 확인한다.
일반 폴더 수정 이벤트(`DirModifiedEvent`)는 자식 파일 이벤트와 중복되므로 무시한다.

Windows에서 이름 변경은 이동 이벤트, 폴더 간 이동은 삭제·추가로 전달될 수도 있다.
두 형태 모두 같은 디바운스·안정화 묶음에 원본과 대상을 넣는다. 여러 감시 루트 사이의
변경도 같은 컨트롤러에서 모은다. 삭제한 하위 폴더는 지정 검사에서 정보성 결과로,
감시 루트 자체의 소실과 접근 오류는 기존 실패 결과로 남는다.

`FolderWatcher`는 `start(folders, on_change)`, `update(folders)`, `stop()` 계약이다.
이동 이벤트의 원본·대상은 한 콜백에 넣으며 OS가 나눈 이벤트도 컨트롤러가 모은다.
`clock`(단조 초), `scheduler.call_later(seconds, callback)`(취소 가능한 핸들 반환),
`snapshot(folders)`(경로별 크기·수정 시각)과 대기 시간을 주입할 수 있다.
테스트의 `FakeWatcher`와 `FakeTime`은 실제 대기 없이 공개 동작을 검증한다.

5초 이상 쓰기를 멈췄다가 재개하는 복사는 완료로 오인할 수 있는 안정화 휴리스틱이다.
감시 중 루트/드라이브 소실·재접속, OS 이벤트 버퍼 넘침 복구는 #133에서 다룬다.
