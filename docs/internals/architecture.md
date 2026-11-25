# 코어 구조와 DB

## 모듈

- `core.py`: 앱 코어 공개 API인 `AppCore`, 기능별 위임, SQLite 연결, 키 명령·속도 범위 정책.
- `__init__.py`: Python 패키지 선언.
- `__main__.py`: 실행 진입점, 데이터 폴더·어댑터 준비와 앱 시작.
- `web_shell.py`, `web_shell_bridge.py`, `web_page_registry.py`: 단일 웹 뷰·채널·페이지 등록·탭/재생 왕복.
- `web_*_page.py`, `web_*_bridge.py`, `web_*_data.py`: 페이지별 작업과 공개 JSON 계약.
- `web_dialogs_entries.py`, `web_dialogs_host.py`, `web_dialogs_models.py`: 웹 업무 대화상자 진입·모달 수명주기·명령.
- `library_operations.py`, `library_controls.py`: 검사 작업자·라이브러리 관리 명령·파일 선택 연결.
- `reel_controls.py`: 모아보기 재생 엔진 전환과 재생 화면 상태 연결.
- `qt_keys.py`: 재생과 웹 설정 키 캡처가 공유하는 Qt 키 이름 변환.
- `time_display.py`: 웹 대화상자와 네이티브 재생 화면이 공유하는 시각 표시.
- `ui.py`: 페이지 연결, 창 내부 키 전달, 재생 시작·종료와 트레이 연결을 담당하는 메인 셸.
- `theme.py`: 웹 토큰 기반 네이티브 재생·트레이·공용 경고의 팔레트와 스타일.
- `library_details.py`: 선택 영상의 상세 요약 결과. `AppCore.library_details`는 자막·번역·하이라이트 소유 모듈에서 한 영상만 조회한다.
- `playback_page.py`: 영상 중심 재생 배치·아래쪽 바(조작 줄)·작업 메뉴와 `show_position`·`show_reel` 표시 API. 전체 화면의 임시 바와 Esc 우선순위를 처리한다. 재생 키와 조작 줄 단추는 모두 `run_command(command)`로 명령 하나를 실행한다. 새 단추·영상 클릭도 이 함수를 부르며, 좁은 창에서 글자를 줄일 단추는 `compact_order`에 더한다.
- `playback_help.py`: F1·⌨ 단추로 켜는 별도 반투명 안내 창. 현재 키 배치·모아보기 키 의미·하이라이트 색 범례를 mpv 위에 표시한다. 앱 창의 활성 상태와 초점은 가져가지 않고, 닫기 단추로 마우스로도 닫는다.
- `settings.py`: JSON 값을 저장하는 공용 `Settings` 저장소. 라이브러리·번역·키 배치 설정이 함께 사용하며 키 배치는 `keys.bindings`에 저장.
- `single_instance.py`: 데이터 폴더별 중복 실행 방지와 기존 창 활성화 요청.
- `tray.py`: 트레이 숨기기·복귀·완전 종료와 대기열 완료 알림.
- `library.py`: `Video`·`Location`·`WatchedFolder`, 지문·검사 캐시, 위치·파일 없음·제외, DB v1→v2 이전.
- `adapters.py`: ffprobe 정보 읽기, ffmpeg 썸네일 캡처, python-mpv를 통한 libmpv 제어.
- `media.py`: ffprobe JSON 파싱 및 정지 이미지·영상 판정 순수 함수.
- `playback.py`: 재생 시작·위치·종료를 코어 기능에 알리는 공용 계약.
- `viewing.py`: 시청 구간 합집합·분류·이어볼 위치, 시청 전용 SQLite 테이블과 주기 저장·복구.
- `series.py`: 제목 틀·번호 추출, 자동 묶기, 사용자 편집 보존, 시리즈 순서와 이전·다음 영상 결정.
- `highlights.py`: 지점·구간 하이라이트, 메모 저장·편집·삭제, 열린 구간 종료와 이전·다음 탐색 규칙.
- `highlight_editing.py`: 하이라이트 시각 입력의 범위 제한과 수정하지 않은 정밀도 보존.
- `highlight_ui.py`: 재생 진행 막대와 읽기 전용 하이라이트 패널·현재 위치 따라가기.
- `reel.py`: 모아보기 자연 정렬·순서·반복·영상 단위 이동, 재생 지시와 복습 판정.
- `revisit.py`: 하이라이트별 마지막 복습 저장과 영상별 조회.
- `recommendation.py`: 추천 후보 줄 만들기, 줄 정의 `ROW_DEFINITIONS`의 표시 순서·전용 여부, 줄 배정 순수 함수 `assign_rows`(전용 줄부터 배정하고 줄마다 최대 20개·영상마다 한 줄), 시리즈별 후보와 관심 없음 상태.
- `tags.py`: 태그 이름 정규화, 공유 태그·연결 저장, 자동 완성과 태그별 조회.
- `tag_editing.py`: 직접 입력한 이름과 명시적으로 고른 자동 완성 후보의 확정 규칙.
- `subtitles.py`: 영속 자막 대기열, 원어·원어 자막 저장, 받아쓰기 Protocol과 SRT 변환.
- `subtitle_queue.py`: 자동 자막 규칙, 요청 순서·앞당기기와 영상별 대기열 상태.
- `transcription.py`: 별도 프로세스의 faster-whisper large-v3-turbo GPU 어댑터.
- `cuda_runtime.py`: 첫 자막 요청의 CUDA·Whisper 다운로드, 해시 검증, 취소와 완료 파일 재사용.
- `windows_job.py`: 앱 종료 시 받아쓰기 프로세스 트리를 정리하는 Windows Job 어댑터.
- `subtitle_controls.py`: 웹 자막 요청 진입, 백그라운드 처리, 완료된 자막의 플레이어 연결.
- `translation.py`: 번역 자막과 줄별 참조, 묶음 진행 저장·원자적 교체, 보류·재시도, 재생 중 언어 선택.
- `translation_cli.py`: 읽기 전용 구독 CLI 어댑터, 구조화 응답 검증과 오류 판정 순수 함수.
- `opencode_go.py`: OpenCode Go 연결과 번역 요청 어댑터.
- `secret_store.py`: Windows 사용자별 DPAPI로 비밀 값을 암호화해 데이터 폴더에 보관.
- `translation_models.py`: 번역 모델 목록과 모델 선택 계약.
- `translation_controls.py`: 번역 작업자와 웹 CLI 선택·재시도 진입.
- `review.py`: 원어·번역 검수, 구간 재생성·보호와 SRT 내보내기.
- `transcript_originals.py`: 검수 전 원어 자막 원문(분석용, v12)의 기록·조회.
- `key_bindings.py`: 명령 목록·키 정규화·충돌 검사와 키 배치 변경분 저장.
- `key_display.py`: 방향키 기호 등 화면 표시용 키 이름 변환. 한 글자 기호 키는 이름을 함께 보여 준다(예: `' (작은따옴표)`).
- `search.py`: 검색 결과와 검색어 정규화, 원어·번역 출처를 구분하는 자막 FTS5 색인.

## 테스트 파일

- `tests/test_core.py`: 임시 실제 파일·임시 DB, 가짜 미디어 어댑터·시계로 코어 공개 동작만 검증.
- `tests/test_settings.py`: 공용 설정의 손상된 저장 값·기본값·재저장 검증.
- `tests/test_key_bindings.py`: 공개 코어 API로 즉시 반영·재실행·충돌·복원·새 기본 명령 추가를 검증.
- `tests/test_library.py`: 이동·복사·파일 없음·제외·길이 설정·캐시와 이전 DB의 기록 보존 검증.
- `tests/test_library_return_ui.py`: 웹 셸에서 트레이 복귀와 모아보기 전환 뒤 라이브러리 갱신 검증.
- `tests/test_library_details.py`: 공개 AppCore API로 상세 요약과 파일 없음·제외 시 기록 보존 검증.
- `tests/test_playback_page_ui.py`: 재생 페이지의 키 우선순위, 전체 화면·키 안내·메뉴와 창 상태 복원, 아래쪽 바 표시 검증.
- `tests/test_media.py`: 고정 ffprobe JSON으로 미디어 판정을 검증.
- `tests/test_series.py`: 번호·제목 틀 순수 함수와 공개 코어 API로 묶기·복사본·편집·재검사·탐색 검증.
- `tests/test_viewing.py`: 순수 구간 계산과 코어 공개 동작으로 분류·탐색·배속·이어보기·복구를 검증.
- `tests/test_highlights.py`: 키 명령, 종료·전환·되감기, 탐색 경계, 메모·시각 편집과 저장 보존을 공개 코어 API로 검증.
- `tests/test_reel.py`: 공개 코어 API로 자동 전환·키 의미·복습 시계·시청 비간섭·저장 보존을 검증.
- `tests/test_recommendation.py`: 줄 배정·넘침 순수 함수와 추천 줄 선정·정렬·시리즈 예외, 관심 없음·재실행 보존 검증.
- `tests/test_web_recommend_page.py`: 추천 탭 브리지·Ctrl+2·재생 왕복·관심 없음과 되돌리기 검증.
- `tests/test_tags.py`: 공개 코어 API로 태그 추가·떼기·정규화·자동 완성·이름 변경·삭제·필터·재실행 보존을 검증.
- `tests/test_subtitles.py`: 가짜 받아쓰기와 실제 임시 DB로 요청·FIFO·언어·재생성·재시작·실패 복구를 검증.
- `tests/test_subtitle_queue.py`: 자동 규칙·직접 요청 우선순위·앞당기기·취소·완료 알림 검증.
- `tests/test_queue_review.py`: 재등록·태그 부착·일괄 재시도·진행 보고와 대기열 회귀 검증.
- `tests/test_transcription.py`: GPU 없이 가짜 스크립트로 JSON·오류·취소·부모 강제 종료 시 자식 정리를 검증.
- `tests/test_translation.py`, `tests/test_translation_cli.py`: 코어 공개 동작과 순수 함수로 번역 대상,
  줄 일대일 대응, 원어 재생성, 한도 보류, 재시작·재시도, 부분 번역, CLI 프로세스 정리와 `.` 전환을 검증.
- `tests/test_review.py`: 자막 검수·구간 재생성·동시 응답 보호·부분 번역과 SRT 내보내기 검증.
- `tests/test_search.py`: 검색 범위, 부분 일치, 갱신·재실행, 장면 재생과 이어보기 규칙을 코어 공개 API로 검증.

## 시청·태그 코어 API

시청 기본값은 `AppCore(viewing_settings=ViewingSettings(...))`로 주입합니다.
`finished_ratio`, `abandoned_ratio`, `favorite_count`, `resume_rewind`, `save_interval`을 바꿀 수 있으며
설정 화면은 후속 범위입니다. `favorite_count`는 틀어보기를 뺀 시청(다 본 시청·보다 만 시청) 횟수의 기준이고
기본값은 3입니다. 재생 어댑터는 mpv의 `time-pos`를 보고하고 `seek`부터
`playback-restart`까지는 구간을 연결하지 않습니다. 화면은 이 보고를 UI 스레드에서
`core.playback.report(position, seeked=...)`로 전달합니다.
`core.playback.start(video_id, position, record_viewing=False)`로 시작하면 시청 기록이 생기지 않아
후속 하이라이트 모아보기에서도 같은 재생 연결을 사용할 수 있습니다.

태그 공개 API는 `AppCore.tags(prefix="")`, `create_tag(name)`, `rename_tag(tag_id, name)`,
`delete_tag(tag_id)`입니다. `add_video_tag(video_id, name)`과 `add_highlight_tag(highlight_id, name)`은
이름으로 기존 태그를 재사용하거나 만들고 연결합니다. `video_tags(video_id)`·`highlight_tags(highlight_id)`로
붙은 태그를 읽고 `remove_video_tag(video_id, tag_id)`·`remove_highlight_tag(highlight_id, tag_id)`로 뗍니다.
후속 기능은 `videos_for_tag(tag_id)`와 `highlights_for_tag(tag_id)`로 대상 객체를 조회할 수 있습니다.
태그별 영상은 제목·ID 순, 하이라이트는 영상 ID·시작 시각·ID 순입니다.

```powershell
.venv/Scripts/python -m pytest -n auto -q
```

## 영상 지문·검사·DB 이전

영상 지문은 `v1:파일크기:SHA256`입니다. 앞·중앙·뒤에서 각각 최대 64 KiB를 읽습니다.
동일 내용의 복사본은 하나의 영상과 여러 위치로 저장됩니다. 전체 파일 해시가 아니므로
같은 크기이고 샘플 부분이 같은 파일은 구별하지 못할 수 있습니다(ADR-0002의 절충).
제목은 최초 등록 위치의 확장자를 제외한 파일 이름입니다.
파일 확장자에 제한을 두지 않고 ffprobe가 실제 영상 스트림과 양수 길이를 확인합니다.
GIF·정지 이미지 형식과 단일 프레임, 첨부 그림은 새 영상으로 등록하지 않습니다.
새 영상에는 최소 길이 필터를 적용합니다. 경로·파일 크기·나노초 수정 시각이 그대로인
등록 위치는 미디어 정보와 지문을 다시 읽지 않으며, 비영상 파일도 ffprobe로 다시 읽지 않습니다.
크기나 수정 시각이 달라지면 재판정합니다. 크기와 수정 시각까지 강제로 동일하게 유지한 변경은 감지하지 못합니다.
검사를 마치면 이번 감시 폴더 범위에서 사라진 경로의 비영상·짧은 파일 캐시를 정리합니다.
검사 범위 밖과 접근 오류로 확인하지 못한 폴더의 캐시는 유지합니다.
손상된 영상이나 썸네일 생성 실패는 검사 결과에 알리고 나머지는 계속 등록합니다.
디렉터리 열거 오류도 검사 결과로 알리며 다른 폴더는 계속 검사합니다.
정션·심볼릭 링크 등 재분석 지점은 건너뛰고 이미 검사한 실제 디렉터리는 다시 들어가지 않습니다.

실시간 파일 감시는 제공하지 않으므로 파일을 옮기거나 드라이브를 연결한 뒤 **다시 검사**를 누릅니다.
코어의 `AppCore.scan(folders=[Path(...)])`은 지정한 감시 폴더 또는 그 하위 폴더만 재귀 검사합니다.
`folders`에는 `watched_folders()`가 돌려준 경로 아래 폴더의 `Path` 목록을 넘깁니다. 밖이거나
감시 해제된 경로는 건너뛰고 로그만 남기며, 경로 하나(문자열·`PathLike`)를 그대로 넘기면 `TypeError`입니다.
같은 폴더를 다른 표기(subst 드라이브 등)로 넘겨도 실제 경로로 해석해 범위 안으로 판정합니다.
새 영상 등록·빠른 경로·지문 기준 연결·자동 자막 규칙과 `ScanResult`는 전체 검사와 같습니다.
위치의 파일 없음 처리, 오래된 검사 캐시 정리, 외부 자막 갱신은 지정 범위에만 적용합니다.
감시 폴더 밖(감시 해제된 폴더 포함)과 정션·심볼릭 링크를 거치는 입력은 로그를 남기고 건너뜁니다.
빈 목록이나 유효한 경로가 없는 목록은 빈 결과를 반환하며, 중복·상하위 경로는 한 번만 순회합니다.
이동한 영상은 새 위치에서 기존 지문에 연결하고, 검사 범위 밖의 옛 위치는 다음 해당 폴더 검사나
전체 검사 때 정리합니다. `reconnected` 안내는 검사 시작 때 이미 파일 없음이던 영상에만 적용됩니다.
인자 없는 `scan()`은 감시 폴더 전체와 직접 추가한 위치를 지금처럼 검사합니다.
전체/지정 폴더 검사는 자동 자막 규칙 조회부터 후처리까지 앱 코어의 잠금으로 직렬 실행합니다.
기존 DB는 최초 실행 때 라이브러리 테이블을 v13으로 이전합니다(`PRAGMA user_version = 13`).
영상 ID와 다른 기능 테이블은 그대로 유지하며, 이전 위치는 첫 검사에서 캐시 정보를 채웁니다.
이전 직전에는 원래 버전 DB의 자동 백업을 남깁니다. v3은 가로·세로 및 해상도 확인 상태 열을,
v4는 번역 작업의 용어집과 최근 사용 순서를 저장하는 테이블을 추가합니다.
v5는 원어 자막에 전체 받아쓰기에 쓴 모델 이름을 저장하고 기존 기록은 `large-v3`로 채웁니다.
말소리 없음 결과도 모델을 기록하며 구간 다시 만들기는 기존 모델 기록을 유지합니다.
이전 시점에 원어 자막 테이블이 없으면 자막 모듈이 시작할 때 모델 열을 포함해 만듭니다.
v6은 대기열 항목·순서·숨기기의 키를 `(영상, 작업 종류)`로 바꾸며 기존 항목은 `transcription`으로 옮깁니다.
검수 구간 요청의 항목 ID·순번·앞당기기와 실패 기록을 보존합니다. 번역·다듬기는 받아쓰기 작업의 후속 단계입니다.
`queue_kind`는 대기열 작업 종류이고 `TranslationQueueEntry.kind`(번역·다듬기 단계)와 구별합니다.
웹 행의 `queueKind`와 행 키(`key` = `영상ID:작업 종류`)로 앞당기기·빼기 같은 행 동작이 그 작업 종류에만 적용됩니다.
v8은 화면 자막 영역·세대·줄 테이블(`onscreen_subtitle_regions`, `onscreen_subtitles`, `onscreen_subtitle_lines`)을
만듭니다. 이 버전부터 자막 대기열에 화면 자막 작업(`onscreen_subtitle`, 진행 상태 `reading`)이 들어오므로
이를 모르는 이전 버전이 열지 않도록 버전을 올립니다. 영역은 영상 ID에 속해 위치 이동·복사에도 유지됩니다.
`onscreen_subtitles.py`의 `OnScreenSubtitles`가 영역 저장, 대기열 등록·처리·취소·재시도, 훑기·줄 합치기·저장을 맡고,
영역 이미지는 `RegionFrameReader`(ffmpeg `FFmpegMediaReader.region_frames`), 글자 읽기는 `OcrEngine`
(`WindowsOcrEngine`) 어댑터로 주입합니다. 줄 합치기 기준값(초당 4장, 잡음 2장, 최소 3장, 비슷한 글자 0.9·흔들림 4장 이하, 같은 그림 판정)은
`tests/test_onscreen_subtitles.py`가 고정합니다. 화면 자막 작업자(`onscreen_controls.py`)는 받아쓰기 작업자와 따로 돌아갑니다.
v9는 `translation_glossary`를 작업 ID에서 영상 ID 단위로 옮기고 `onscreen_translation_reviews`에
화면 번역의 사용자 수정 여부를 저장합니다. 기존 용어는 요청 시각·작업 순서·용어 순서로 읽어 먼저 정한 표기를 보존합니다.
용어집은 영상의 어느 출처든 번역 결과나 대기열 행이 남아 있는 동안 공유하며, 모두 사라진 뒤 새 작업을 등록할 때 비웁니다.
화면 번역 결과와 줄별 방식은 v7의 공용 `translation_lines`·`translation_line_providers`에
출처 `onscreen_subtitle`과 화면 자막 줄 ID로 저장하며, 줄 삭제 시 함께 정리합니다.
화면 자막 저장과 후속 번역 등록은 같은 트랜잭션이며, v8에서 이미 읽은 미번역 영상도 시작할 때 등록합니다.
`translation_queue.transcript_id`의 화면 자막 세대 토큰은 영상의 모든 `(region_id, generation_id)`를
영역 ID 순으로 정렬한 JSON입니다. 빈 세대·아직 읽지 않은 영역도 포함하므로 영역 추가·삭제·재생성 때 달라집니다.
무작위 UUID의 최댓값이나 되돌아갈 수 있는 순번 최댓값을 최신 세대로 취급하지 않습니다.
전체 화면 번역 요청은 번역 없는 줄만 대상으로 하며, 영역별 언어를 각 대상의 `language`에 포함합니다.
화면 번역 payload에는 최상위 `spoken_language`를 넣지 않습니다.
참고 문맥은 대상 구간과 겹치거나 앞뒤 `ONSCREEN_CONTEXT_MARGIN = 2.0`초 안에 있는 말소리이며,
대상별 가까운 대사부터 순환 배분하고 중복을 제거해 시각순으로 보냅니다. 문맥 상한은 `max(100, 대상 수)`이며,
`ONSCREEN_CONTEXT_LIMIT = 200`줄을 넘지 않도록 대상 묶음도 최대 200줄로 나눕니다.
저장된 번역이 있으면 함께 보내며 결과에는 넣지 않습니다.
`AppCore.onscreen_translation_skip_reason(video_id)`는 모든 영역의 읽기가 끝났고 줄 합이 0이면
`no_onscreen_text`를 반환합니다. 영구 제외 기록을 남기지 않아 영역을 다시 읽으면 다시 등록됩니다.
`edit_onscreen_translation_line(line_id, text)`는 사용자 수정본을 저장하고 진행 중 응답과 재번역으로부터 보호합니다.
`onscreen_translation_reviewed_lines(video_id)`는 보호된 줄 ID를 반환합니다.
v10은 `onscreen_translation_reviews`에 `original_reviewed`(화면 자막 원문 검수됨) 열을, 화면 자막 구간 요청
`onscreen_subtitle_review_ranges(region_id, generation_id, start, end)`를 더합니다. 보호는 계속 `translation_reviewed=1`만입니다.
`edit_onscreen_subtitle_line(line_id, text, overwrite_reviewed=False)`는 원문을 화면 자막 읽기와 같은 정규화로 고쳐 원문 검수됨으로
남기고 그 줄의 화면 번역만 다시 요청합니다. 직접 고친 화면 번역이 있으면 `ReviewConfirmationRequired`로 확인을 받고,
확인하면 보호를 풀어 다시 번역합니다. 읽지 못한(실패한) 영역이 남아 있으면 화면 번역을 요청할 수 없어 거부합니다.
`request_onscreen_subtitle_range(region_id, start, end)`·`onscreen_subtitle_range_bounds`는 그 영역의 줄 경계까지 넓힌 구간만
다시 읽습니다. 구간 기록은 대기열 항목이 아니라 영역과 그 세대에 붙어 영역을 더하거나 다른 영역을 지워도 남고, 세대가 바뀌거나 그 영역이 지워지면 함께 지워집니다.
대기열 항목을 남길지는 "세대가 없는 영역이나 현재 세대의 구간 요청이 있는가" 한 판정으로 정하고, 사용자가 대기열에서 빼면 그 영상의 구간 요청도 버립니다.
처리 한 번은 세대가 없는 영역 전체와 구간을 함께 읽고(`region_frames(..., start=, end=)`, 시각은 영상 기준), 구간 안의 줄만 새 줄로 바꿔
새 줄만 번역합니다. 그 영상의 화면 자막 읽기가 대기·읽는 중이면 원문 줄 수정과 구간 요청을 막습니다(화면 번역 줄 수정은 코어에서 막지 않고
검수 화면이 함께 막습니다). `onscreen_review_lines(region_id)`는 영역의 검수 줄을, `onscreen_subtitle_region_reviewed_line_count`는
원문·번역을 고친 줄을 한 줄에 한 번 셉니다. 검수 화면은 읽기를 마친 영역이 있을 때만 받아쓰기 자막과 영역(번호·읽을 언어)을 고르게 합니다.
v11은 시리즈 영역 `series_onscreen_regions(id, series_id, x, y, width, height, language, created_at)`과
`onscreen_subtitle_regions.series_region_id`(없으면 직접 정함)를 더합니다. 기존 영역은 모두 직접 정함입니다.
시리즈가 지워지면 시리즈 영역도 지워지고, 시리즈 영역이 지워지면 복사본은 직접 정함으로 남습니다(외래 키). 시리즈 표는
`SeriesStore`가 이전 단계 밖에서 만들지만 외래 키는 쓸 때 검사하므로 최초 생성에서도 v11 단계를 그대로 씁니다.
화(영상)의 영역 출처는 `RegionOrigin`(`direct` 직접 정함 / `series` 시리즈에서 옴) 하나이고 `OnScreenSubtitleRegion.origin`으로
영역마다 드러냅니다. `series`는 그 화가 지금 시리즈 영역의 시리즈에 속할 때만이라, 소속 맞추기 전에 끊긴 화의 영역은 `direct`로
보이고 고치기·지우기가 그 화만 바꿉니다. `onscreen_series.py`의 `OnScreenSeriesRegions`가 시리즈 영역의 적용·고치기·지우기와 소속 맞추기를 맡습니다.
`add_onscreen_subtitle_region(..., series=True)`는 시리즈에서 온 화면 시리즈 영역에 영역 하나를 더하고, 아니면 이 화의 영역 묶음
전체를 시리즈 영역으로 삼습니다(이전 시리즈 영역은 통째로 바뀜). 시리즈에서 온 화와 영역이 없는 화가 같은 영역을 받아 자동 대상으로
들어가고, 지금 화는 직접 요청입니다. `update_onscreen_subtitle_region(..., series=True, mode=...)`는 시리즈 영역을 고쳐 시리즈에서 온
화마다 그 영역의 복사본에 같은 고치기 방식을 적용하고(`RegionEdit.MOVE`는 사각형만, `REREAD`는 다시 읽어 예전 줄과 맞추기,
`REBUILD`는 다시 만들기), 사라질 검수 수(`onscreen_subtitle_region_series_impact(..., mode=...)`)는 고친 영역에서는 `REBUILD`일
때만 셉니다. `delete_onscreen_subtitle_region`은 시리즈에서 온 영역이면 시리즈에서 온 모든 화에서 지웁니다. `series=False`로
고치거나 더하면 그 화만 직접 정함이 됩니다. 여러 화의 영역·줄은 한 트랜잭션에서 바꿉니다. 제외 영상은 시리즈 영역 변경에서
빠집니다(채우거나 바꾸지 않고, 대기열에 넣지 않고, 범위에 세지 않음). 시리즈에서 온 제외 영상은 시리즈 영역을 바꾸는 순간 영역·줄·검수를
지킨 채 직접 정함이 됩니다.
`onscreen_subtitle_region_series_impact(video_id, region_id=None, delete=False)`는 확인 창의 범위
`OnScreenSeriesImpact(other_videos, reviewed_line_count, replaces_existing, change)`를 돌려주고(`change`는 `add`·`update`·
`delete`·`replace`이며 확인 창 문구가 씁니다), `expected_series_impact`가 바꾸는 순간의 범위나 변경 종류와 다르면
`OnScreenSeriesChanged`(`OnScreenRegionChanged`의 하위)로 아무것도 바꾸지 않습니다. 이 대조와 단일 화 고치기·지우기의 검수 수 대조는
진행 중 읽기를 멈추기 전에 먼저 하므로, 어긋나면 읽던 결과도 버리지 않습니다. 스캔·파일 추가·다시 연결·
시리즈 만들기·편집·자동 묶기 뒤에는 소속을 견줘, 그 동작으로 새로 들어온 화 가운데 영역이 없는 화만 시리즈 영역을 받고,
지금 그 시리즈에 속하지 않는 화의 시리즈에서 온 영역은 직접 정함이 됩니다. 이 맞추기는 상태만 보므로 몇 번 불러도 결과가 같습니다.
화면 자막 대기열 요청의 자동 대상은 그 영상의 지금 순번(직접 요청 포함)을 그대로 둡니다.
새 등록과 파일 변경 검사 때 ffprobe의 첫 일반 영상 스트림 크기를 저장하며 display matrix와
구형 rotate 태그의 90/270도 회전을 반영합니다. 해상도 미확인 기존 영상은 유휴 시간에
한 번에 한 개씩 약 1초 간격으로 읽습니다. 재생·받아쓰기·검사가 시작되면 채우기를 취소하고,
종료·재시작 후 미처리 항목부터 이어갑니다. 파일 없음·실패 항목은 알 수 없음으로 남기며
**다시 검사** 또는 파일 다시 연결로 재시도합니다. 실패한 항목을 시작할 때마다 반복하지 않습니다.
통계의 라이브러리 구성은 짧은 변 기준 SD(<720), 720p, 1080p, 1440p, 4K 이상(≥2160),
알 수 없음 분포를 표시합니다. 각 구간의 최소값을 넘으면 해당 구간에 포함합니다.
검수 기록과 구간 요청은 별도 테이블을 쓰며 기존 테이블 구조·DB 버전은 바꾸지 않습니다.
v12는 검수 전 원어 자막 원문 `transcript_line_originals`를 더합니다(분석용, 화면에 보이지 않음). 받아쓰기가 만든 줄이 처음
바뀌기 직전의 글자·시작·끝 시각을 줄마다 한 번만 남기고, 그 줄을 만든 받아쓰기 모델과 원어를 함께 적습니다. 구간 다시 만들기가
만든 줄의 모델은 `transcript_line_models`에 따로 둡니다(원어 자막의 모델 기록은 전체 받아쓰기의 모델 그대로). v12 이전에 만든 원어
자막은 `transcripts.line_models_tracked = 0`이며, 그 줄은 그 전 구간 다시 만들기의 모델을 알 수 없어 원어 자막의 모델로 적고
`model_inferred`로 표시합니다. 검수로 원어 줄을
처음 고칠 때와 구간 다시 만들기가 줄을 지울 때 남기며, 지워진 줄에는 지운 시각과 까닭(`range`)을 적습니다. 전체 다시 생성은
이미 남긴 기록에만 까닭 `whole`을 적고 고치지 않은 줄을 옮겨 적지 않습니다. 줄·원어 자막이 지워져도 기록이 남도록 둘을 외래 키로
걸지 않으며, DB 파일에 있으므로 백업과 복원에 들어갑니다. 이전 전 라이브러리에는 기록이 없습니다. `transcript_line_originals(video_id)`가
`OriginalTranscriptLine` 목록을 돌려줍니다.
v13은 화면 자막 구간 요청 `onscreen_subtitle_review_ranges`에 `whole` 열을 더합니다. 영역 고치기의 다시 읽기는 영역마다
하나인 이 자리에 `whole = 1`로 영상 전체 요청을 남겨 그 영역의 구간 요청을 대신하고, 처리는 영상 전체를 읽은 뒤 새 줄을 예전 줄과
맞춥니다(`_merge_reread`). 이전 전 구간 요청은 `whole = 0`입니다.

## 중복 실행 방지

데이터 폴더별 `QLockFile`과 `QLocalServer`를 사용하며, 서로 다른 `--data-dir`은 독립 실행됩니다.
