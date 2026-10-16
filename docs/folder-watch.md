# 실행 중 폴더 변경 감지 코어 (#132 앞부분)

`AppCore.create_folder_watch(on_batch_ready, *, watcher=None, **options)`는
`FolderWatch`를 한 번 생성한다. 생성만으로 감시나 스레드를 시작하지 않는다.
앱 연결은 `FolderWatchControls`(`folder_watch_controls.py`)가 맡는다(아래 "앱 연결").

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
- `start()` 직후 짧은 시간(OS 감시의 첫 호출 전)의 변경은 잃을 수 있으므로 호출자는
  감시를 시작한 뒤 시작 검사를 돌려 그 틈을 덮는다. 폴더 추가 직후도 같다.
- `core.automatic_detection_enabled()` / `core.set_automatic_detection_enabled(bool)`은
  `Settings`의 `library.automatic_detection_enabled`를 읽고 쓴다. 기본값은 `True`다.
  컨트롤러의 `set_enabled(bool)` / `enabled`도 같은 설정을 사용한다.
- 비활성화는 감시·대기 묶음·타이머를 취소한다. 다시 켜면 시작된 앱 수명 안에서만
  감시를 재개한다. 코어는 꺼져 있던 동안의 변경을 소급 검사하지 않으므로 앱이 다시 켤 때
  전체 검사를 한 번 돌린다(아래 "앱 연결").
- `core.add_watched_folder()` / `core.remove_watched_folder()`가 감시 대상을 즉시 갱신한다.
  컨트롤러의 `set_folders(Iterable[Path])`는 어댑터 연결에 쓰는 공개 API다.
- 위 수명·설정·폴더 변경 API는 하나의 소유 스레드에서 직렬 호출한다.
  이벤트 수신과 타이머는 다른 스레드에서 안전하게 들어올 수 있다.
- `on_batch_ready(tuple[Path, ...])`는 기본 타이머 스레드에서 호출된다.
  **짧은 enqueue 또는 Qt queued signal만 실행**해야 한다. 검사를 직접 실행하거나
  콜백에서 감시 수명을 바꾸지 않는다. 전달받은 묶음은 한 번의 지정 검사로 넘긴다.
  수동 검사와의 실행기 공유, 이미 전달된 요청의 종료/해제 처리는 아래 "앱 연결"이 맡는다.
- 콜백 전달 실패는 로그를 남기고 묶음을 보존해 재시도한다. 전달 전에 실패하도록
  구현해야 중복 enqueue를 피할 수 있다. 요청 폴더 자체와 하위 항목의 접근 실패는
  고정 표식으로 기록해 정상 폴더와 함께 전달하고 실제 검사의 `ScanIssue`로 처리한다.
  주입한 스냅숏 어댑터가 범위 전체의 `OSError`를 던지면 안정화 시간 한 번만 재시도한
  뒤 접근 불가 표식으로 넘긴다. 묶음당 첫 실패만 traceback 없이 로그에 남긴다.
- 어댑터는 dispatcher를 먼저 시작한 뒤 루트별로 감시를 설치한다. 실패한 루트는
  건너뛰며 정상 루트는 계속 감시한다. `watch.failed_folders`와
  `WatchdogFolderWatcher.failed_folders`는 감시하지 못하는 루트의 `tuple[Path, ...]`를 제공한다.
  타이머 스레드가 바꾸는 불변 스냅숏이라 어느 스레드에서든 잠금을 기다리지 않고 읽는다.
  변경 알림은 없으므로 화면은 갱신 시점이나 주기적으로 읽는다.
  시작 때 없던 루트와 실행 중 사라진 루트 모두 아래 "루트 소실과 재연결"대로 자동으로 다시 연결한다.
  껐다 켜기로도 바로 다시 설치할 수 있다. `set_folders()` / 폴더 추가·해제는 새 루트만 소유 스레드에서
  설치하고, 이미 실패한 루트는 느린 드라이브에서 기다리지 않도록 재연결 타이머에 맡긴다.
  `start()`가 예외를 던지는 것은 observer 자체를 시작할 수 없는 경우다.
- `AppCore`는 영속 폴더 변경 뒤 감시 갱신 실패를 로그로 남기고 폴더 관리를 성공으로
  끝낸다. 폴더 해제의 시리즈 재구성도 계속한다. 일반 어댑터의 `update()` 예외는
  컨트롤러의 실패 목록에도 남으며 명시적인 대상 갱신으로 다시 시도할 수 있다.

## 이벤트와 안정화

`watchdog==6.0.0`을 고정했다. Windows의 `ReadDirectoryChangesW` 기반 재귀 감시를
사용하므로 Qt 이벤트 루프나 하위 폴더별 Qt 감시 등록 없이 코어를 검증할 수 있다.
유휴 중 전체 폴더를 반복 순회하는 방식도 피한다.
Windows에서는 `WindowsApiEmitter`를 직접 가져와 상속하며 import 실패를 조용히 polling으로 대체하지 않는다.
[공식 Windows 구현 설명](https://python-watchdog.readthedocs.io/en/latest/installation.html)과
[고정 패키지 배포본](https://pypi.org/project/watchdog/6.0.0/)을 확인했다.
기존 `scripts/bundle_licenses.py`가 wheel의 Apache-2.0 `LICENSE`와 `COPYING`을 수집한다.

기본 디바운스는 0.5초이며, 변경 폴더 안의 영상과 외부 자막 크기·`mtime_ns`를
`DirEntry.stat()`으로 1초마다 확인한다. `media.VIDEO_SUFFIXES`와
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

스냅숏 순회, 요청 폴더별 배정, 서명 비교, 전달 직전 확인은 상태 잠금 밖에서 한다.
배정은 경로마다 상위 폴더를 따라 올라가므로 비용이 경로 수 × 깊이에 비례한다.
그 사이 종료·폴더 변경·새 이벤트가 있으면 계산 결과를 버리고 다시 확인한다.

변경이 없으면 묶음 타이머도 없다(루트 생존 확인 타이머만 돈다). 디렉터리 이동은 자식 이벤트가 없어도 해당 하위 트리를
확인한다. 중복·상하위 폴더는 한 번만 확인한다.
일반 폴더 수정 이벤트(`DirModifiedEvent`)는 자식 파일 이벤트와 중복되므로 무시한다.
영상·외부 자막 이외 파일의 `modified`도 디바운스를 연장하지 않는다.
생성·삭제·이동 이벤트는 유지한다(Windows는 삭제된 디렉터리도 FileDeletedEvent로 보낸다).

Windows에서 이름 변경은 이동 이벤트, 폴더 간 이동은 삭제·추가로 전달될 수도 있다.
두 형태 모두 같은 디바운스·안정화 묶음에 원본과 대상을 넣는다. 여러 감시 루트 사이의
변경도 같은 컨트롤러에서 모은다. 삭제한 하위 폴더는 지정 검사에서 정보성 결과로,
감시 루트 자체의 소실과 접근 오류는 기존 실패 결과로 남는다. 감시 루트가 없을 때의 기록은
아래 "루트 소실과 재연결"을 따른다.

`FolderWatcher`는 `start(folders, on_change)`, `update(folders)`, `stop()` 계약이다.
선택적으로 `failed_folders`와 `reconnect() -> tuple[Path, ...]`를 제공한다.
이동 이벤트의 원본·대상은 한 콜백에 넣으며 OS가 나눈 이벤트도 컨트롤러가 모은다.
`clock`(단조 초), `scheduler.call_later(seconds, callback)`(취소 가능한 핸들 반환),
`reconnect_seconds`(기본 `RECONNECT_SECONDS`),
`snapshot(folders)`(경로별 크기·수정 시각 또는 접근 불가 표식 `None`),
`ready(path)`(쓰는 중이면 `False`, 열 수 있으면 `True`)와 대기 시간을 주입할 수 있다.
테스트의 `FakeWatcher`와 `FakeTime`은 실제 대기 없이 공개 동작을 검증한다.

시간은 폴더별 첫 이벤트와 마지막 이벤트로 잰다. 첫 이벤트부터 `MAX_BATCH_WAIT_SECONDS`(60초)가
지나지 않은 폴더끼리는 모두 준비될 때까지 함께 기다린다. 이동이 delete/create로 나뉠 수
있으므로 이 시간 안에는 원본·대상 동시 검사를 유지한다. 60초가 지난 폴더는 서명이
안정되고 전달 직전 확인까지 통과하면 다른 폴더를 기다리지 않고 먼저 전달한다.
계속 커지거나 잠긴 파일이 있는 폴더만 남으며, 남은 폴더는 각자의 첫 이벤트 시각을 유지한다.
따라서 오래 녹화 중인 폴더가 있어도 뒤에 생긴 이동 쌍은 60초를 새로 기다리지 않는다.
잦은 이벤트도 60초 뒤에는 묶음 전체의 디바운스를 연장하지 않지만, 마지막 이벤트가
디바운스 시간 안인 폴더는 그 폴더만 전달 후보에서 뺀다.
60초 넘게 복사되는 이동은 원본·대상 검사가 갈라질 수 있다. 또한 하나의 재귀 검사
범위 안에 있는 파일끼리는 분리하지 않으므로 같은 폴더의 다른 파일은 함께 기다린다.
파일 이벤트만 비재귀 안정화하는 최적화도 보류했다. 현재 `scan(folders=...)`는 재귀 검사라
안정화만 비재귀로 바꾸면 검사되는 하위 파일의 복사를 확인하지 못한다.
이후 이벤트 범위와 지정 검사 계약을 함께 바꿀 때 다룰 수 있다.

쓰기 핸들을 닫은 뒤 5초 이상 멈췄다가 다시 여는 복사는 완료로 오인할 수 있는 휴리스틱이다.

## 루트 소실과 재연결 (#133)

감시 루트를 지우면 watchdog emitter는 `DirDeletedEvent`를 보낸 뒤 스스로 멈추고,
드라이브·네트워크 연결이 끊기면 `ReadDirectoryChangesW` 오류로 이벤트 없이 멈춘다.
어느 경우도 watchdog이 알려 주지 않으므로 어댑터가 `reconnect()`에서 루트별 emitter
스레드의 생존을 확인한다. 멈춘 루트는 감시를 해제해 `failed_folders`로 옮기고 경고를
루트당 한 번 남긴다. 다른 루트의 감시와 앱 동작은 그대로 이어진다.

`FolderWatch`는 `reconnect()`를 제공하는 어댑터에 대해 시작된 동안
`RECONNECT_SECONDS`(10초)마다 타이머 스레드에서 이를 부른다. 건강한 루트는 메모리의
스레드 생존만 보고, 실패한 루트만 `os.path.isdir` 한 번으로 존재를 확인한다. 외장 드라이브를
다시 꽂으면 10초 안에 감지를 이어 가며, 확인이 끝난 뒤에야 다음 확인을 예약하므로 느린
네트워크 확인이 쌓이지 않는다. `reconnect()` 예외는 성공할 때까지 한 번만 로그를 남기고
다음 주기에 다시 시도하며(`stop()`이 초기화), 재예약은 `finally`에서 해 예외가 나도 주기 확인이 이어진다.

잠금 순서: watchdog dispatcher는 observer 잠금을 쥔 채 이벤트 콜백(`FolderWatch` 잠금)을 부른다.
따라서 **`FolderWatch` 잠금과 어댑터 잠금을 동시에 쥐지 않고, observer 호출(`schedule`·`unschedule`·
`stop`·`join`)은 어떤 우리 잠금도 쥐지 않고 한다.** 두 잠금은 상태 교체에만 쓴다. 어댑터는
설치·해제 중인 루트를 `_busy`로 표시해 소유 스레드와 타이머 스레드가 같은 루트를 동시에 다루지
않게 하고, 잠금 밖 설치 결과는 그 사이 해제·정지되었으면 되돌린다. `set_folders()`는 같은
폴더로 불리면 컨트롤러 자신의 갱신 실패(`_update_failed`)가 있을 때만 다시 갱신하며, 진행 중인
안정화 상태를 버리지 않는다. 남은 대기는 watchdog observer 잠금 안의 `CreateFileW`뿐이다
(존재 확인 직후 다시 끊긴 드라이브에서 소유 스레드의 `update()`/`stop()`이 잠시 기다릴 수 있다).

다시 설치한 루트는 일반 변경처럼 대기 묶음에 넣어 디바운스·안정화·폴더별 대기 규칙을
거친 뒤 `on_batch_ready`로 한 번 지정 검사에 넘긴다. 감시를 먼저 설치한 뒤 검사하므로
끊긴 동안과 재설치 직전의 변경이 모두 반영된다. 안정화 동안 루트 전체의 서명을 확인한다.

Windows emitter는 `WindowsApiEmitter`를 상속해(`BaseObserver(_Emitter)`) 세 가지를 더한다.
스스로 멈춘 emitter를 해제할 때 디렉터리 핸들을 두 번 닫지 않는다. 연결 끊김 읽기 오류를
스레드 밖 traceback 대신 `error`에 남겨 끊김 경고에 싣는다. 중지 중이 아닌 0바이트 읽기는
OS 이벤트 버퍼 넘침이므로 루트 전체 변경으로 넘긴다. 넘침이 이어져도 같은 대기 묶음에서
루트 검사 하나로 합쳐지며, 로그는 처음 한 번과 `stop()` 때의 횟수 집계만 남긴다.

### 끊긴 루트 아래 기록

지정·전체 검사에서 폴더가 없을 때(`FileNotFoundError`), 그 폴더를 담는 감시 폴더가 모두
없으면 드라이브 분리와 삭제를 구분할 수 없으므로 "접근 불가 폴더 아래 기록 보존" 규칙을
따른다. 그 아래 위치와 외부 자막 기록을 바꾸지 않고 "파일 없음"으로 만들지 않으며, 실패
`ScanIssue`로 보고한다. 루트 없이 하위 폴더만 지정한 검사도 같다. 감시 폴더가 남아 있는데
하위 폴더(겹친 안쪽 감시 폴더 포함)만 없으면 기존대로 삭제로 보고 위치를 정리한다.
비영상 판정 캐시는 기존처럼 정리하므로 다시 연결된 뒤 같은 서명도 새로 판정한다.
사용자가 감시 폴더째 지운 경우에도 위치가 남으며, 재생 때 위치 확인이나 감시 폴더 해제로 정리된다.
## 앱 연결 (#132 마무리)

`MainWindow`가 `FolderWatchControls`를 만들고, 컨트롤이 감시를 한 번 생성한다.
테스트는 `MainWindow(..., folder_watch_options=dict(watcher=..., stable_seconds=...))`로 주입한다.

- **스레드**: `on_batch_ready`는 `batch_ready` 신호의 `emit`이다. `QueuedConnection`으로 메인 스레드의
  `enqueue`에 넘기므로 타이머 스레드는 이벤트만 넣고 바로 돌아간다. `BlockingQueuedConnection`은 쓰지 않는다.
- **시작 순서**: 시작 검사 진입점(`scan_on_startup`)에서 `watch.start()`를 먼저 부른 뒤 #131 시작 검사를
  예약 작업자로 돌린다. 감시 시작 직후 놓친 변경은 시작 검사가 덮는다. 자동 감지가 꺼져 있으면
  시작 검사도 하지 않는다. `start()`가 실패하면 경고 로그만 남기고 시작 검사는 계속한다.
- **묶음 실행**: 받은 폴더를 순서를 유지한 집합에 합친다. 검사 작업자가 없으면 그 집합으로
  `core.scan(folders=...)`를 한 번 실행하는 `ScanWorker`를 시작한다(#131의 조용한 완료 규칙).
  작업자가 있으면(수동·시작·지정 검사) 버리지 않고 합쳐 두었다가 `scan_state_changed(False)` 뒤
  다음 이벤트 차례에 실행한다. 폴더·라이브러리 작업 대화상자나 Qt 모달이 열려 있는 동안에도
  0.5초 간격으로 미뤄 사용자가 고른 작업이 "검사 뒤 다시 시도"로 거부되지 않게 한다.
- **설정**: 설정 페이지의 `setAutomaticDetection(bool)`이 `FolderWatchControls.set_enabled`를 부른다.
  끄면 감지와 미룬 묶음을 버린다. 다시 켜면 인자 없는 전체 검사를 한 번 예약한다(진행 중인 검사가
  있으면 끝난 뒤). 시작에 실패했던 경우에는 다시 켤 때 `start()`를 다시 시도한다. 검사 중에는 바꿀 수 없다.
- **폴더 추가·해제**: 기존처럼 메인 스레드의 폴더 관리가 `AppCore`를 부르고 `AppCore`가 `set_folders`로
  감시 대상을 갱신한다. 추가 뒤에는 전체 검사를 한 번 돌리며, 폴더 선택 중 다른 검사가 시작됐다면
  그 검사가 끝난 뒤로 미룬다.
- **감시 실패 표시**: 폴더 관리 페이지가 보이는 동안 1초마다 `failed_folders` 스냅숏을 잠금 없이 다시 읽어
  바뀌면 `unwatched`를 보낸다. 실행 중 끊긴 루트도 같은 방식으로 나타나고 재연결되면 사라진다.
  시작 자체가 실패하면 모든 감시 폴더를 감시 실패로 표시한다. 꺼져 있으면 비운다.
- **재연결**: 다시 설치된 루트는 일반 묶음으로 `on_batch_ready`에 오므로 묶음 실행기가 그대로
  지정 검사 한 번으로 처리한다.
- **종료 순서**: 완전 종료가 확정되면(백업·검사·자막 확인을 통과한 뒤) `watch.stop()`을 먼저 부르고
  미룬 묶음을 버린다. 종료 확인 중에 온 묶음은 실행하지 않고 두었다가 종료를 취소하면 이어서 검사한다.
  트레이로 숨길 때는 감시를 계속한다.
