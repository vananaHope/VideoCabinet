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
  구현해야 중복 enqueue를 피할 수 있다. 요청 폴더 자체의 접근 실패는 다시 확인하며
  묶음당 첫 실패만 traceback 없이 로그에 남긴다. 하위 항목의 접근 실패는 고정 표식으로
  기록하고 계속 확인한다. 실제 검사에서 기존 `ScanIssue`로 처리한다.
- 어댑터는 dispatcher를 먼저 시작한 뒤 루트별로 감시를 설치한다. 실패한 루트는
  건너뛰며 정상 루트는 계속 감시한다. `watch.failed_folders`와
  `WatchdogFolderWatcher.failed_folders`는 실패 루트의 `tuple[Path, ...]`를 제공한다.
  명시적인 `set_folders()` / 폴더 추가 또는 껐다 켜기로 다시 설치할 수 있다.
  자동 재접속은 하지 않으며, 런타임에 사라진 루트 감시는 #133에서 다룬다.
  `start()`가 예외를 던지는 것은 observer 자체를 시작할 수 없는 경우다.
- `AppCore`는 영속 폴더 변경 뒤 감시 갱신 실패를 로그로 남기고 폴더 관리를 성공으로
  끝낸다. 폴더 해제의 시리즈 재구성도 계속한다. 일반 어댑터의 `update()` 예외는
  컨트롤러의 실패 목록에도 남으며 명시적인 대상 갱신으로 다시 시도할 수 있다.

## 이벤트와 안정화

`watchdog==6.0.0`을 고정했다. Windows의 `ReadDirectoryChangesW` 기반 재귀 감시를
사용하므로 Qt 이벤트 루프나 하위 폴더별 Qt 감시 등록 없이 코어를 검증할 수 있다.
유휴 중 전체 폴더를 반복 순회하는 방식도 피한다.
Windows에서는 `WindowsApiObserver`를 직접 가져오며 import 실패를 조용히 polling으로 대체하지 않는다.
[공식 Windows 구현 설명](https://python-watchdog.readthedocs.io/en/latest/installation.html)과
[고정 패키지 배포본](https://pypi.org/project/watchdog/6.0.0/)을 확인했다.
기존 `scripts/bundle_licenses.py`가 wheel의 Apache-2.0 `LICENSE`와 `COPYING`을 수집한다.

기본 디바운스는 0.5초이며, 변경 폴더 안의 영상과 외부 자막 크기·`mtime_ns`를
`os.stat()`으로 1초마다 확인한다. `media.VIDEO_SUFFIXES`와
`external_subtitles.EXTENSIONS`를 재사용하며 `.part` 등의 임시 파일은 안정화에서 뺀다.
외부 자막은 부분 복사 상태에서 파싱하지 않도록 포함한다.
5초 동안 서명이 같으면, 직전 전달 때와 서명이 다르거나 새로 보인 파일에
`ready(path)`를 호출하고 크기·mtime을 다시 `os.stat()`으로 읽는다.
Windows 기본 `file_ready()`는 `CreateFileW(GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING)`으로
읽기 핸들만 열었다 닫는다. 공유/잠금 위반이면 안정화 시간을 다시 센다.
[공유 모드 계약](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)에
따라 쓰기 핸들이 열린 `CopyFileExW` 복사도 기다린다. 내용·미디어 정보·지문은 읽지 않는다.
영구 접근 거부 등 다른 열기 오류는 실제 검사의 `ScanIssue`에 맡긴다.
비Windows의 기본 `open()`은 Windows의 공유 잠금 보장을 제공하지 않는다.

변경이 없으면 타이머도 없다. 디렉터리 이동은 자식 이벤트가 없어도 해당 하위 트리를
확인한다. 중복·상하위 폴더는 한 번만 확인한다.
일반 폴더 수정 이벤트(`DirModifiedEvent`)는 자식 파일 이벤트와 중복되므로 무시한다.
영상·외부 자막 이외 파일의 `modified`도 디바운스를 연장하지 않는다.
생성·삭제·이동 이벤트는 유지한다(Windows는 삭제된 디렉터리도 FileDeletedEvent로 보낸다).

Windows에서 이름 변경은 이동 이벤트, 폴더 간 이동은 삭제·추가로 전달될 수도 있다.
두 형태 모두 같은 디바운스·안정화 묶음에 원본과 대상을 넣는다. 여러 감시 루트 사이의
변경도 같은 컨트롤러에서 모은다. 삭제한 하위 폴더는 지정 검사에서 정보성 결과로,
감시 루트 자체의 소실과 접근 오류는 기존 실패 결과로 남는다.

`FolderWatcher`는 `start(folders, on_change)`, `update(folders)`, `stop()` 계약이다.
이동 이벤트의 원본·대상은 한 콜백에 넣으며 OS가 나눈 이벤트도 컨트롤러가 모은다.
`clock`(단조 초), `scheduler.call_later(seconds, callback)`(취소 가능한 핸들 반환),
`snapshot(folders)`(경로별 크기·수정 시각 또는 접근 불가 표식 `None`),
`ready(path)`(쓰는 중이면 `False`, 열 수 있으면 `True`)와 대기 시간을 주입할 수 있다.
테스트의 `FakeWatcher`와 `FakeTime`은 실제 대기 없이 공개 동작을 검증한다.

하나의 묶음을 폴더별로 쪼개는 안정화는 적용하지 않았다. 기존 이벤트 계약이 폴더 목록이고
이동이 delete/create로 나뉠 수 있어 원본·대상 동시 검사를 유지한다. 임시 파일로 인한
대기는 해결했지만, 같은 묶음 안에서 영상/외부 자막 자체가 계속 쓰이면 함께 기다린다.
파일 이벤트만 비재귀 안정화하는 최적화도 보류했다. 현재 `scan(folders=...)`는 재귀 검사라
안정화만 비재귀로 바꾸면 검사되는 하위 파일의 복사를 확인하지 못한다.
이후 이벤트 범위와 지정 검사 계약을 함께 바꿀 때 다룰 수 있다.

쓰기 핸들을 닫은 뒤 5초 이상 멈췄다가 다시 여는 복사는 완료로 오인할 수 있는 휴리스틱이다.
감시 중 루트/드라이브 소실·재접속, OS 이벤트 버퍼 넘침 복구는 #133에서 다룬다.
