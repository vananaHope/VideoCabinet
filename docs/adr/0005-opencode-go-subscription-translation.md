# 구독 번역에 OpenCode Go API와 실패 시 이어받기를 추가한다

ADR-0003의 기조를 **사용자가 이미 낸 구독으로 번역한다**로 보완한다.
Codex·Claude는 기존 구독 CLI를 사용하고, OpenCode Go는 사용자가 등록한 구독 키로 API를 호출하는 예외로 둔다.
이 결정은 #63의 2026-10-15 사용자 결정이며, 기본 번역 주체는 기존 Codex를 유지한다.

## 이용 조건 위험과 사용자 결정

[Go 문서](https://opencode.ai/docs/en/go/)는 코딩 에이전트와 유사한 트래픽을 요구하고 남용 감시를 명시한다.
[이용 약관](https://opencode.ai/legal/terms-of-service)의 사용 제한에는 서비스가 합리적으로 의도하지 않은 목적과
프로그램을 통한 출력 추출에 대한 문구도 있다. 자막 번역에 대한 명시적 허용은 확인하지 못했다.
2026-10-15 사용자는 이 위험과 계정 제한 가능성을 알고 감수하기로 결정했다.
이는 제공자의 허용 확인을 뜻하지 않으며, 코딩 에이전트로 위장하지 않고 `my-video-manager/<실제 앱 버전>` User-Agent를 보낸다.
설치 메타데이터를 읽지 못하면 버전은 `0.1.0`으로 대체한다.
번역 작업마다 고정 ID를 `x-opencode-session`에 전달한다. 같은 작업의 묶음·재시도는 같은 ID를 쓰며 키 확인은 매번 별도 ID를 쓴다.
모델 목록 등 모델 요청이 아닌 통신에는 세션 헤더를 붙이지 않는다.

## 모델과 응답 계약

- 기준 주소는 `https://opencode.ai/inference/go/v1`이고 `chat/completions`만 호출한다. 확인된 다른 API 계열 모델은 거절한다.
  목록 외 직접 입력 모델도 받되 정책 미확인으로 표시하며, 실제 호환성은 호출 결과로 확인한다. 예전 `/zen/go/v1`로 폴백하지 않는다.
- 기본 모델은 사용자 지정 **`deepseek-v4.1-flash`**이다. 품질 시험으로 선정하지 않는다.
  Go 문서의 2026-10-15 정책은 학습 미사용·보존 0일이며, DeepSeek 무보존 계약은 매월 갱신되고 현재 2026-10-31까지다.
  기본 모델에도 다른 모델과 동일한 정책 표시/경고 규칙을 적용한다. 학습 사용·미확인·계약 만료는 경고 대상으로 반환한다.
  모델 ID, 학습 여부, 보존 기간, 확인일, 만료일, 출처를 데이터로 두고 후속 화면이 사용한다. 자동 정책 갱신은 없다.
- [Inference API 문서](https://opencode.ai/v2/docs/console/api/inference)의 `Authorization: Bearer <token>`을 사용한다.
  실제 Go 키를 이용한 인증 검증은 아직 하지 않았다.
- [참고 구현의 실측 기록](https://github.com/ucx0204/CarrotMangaTranslator/blob/721e709d3706f15ed1ef62270460d4b8ab5d5312/docs/custom-api-profiles-20261005.md)과
  2026-10-15 사용자 결정에 따라 기본 모델은 정책 데이터의 `structured_output="json_object"`로 지정한다.
  번역과 키 확인에 `response_format: {"type": "json_object"}`를 보내고 프롬프트에 소문자 `json` 안내와 예시를 포함한다.
  `json_schema`는 보내지 않는다. 참고 프로젝트의 코드는 복사하지 않고 확인된 동작 사실만 사용했다.
  `translation_prompt`와 `translation_schema`는 프롬프트에 포함하고, 응답 바깥 코드 펜스 한 겹만 벗긴 뒤
  `parse_translation_response`로 줄 ID 일대일 대응과 형식을 검증한다. 앞뒤 설명이나 중첩 펜스는 형식 오류다.
  400은 요청 거부로 반환하고 JSON 안내 누락/스키마 거부는 정제된 진단만 남긴다. 무조건 재시도하거나 모델·주소를 바꾸지 않는다.
- 어댑터는 전달받은 남은 줄 묶음만 번역하고 자체 재시도를 하지 않는다. 형식 오류는 현재의 `format`, 한도는 `usage_limit`으로 반환한다.
  키 없음·인증 오류·연결 실패·저장소 오류는 구분하고 서버 원문/원래 예외를 오류 문구에 포함하지 않는다.
  `Retry-After`의 초/HTTP 날짜와 오류 객체의 시간대가 있는 `retry_at`/`reset_at`을 UTC 시각으로 제공한다.
  알 수 없는 단위나 자연어 시각은 추측하지 않는다. 현재 큐는 이 시각을 읽지 않으므로 후속 연결에서 적용해야 한다.
- 모델 목록 조회는 표시용이다. 공개 목록 조회 성공을 키 유효성으로 간주하지 않는다.
  `check_key()`는 사용자가 명시적으로 요청할 때만 기본 유료 모델에 고정 문자열과 `max_tokens=1`을 보낸다.
  유효·키 없음·키 오류·한도·연결 실패·기타 결과를 구분하며 자동/주기적으로 호출하지 않는다.

중립 모듈 `translation_models.py`에 `ModelPolicy`와
`TranslationModelChoice(provider, model_id, label, is_default, policy, source,
reasoning_efforts, structured_output)`를 둔다. CLI와 Go 어댑터가 순환 import 없이 공유할 수 있다.
`reasoning_efforts: tuple[str, ...] | None`의 `None`은 미확인, `()`은 미지원, 값이 있으면 선택 가능한 강도 목록이다.
`reasoning_supported`는 이 목록에서 파생한다. '기본' 선택은 추론 강도 인자를 넘기지 않는다.
`policy=None`인 CLI 직접 입력 항목에는 Go 개인정보 경고를 적용하지 않는다. Go 직접 입력은 값이 미확인인 `ModelPolicy`를 붙여 경고한다.
개인정보 정책 출처와 모델 선택/구조화 출력 근거의 출처를 각각 보존한다. 실제 Codex·Claude 선택지와 공용 목록 통합은 연결 단계에서 한다.

## 키 저장

키는 데이터 폴더의 `secrets/opencode-go.dpapi`에 Windows 사용자 범위 DPAPI 암호문으로 저장한다.
`CryptProtectData`/`CryptUnprotectData`를 ctypes로 호출하며 머신 공용 플래그는 사용하지 않는다.
설정과 DB에는 키를 넣지 않고, 암호화 후 임시 파일과 원자적 교체를 사용해 저장 실패 시 기존 키를 보존한다.
저장/읽기/삭제와 끝 4자리 가린 표시를 제공하며 짧은 키는 전부 가린다. 키 객체의 str/repr과 오류는 평문을 숨긴다.
붙여넣기의 앞뒤 공백·줄바꿈은 없애고 키 내부는 ASCII 33~126만 허용한다. 입력 오류와 암호화/파일 저장 오류는 다른 문구로 안내한다.
이는 저장 데이터 보호이며 같은 Windows 계정의 프로세스나 실행 중 메모리까지 격리하는 수단은 아니다.
다른 사용자/컴퓨터로 옮기거나 DPAPI 복호화가 불가능해지면 다시 등록한다. 평문 저장으로 폴백하지 않는다.

## 이어받기 정책과 단계

번역 주체가 OpenCode Go이면 처음부터 끝까지 해당 방식으로 처리한다. Codex·Claude가 사용량 한도 보류,
CLI 오류 또는 형식 오류 재시도 소진 등으로 멈추면 **남은 줄**을 OpenCode Go가 이어받는다.
키가 등록돼 있고 **실패하면 OpenCode Go로 이어서** 설정이 켜져 있을 때만 허용하며, 키가 있으면 기본으로 켠다.
직접 취소는 이어받지 않는다. 줄마다 실제 번역 방식을 기록하고, 이어받은 OpenCode Go도 한도에 걸리면 보류한다.

현재 코어 단계는 독립 어댑터·키 저장소·정책 데이터와 이 결정을 제공한다.
선택지/설정 확장, 대기열 실행과 서버 재시도 시각 연결, 이어받기 상태 전이·줄별 방식 기록, 설정/대화상자와
자막 외부 전송 안내는 #51·#53 병합 뒤 연결 단계에서 구현한다. `translation_cli.py`, `translation.py`, `translation_controls.py`는 수정하지 않는다.
HTTP는 주입 가능하며 자동 테스트는 로컬 가짜 서버만 사용한다. 실제 키로 짧은 자막 확인은 후속 사람 확인으로 남긴다.
HTTP transport는 취소 Event를 받으며 취소/전체 제한 시간 도달 시 소켓을 shutdown/close한다.
호출자는 20ms 간격으로 취소를 감시하고 작업 스레드 정리 대기는 최대 100ms다.
#122에서 비스트리밍 번역·다듬기의 긴 추론을 허용하도록 번역 요청의 전체 제한과 응답 읽기를
공통 `TRANSLATION_TIMEOUT` 상수의 600초로 늘렸다. TCP 연결/TLS handshake는 10초를 유지하고,
키 확인·모델 목록 조회는 `CHECK_TIMEOUT` 상수의 30초 이내로 제한한다(더 짧은 주입값은 유지한다).
TCP/TLS 연결 수립 전 시간 초과는 `connection`으로 남기고, 연결 뒤 응답 시간 초과는 CLI의 `timeout`과 다른
`response_timeout`으로 분류하여 기존 묶음 축소·재시도 흐름을 사용한다.
전송 작업자는 원래 예외 대신 종류 문자열만 전달하며, 정제된 `OpenCodeGoError`는 다시 감싸지 않아 실패당 경고를 한 번만 기록한다.
Windows의 읽기 대기를 확실히 중단하도록 응답 reader는 50ms 단위로 취소를 확인하며, 이 짧은 timeout은 HTTP 파서에 전달하지 않는다.
DNS 해석 자체는 OS가 소유하므로 즉시 중단할 수 없으나 호출자는 취소 즉시 반환하며 늦게 만들어진 소켓도 전송 전에 닫는다.
실제 키 사람 확인에서는 기준 주소/Bearer 인증, JSON 모드 지원·응답 펜스 여부, `max_tokens=1`, 짧은 자막 결과를 확인한다.
