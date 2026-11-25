# 백업과 백업 복원

사용자가 보는 동작은 [사용 설명서](../user-guide.md#라이브러리-백업과-백업-복원)를 보세요.

`AppCore.create_backup(path, include_thumbnails=False)`는 SQLite backup API의 128페이지 단위
복사로 실행 중인 라이브러리를 ZIP 하나에 담습니다. UI에서는 작업자에서 호출합니다.
현재 시청의 저장 주기 전 진행분도 백업 사본에 반영하며 재생은 계속됩니다.
`manifest.json`에는 앱 식별자·백업 형식 버전·앱 버전·DB 버전·UTC 생성 시각·영상 수
(제외 영상 포함)·썸네일 포함 여부와 각 파일의 SHA-256, 생성 이유(`reason`)가 들어갑니다.
DB와 선택한 썸네일만 담고, 영상·모델·번역 임시 폴더·실행 잠금은 담지 않습니다.
`BackupResult.snapshot_seconds`는 DB 복사 시간이며 `max_step_seconds`는 복사 단계의 최대
경과 시간입니다. `perf_counter`로 재며 연결·디스크 I/O를 포함한 실제 읽기 잠금 시간의 상한 추정치입니다.
다른 연결의 쓰기로 남은 페이지가 늘어나면 재복사로 셉니다. **3회** 또는 **30초** 제한에서
`BackupBusyError`로 중단하고 기존 ZIP은 유지합니다. 오류의 `restart_count`와 `reason`
(`source_changed` / `deadline_exceeded`), 재생·자막 처리를 멈추고 재시도하라는 문구를 화면에 전달합니다.
453.8 MiB DB에서 일괄 복사는 UI 시청 저장을 3.15초 막았으므로 일괄 전환은 사용하지 않습니다.

`AppCore.inspect_backup(path)`는 파일 목록·SHA-256·SQLite 무결성·메타데이터를 모두 검사한
후 미리보기용 `BackupMetadata`를 돌려줍니다. 새 DB 버전, 다른 앱, 손상된 백업은 거부합니다.
추출 전에 선언된 전체 크기와 임시 디스크 여유 공간을 비교하고, 8 MiB를 넘는 썸네일과
대소문자만 다른 중복 파일 이름을 거부합니다.
`AppCore.request_backup_restore(path)`는 검증한 ZIP 사본을 데이터 폴더에 예약하고
`BackupRestoreResult.restart_required=True`와 파일 없음 위치의 다시 연결 안내를 돌려줍니다.
현재 DB나 작업 중인 받아쓰기·번역을 바꾸지 않습니다. `pending_backup_restore()`로 예약을 검사하고
`cancel_backup_restore()`로 취소할 수 있습니다. 화면의 재시작은 기존 정상 종료 절차로 작업자를
종료한 다음 새 프로세스를 시작합니다.

시작 경로는 `SingleInstance` 잠금을 잡은 뒤, `AppCore`나 DB 연결을 만들기 전에
`backup.apply_pending_backup_restore(database, instance=instance)`를 호출합니다. 다시 검증하고
임시 DB에서 필요한 이전을 완료한 다음, 현재 DB와 썸네일의 자동 백업을 먼저 남깁니다.
이전·압축·디스크 쓰기가 실패하면 현재 라이브러리는 유지됩니다. 썸네일은 기존 파일을
덮어쓰지 않고 충돌 시 새 이름을 사용하며 DB 파일의 `os.replace`가 유일한 커밋 지점입니다.
기존 WAL은 교체 전에 체크포인트합니다. DELETE 모드의 열린 파일은 Windows의 이름 바꾸기 실패로
교체를 막으며, 파일 사용/접근 권한 오류로 분류합니다.
교체 직전에 예약을 `.applying`으로 옮겨 교체 후 청소 실패나 비정상 종료가 다음 시작에서
같은 백업을 재적용하지 않게 합니다. 이 짧은 구간에서 강제 종료되어 원래 DB가 남은 경우에는
원본 ZIP 또는 남은 `.applying` 파일을 다시 `request_backup_restore`에 전달합니다.
24시간 지난 내부 `.restore-*` 임시 폴더와 `.applying`은 다음 시작 때 최선 노력으로 청소합니다.
현재 예약과 `.rejected` 파일은 자동 청소하지 않습니다.
없어진 영상 위치는 파일 없음으로 돌아갑니다. **외장 드라이브를 잠시 뺀 경우도 왕복 동일성의 예외**입니다.
드라이브를 연결하거나 새 감시 폴더를 추가해 다시 검사하면 내용 지문으로
기존 기록에 다시 연결됩니다. 썸네일을 제외한 백업은 기존 썸네일 캐시를 유지합니다.

손상된 백업과 임시 DB 이전 실패는 예약을 `*.rejected`로 격리하고 현재 데이터로 정상 시작합니다.
공간 부족·파일 사용 중 등 일시적 실패는 예약을 유지한 채 현재 데이터로 시작하고 다음 시작에 재시도합니다.
`__main__`이 결과를 `set_backup_restore_startup_result`로 전달하며 `AppCore.backup_restore_status()`는
ZIP을 다시 추출하지 않고 `status`(`scheduled` / `applied` / `rejected` / `deferred`),
`error_kind`, `error_message`, `rejected_path`를 조회합니다. 반복 실패는 `cancel_backup_restore()`로 취소합니다.
현재 DB 손상과 공간 부족 등이 겹쳐 현재 데이터로도 열 수 없으면 웹 셸 대신 짧은 Qt 복구 화면을 엽니다.
단일 인스턴스 잠금을 유지하면서 **다시 시도**, **예약 취소**, **데이터 폴더 열기**를 사용할 수 있습니다.
예약을 취소해도 원본 데이터·보존 사본은 지우지 않습니다. 읽기 전용 파일은 속성을 해제하라는 구체 안내를 유지합니다.

`migrate_library`는 버전을 올리기 전에 `backup_before_migration`을 호출합니다.
#64에서는 `LIBRARY_DB_VERSION`을 올리고 해당 이전 DDL을 추가하면 이 연결 지점을 그대로
사용할 수 있습니다. 빈 새 DB에는 자동 백업이 생기지 않습니다. 자동 백업은 데이터 폴더의
`backups/`에 최근 **5개**를 보존하며 `AppCore.automatic_backups()`로 최신순 경로를 얻습니다.
백업 복원 전 자동 백업은 썸네일을 포함하고, DB 이전 전 자동 백업은 DB만 담습니다.
오래된 ZIP 삭제 실패는 작업을 막지 않고 다음 생성 때 다시 정리합니다. 생성 자체가 실패하면 이전을
막으며 `BackupStorageError.kind`(`disk_full` / `file_in_use` / `storage_error`)와 조치 안내를 돌려줍니다.
설정의 자동 백업 목록은 시각·크기·이유를 표시하고 폴더 열기와 복원 미리보기를 제공합니다.
`AppCore.backup_inventory()`는 ZIP을 추출하지 않고 목록 메타데이터와 예약 존재 여부만 읽습니다.
자동 백업 이유는 `before_restore` / `before_migration`이며 이전 백업에 이유가 없으면
‘백업 복원 또는 DB 형식 변경 전(상세 이유 기록 없음)’으로 표시합니다. 이전 ZIP도 그대로 검사·복원됩니다.
