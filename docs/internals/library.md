# 라이브러리·추천·통계·검색

## 라이브러리 설정

최소 길이는 공용 `Settings` 저장소의 `library.min_duration_seconds` 키에 저장합니다.

## 키 배치

코어의 `key_bindings()`는 명령·한국어 이름·현재 키·기본 키를 반환하고,
`save_key_bindings()`는 명령별 키 목록 전체를 검사해 저장합니다.
`reset_key_bindings(command)` 또는 인자 없는 호출로 개별·전체 복원을 합니다.
`set_key_bindings()`는 기존 키 배치 교체 API이며 이제 변경을 저장합니다.
생성자의 `key_bindings` 주입은 해당 인스턴스에만 적용됩니다.
저장에는 공용 `Settings`의 `keys.bindings`를 사용하고 기본값과 다른 명령만 기록합니다.
후속 기능의 새 기본 키가 기존 사용자 키와 겹치면 사용자 설정을 유지하고 새 명령은 미할당으로 표시합니다.

## 추천

공용 `core`의 다섯 기간은 `recommend.continue_watching_days`(이어 보기, 기본 30),
`recommend.revisit_days`(하이라이트 복습, 기본 30), `recommend.new_arrivals_days`(새로 추가됨, 기본 14),
`recommend.rewatch_days`(다시 보기, 기본 60), `recommend.unwatched_days`(잊고 있던 영상, 기본 30)입니다.

`core.recommendation_period_definitions()`는 설정 화면이 그릴 이름·설명·기본값·허용 범위를,
`core.recommendation_period_days()`는 다섯 기간의 현재 값을, `core.recommendation_period(criterion)`은 기간 하나의 현재 값을 돌려줍니다.
`core.set_recommendation_period_days(criterion, days)`는 검증한 값만 저장하며,
`core.reset_recommendation_period_days(criterion)`는 저장값을 지워 기본값으로 되돌립니다.
잘못된 값(음수, 무한, 상한 초과, 수가 아닌 값, 불리언)은 예외로 거부하고 저장하지 않으며,
저장한 값은 다음 추천 계산부터 바로 반영됩니다.
기존 `unwatched_days`·`revisit_days` 저장값은 계속 사용합니다. 보다 만 영상의 잊고 있던 영상 전환은
`continue_watching_days`를 따르므로 두 기간을 따로 바꾸어도 이어 보기와 겹치거나 사이에 빠지지 않습니다.
값은 0 이상 365000 이하의 유한한 일수이며 소수도 허용합니다.

이전 버전은 하이라이트 생성 시각을 저장하지 않았으므로 기존 하이라이트는 최초 업그레이드 시각부터
기간을 계산합니다. 이후 생성 시각은 별도 테이블에 저장하고, 시각·메모 편집은 생성 시각을 바꾸지 않습니다.
하이라이트를 삭제하면 그 생성·복습 시각도 제거합니다. 기존 테이블 구조와 DB 버전은 바꾸지 않습니다.

공개 코어 API: `recommendations()`는 추천 줄 목록(`RecommendationRow`: 고유 key·종류·제목·영상과 이유·겹친 태그)을 반환하며,
`dismiss_video(video_id)`, `dismissed_videos()`, `restore_dismissed_video(video_id)`로 관심 없음을 관리합니다.
`recommendation_period_definitions()`, `recommendation_period_days()`, `recommendation_period(criterion)`, `set_recommendation_period_days(criterion, days)`,
`reset_recommendation_period_days(criterion)`로 다섯 추천 기간을 읽고 검증해 저장하고 기본값으로 되돌립니다.
`viewing_status_map()`과 `video_tags_map()`은 제외·시청 없음·태그 없음까지 포함한 영상 ID별 전체 상태를
일괄 조회합니다. `library_snapshot()`은 영상·시청 상태와 기록·태그·시리즈를 한 번씩 조회한 결과를 반환하고,
목록과 `recommendations(snapshot=...)`가 같은 결과를 공유할 수 있습니다. 태그 필터는 목록에만 적용하고 추천은 전체 영상을 기준으로 합니다.
썸네일 아이콘은 경로와 파일 수정 시각으로 캐시하여 반복 갱신 비용을 줄이며 파일이 바뀌면 다시 읽습니다.

## 시청 통계

`AppCore.viewing_statistics(days, *, tz=None)`는 오늘을 포함한 최근 7·30·90·365일의
`ViewingStatistics`를 반환합니다. 기본은 시스템 로컬 시간대이며, 테스트에서는 `tz`에
`datetime.tzinfo`를 주입합니다. 시청을 시작한 날짜에 실제 재생 구간의 합집합을 세며,
틀어보기·모아보기 복습은 빼고 저장 전 진행 중인 시청도 포함합니다.
일별 시간·횟수(빈 날은 0), 이전 같은 기간 대비 증감, 최장 연속 일수, 상위 영상 5개와
전체 기간의 라이브러리 현황을 제공합니다. 이전 값이 0이면 증감률은 `None`이며 화면에서는
"이전 기록 없음"으로 표시합니다. 상위 영상은 시청 시간·횟수 내림차순, 제목 오름차순이고
제외·파일 없음 상태를 함께 반환합니다. 라이브러리 현황과 새 영상 수는 제외 영상만 뺍니다.

`AppCore.video_viewing_statistics()`는 영상 ID별 `VideoViewingStatistics`를 일괄 조회합니다.
시청 횟수·시간은 전체 기간이고, 마지막 시청은 틀어보기를 포함한 `updated_at` 최댓값입니다.
제외·파일 없음·시청 없는 영상도 반환하며, 영상 수와 무관하게 SELECT 2회로 조회합니다.
`library_snapshot().video_statistics`에도 같은 ID별 수치가 들어 있습니다. 스냅샷은
시청 상태와 수치를 한 번의 시청 조회·순회로 함께 계산하므로 카드에서 별도 API를 다시 부를 필요가 없습니다.
저장 시 이미 병합한 구간은 그대로 합산하고, 행과 진행 중 시청을 확보한 뒤 읽기 트랜잭션을
닫고 파싱합니다. 기간 통계는 SELECT 5회이며 필요한 날짜의 로컬 자정 경계를 한 번 만들고
시작 시각을 `bisect`로 찾습니다. 범위에서 이틀 이상 먼 ISO 날짜는 시간대 변환 없이 건너뜁니다.
반환 dataclass의 시간 단위는 초, 날짜·시각은 ISO 문자열이며
`dataclasses.asdict()` 후 JSON으로 직렬화할 수 있습니다. 순수 계산은 `statistics.py`의
`viewing_statistics(viewings, videos, days, today, tz, settings)`와
`video_viewing_statistics(viewings, video_ids, settings)`에 있습니다.

### 통계 화면

`AppCore.statistics_dashboard(days, *, tz=None)`가 기존 `ViewingStatistics`와
요일/시간대 배열, `LibraryInventory`를 한 읽기 스냅샷에서 반환합니다.
영상 수와 무관하게 SELECT 8회이며 시청 기록은 한 번만 순회합니다.
`web_statistics_page.py`는 활성화/시청 종료 때 100ms 뒤 작업자에서 계산하고,
연속 요청을 합치며 오래된 응답을 폐기합니다. 비활성화 시 시작 전 계산은 취소합니다.
`web_statistics_contract.py`의 `STATISTICS`에 dataclass를 등록하며 생성기는 가변 길이 tuple을
TypeScript 배열, 고정 길이 tuple을 TypeScript tuple로 확장합니다. 기존 TypedDict 출력은 유지합니다.
차트는 shadcn Chart 합성 구조와 정확히 고정한 `recharts@3.10.1`을 쓰며 색은 기존 토큰을 사용합니다.

## 검색 색인

미정규화 줄이 1만 개 이상이면 정규화 후 FTS5 `rebuild`를 한 번 실행하며,
소량 변경은 행별로 갱신합니다. 원문은 저장 트리거로 반영하고 정규화 값은 색인 준비 또는 검색 직전에
앱 코어가 채웁니다. `prepare_search()`와 `search_index_ready`로 준비와 상태를 조회할 수 있고,
화면 없이 `search()`를 직접 호출해도 필요한 준비를 수행합니다. 트리거는 SQLite 내장 기능만 사용하므로
앱 전용 함수를 등록하지 않은 구 빌드나 외부 도구에서도 저장·수정·삭제할 수 있습니다.
줄 수정·구간 교체(#9)를 포함한 모든 쓰기 경로에 트리거가 적용되므로 별도 색인 갱신 호출이 필요 없습니다.
장면 시각은 색인에 복사하지 않고 검색할 때 원어 자막 줄에서 읽으므로 번역 결과도 최신 시각을 표시합니다.
제목·파일 이름·태그·메모는 검색할 때 현재 값을 읽습니다.
`AppCore.search(query)`는 `SearchResponse(results, truncated)`를 반환하며,
각 결과는 원어(`transcript`)와 번역(`translation`) 출처, 일치한 원문, 장면 시각과 파일 없음 상태를 포함합니다.

## 외부 자막

인코딩 판정은 **BOM(UTF-8, UTF-16 LE/BE) → NUL 패턴으로 판별한 BOM 없는 UTF-16 →
UTF-8 → CP949 → EUC-KR** 순서이며, 엄격한 디코딩을 사용합니다. EUC-KR의 일반적인
문자는 CP949에도 포함되므로 이 경우 기록되는 인코딩 이름은 `cp949`입니다.
파일 끝 NUL은 인코딩 판별에서 제외하고, UTF-16 BOM 파일 끝에 추가된 홀수 NUL 바이트는 제거합니다.
확장자가 `.smi`여도 SYNC 태그가 없고 내용이 SRT이면 읽으며, ASS이면 지원하지 않는 형식임을 경고합니다.
SRT·VTT의 큐 설정과 태그는 검색 글자에서 빼고, SMI의 빈 싱크는 앞 큐의 끝 시각으로 씁니다.
SMI 싱크는 원래 시각순으로 안정 정렬하며 같은 시각끼리는 파일 순서를 유지한 뒤, 음수 시작 시각은 0초로 보정합니다.
SMI 마지막 큐의 끝은 영상 길이이며, 길이를 모르면 시작+5초를 씁니다.
다음 싱크는 같은 언어 클래스 기준이고, P 없이 쓴 대사는 기존 모든 클래스를 닫고 기본 클래스(`""`)로 읽습니다.
P도 대사도 없는 빈 싱크는 모든 클래스를 닫으며, 빈 P는 해당 클래스만 닫습니다.
잘못된 블록은 건너뛰고 개수를 경고에 남기며, 읽힌 줄이 하나도 없을 때 파일 실패로 처리합니다.

`AppCore.external_subtitles(video_id)`는 파일 경로·인코딩·경고와 언어별 자막 줄을 반환합니다.
경고가 없고 파일 크기·수정 시각이 같으면 다시 읽지 않으며, 경고가 있는 파일은 다음 검사에서 재시도합니다.
앱 업데이트로 자막 읽기 규칙이 바뀌면 다음 검사에서 외부 자막을 한 번 다시 읽습니다.
전체 검사에서 접근 가능한 범위를 갱신하고, 연결이 끊긴 드라이브는 다시 연결된 뒤 그 폴더만 다시 읽습니다.
접근하지 못한 영상·자막 경로도 따로 남겨 복구 후 다시 읽으며, 정상 파일은 반복해서 읽지 않습니다.
부분 검사만 했거나 전체 검사를 중단했으면 다음 전체 검사에서 갱신을 마칩니다.
바뀐 파일의 읽기 실패는 이전 검색 줄을 제거하고 경고로 남깁니다. 자막 파일 삭제도 검색에 반영합니다.
일부 블록만 실패한 파일은 읽힌 줄과 경고를 함께 보관하고, 서명이 같아도 다시 읽습니다.
파일별 저장·삭제를 커밋하므로 검사 중단 뒤 다음 검사에서 나머지 파일을 이어서 맞춥니다.
검색 결과의 출처는 `external`(외부 자막)이고 `video_id`, `start`, 선택적 `language`를 제공합니다.
원어·번역 자막, 검수·번역 대기열에는 영향을 주지 않습니다. 기존 DB 버전도 유지합니다.

상세 조회는 `external_subtitle_summaries(video_id)`로 자막 본문 없이 집계만 가져옵니다.
