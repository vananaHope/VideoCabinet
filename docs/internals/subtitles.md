# 자막

## 자막 기능 준비

작업자 스레드에서
`AppCore.prepare_subtitle_support(cancellation=Event(), progress=callback)`을 호출하면
CUDA와 Whisper large-v3-turbo를 같은 흐름에서 준비합니다.
독립 어댑터 `SubtitlePreparation(data_directory, adapter=RuntimeDownloadAdapter(), gpu_available=...)`도
사용할 수 있으며 `prepare()`가 CUDA 디렉터리들과 모델 경로를 반환합니다.
콜백은 `PreparationProgress(phase, asset, completed, total)`을 받습니다.
download/verify/extract는 파일별 바이트, reuse/ready는 완료 개수, probe는 GPU 확인입니다.
추가 필드 `file_index`, `file_count`, `overall_completed`, `overall_total`은 전체 파일 순서와
누적 바이트 진행률입니다. `AppCore.subtitle_support_status()`는 이전 결과와 완료 manifest만 읽습니다.
취소 토큰은 청크마다 검사하며 네트워크 무응답 제한 시간은 10초입니다.
**진행률 콜백은 예외를 던지지 않아야 합니다.** 화면 갱신 실패 등 콜백 내부의 오류는 호출자가 처리합니다.

`PreparationError.kind`는 `gpu_unavailable`, `network`, `hash_mismatch`, `disk_full`,
`cancelled`, `invalid_archive`, `storage`, `preparation_required`를 구별하고 한국어 안내와 별도 `detail`을 제공합니다.
NVIDIA 드라이버는 사용자가 설치해야 합니다.
다운로드·해시 검증·추출과 공간 검사는 어댑터에서 주입할 수 있습니다.
GPU 감지는 최대 15초의 별도 Python 자식(`transcription --probe-cuda`)에서 실행하므로 앱 프로세스에
`ctranslate2`를 올리지 않습니다. 설치판은 같은 실행 파일의 `transcription --probe-cuda`를 사용합니다.
frozen 받아쓰기 자식은 `prepared()`로 완료 결과만 읽고, 없으면 `preparation_required`로 바로 실패합니다.
준비 다운로드는 명시적인 `prepare_subtitle_support()` 흐름에서만 실행합니다.

CUDA 버전은 기존 `cuda` extra와 같고 Windows x64 공식 PyPI 휠 URL·SHA-256은
`runtime_assets.py`에 고정했습니다. Whisper 저장소는
`mobiuslabsgmbh/faster-whisper-large-v3-turbo`, revision은
`0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`이며 같은 파일의 크기와 SHA-256으로 검증합니다.
`config.json`의 `alignment_heads`를 단어 시각에 사용합니다. 소스 실행도 같은 revision을
`download_model(TRANSCRIPTION_MODEL, cache_dir=..., revision=WHISPER_REVISION)`으로 받습니다.
어댑터가 반환하는 모델 이름은 `large-v3-turbo`입니다. 엔진과 CUDA 버전은 바꾸지 않습니다.
CUDA는 `data_directory/runtime/cuda/<wheel-sha256>/`에 DLL만,
모델은 기존 `data_directory/models/` 아래 `large-v3-turbo/<revision>/`에 둡니다.
소스 실행의 `models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots/<revision>/`가 있으면
고정 파일 전체의 크기와 SHA-256을 한 번 확인해 `ready.json`을 만들고 그 경로를 그대로 재사용합니다.
맞지 않는 HF 캐시는 보존하고 앱 전용 폴더에 다시 받습니다.
반쯤 받은 `.part`와 추출 중 `.partial` 폴더는 다음 시도에서 지웁니다.
HF 캐시를 재사용할 때도 현재 revision의 앱 전용 `.partial`은 먼저 정리합니다.
CUDA 완료본은 그대로 재사용하므로 기존 설치판은 turbo 모델만 내려받습니다.
turbo 그룹의 검증·게시가 성공한 뒤(검증한 HF 캐시에 `ready.json`을 쓴 경우 포함)에만
`SubtitlePreparation.cleanup_previous_models()`가 `models/large-v3/` 전체와
`models/large-v3*.partial`을 정리합니다. turbo 이름의 폴더·단계 폴더는 제외하며,
`models/` 바로 아래의 실제 디렉터리인지 확인하고 정션·심볼릭 링크를 따라가지 않습니다.
`models/` 폴더 자체가 링크면 자동 정리하지 않고 건너뛴 이유를 로그에 남깁니다.
준비가 실패하거나 취소되면 이전 모델은 남습니다. 삭제 실패는 로그에만 남기고 준비는 성공합니다.
다음 준비에서 다시 정리하고, 설치판 앱 시작 시 이미 준비됐다면 `start_cleanup_if_ready()`가
뒤 작업으로 한 번 재시도합니다. `status()`·`prepared()`와 받아쓰기 자식은 삭제하지 않습니다.
정리 뒤 구버전으로 돌아가면 large-v3를 다시 준비해야 합니다. 기존 자막·모델 기록은 그대로 남습니다.
CUDA 런타임과 `models/models--*` 형태의 Hugging Face 캐시 및 다른 모델은 자동 삭제하지 않습니다.
현재 해시·revision과 다운로드 용량(합계 약 2.9 GB)은 `runtime_assets.py`의 자산 목록이 원본입니다.
완료 표시와 파일 크기가 맞으면 다시 받지 않으며, 같은 데이터 폴더의 준비 작업은 프로세스 사이에서도 직렬화합니다.
소스 받아쓰기는 기존 `.venv` CUDA와 Hugging Face 모델 캐시를 계속 사용합니다.

공식 CUDA 휠 실측(2026-10-15): cuBLAS 567,544,208바이트 / DLL 788,719,104바이트,
cuDNN 684,630,375바이트 / DLL 1,007,375,176바이트입니다.
모델 파일과 다운로드·추출 중 임시 공간은 별도로 필요합니다.

준비 배너의 **파일 n/m · 전체 약 X GB**와 전체 진행률은 `runtime_assets.py`의 고정 크기에서 계산합니다.

## 받아쓰기

Windows Job 객체가 받아쓰기 자식·손자 프로세스를 묶으므로 앱 강제 종료 때도 함께 종료됩니다.

원어를 직접 지정하지 않았고 자막 줄이 없거나 감지 확률이 50% 미만이면 원어를 알 수 없음으로 저장합니다.
이때 코어의 `Transcript.spoken_language`는 `None`이고 `translation_eligible`은 `False`이므로
후속 번역 기능에서도 알 수 없는 원어를 번역 대상으로 취급하지 않습니다.

Windows GPU 검증 조합은 **faster-whisper 1.2.1, CTranslate2 4.8.3,
CUDA 12.8 cuBLAS 12.8.4.1, cuDNN 9.8.0.87**입니다.
`setup.ps1`은 NVIDIA 공식 Windows wheel을 **이 저장소의 `.venv`에만** 설치하며,
시스템 CUDA Toolkit이나 PyTorch 설치는 필요하지 않습니다. 앱이 해당 DLL 경로를 프로세스 안에 등록합니다.
RTX 5070(Blackwell)에서 NVIDIA 드라이버 **610.47**, Python **3.10.6**으로
`large-v3` FP16 실제 음성 받아쓰기를 확인했습니다. 드라이버는 스크립트가 변경하지 않습니다.
Blackwell에는 CUDA 12.8 이상이 필요하므로 오래된 cuBLAS/cuDNN을 섞지 마세요.
근거: [faster-whisper GPU 요구사항](https://github.com/SYSTRAN/faster-whisper#gpu),
[CTranslate2 Windows 빌드](https://github.com/OpenNMT/CTranslate2/blob/v4.8.3/python/tools/prepare_build_environment_windows.sh),
[NVIDIA cuDNN 지원표](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.8.0/reference/support-matrix.html).

## 자막 대기열

받아쓰기 진행률은 하위 프로세스가 임시 진행 파일로 보고하는 처리 오디오 시간 / 영상 길이입니다.
보고는 파일을 원자적으로 교체하며, 보고 파일 쓰기·교체 오류는 받아쓰기 결과에 영향을 주지 않습니다.
시작 시 남아 있던 `transcribing`·`reading`·`translating`은 `queued`로 복구합니다.

## 자막 줄 저장

원어 자막은 DB에 시작·끝 시각과 텍스트, 줄별 UUID로 저장합니다.
줄 ID는 다시 읽기·앱 재시작에도 유지되며, 전체 재생성에서는 새 세대와 새 줄 ID로 교체합니다.
향후 번역·검수는 이 ID를 참조할 수 있습니다. mpv 전달용 `.srt` 캐시는 데이터 폴더의
`playback-subtitles/`에만 만들고 영상 옆에는 쓰지 않습니다. 이 캐시는 삭제해도 다시 만들어집니다.

## 번역

모델과 강도는 `translation.model.<방식>`, `translation.effort.<방식>`에 각각 저장합니다.
번역 묶음 기본값은 `translation_models.py`의 방식별 정책에 있으며, 테스트는 `AppCore(translation_batch_size=...)`로 크기를 지정할 수 있습니다.

`AppCore.request_translation(video_id, line_ids=[...])`로 지정한 원어 줄만 다시 번역할 수도 있습니다.

### 번역 CLI 호출

`codex exec`는 비대화식 읽기 전용 sandbox와 승인 금지로 실행합니다. `--ignore-user-config`로
사용자 `config.toml`, `--ignore-rules`로 사용자·프로젝트 실행 규칙을 제외하고, `--disable hooks`로
사용자·프로젝트 훅을 끕니다. `-c project_doc_max_bytes=0`으로 작업 경로의 프로젝트 AGENTS도 제외합니다.
다만 **전역 `$CODEX_HOME/AGENTS.md` 또는 `AGENTS.override.md`가 있으면 그 지시는 번역 호출에도
적용**됩니다(Codex 0.162.1 기준). `hooks.json`의 사용자 정의 세션·도구 훅은 번역 호출에서 비활성화합니다.
인증은 기존 `CODEX_HOME`을 그대로 사용합니다. 빈 임시 홈은 기존 로그인을 읽지 못하며,
인증 파일 복사는 키링 로그인과 호환되지 않고 토큰 갱신 상태도 갈라지므로 사용하지 않습니다.
전역 지시만 별도로 끄면서 인증 저장소를 유지하는 지원 옵션은 확인하지 못했습니다.
따라서 전역 지시가 번역 결과에 영향을 줄 수 있습니다. 읽기 전용 sandbox는 **모델이 실행하는 명령의
파일 쓰기와 네트워크 접근**을 막지만, 파일 읽기는 허용하며 CLI 자체의 인증·모델 통신과 상태 저장까지
막는 완전한 격리는 아닙니다. 참고: [AGENTS 탐색](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[훅](https://learn.chatgpt.com/docs/hooks), [인증 저장소 구현](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/login/src/auth/storage.rs).

`claude -p`는 safe mode에서 모든 도구를 끕니다. 여러 줄인 번역 지시문은 임시 파일을
`--system-prompt-file`로 전달하므로 Windows `.cmd`·`.bat` 런처에서도 잘리지 않습니다.
자막 안의 지시 문구는 데이터로 번역합니다. 작업 폴더는 데이터 폴더 아래 `translation-temp/`의
임시 폴더이며 실행 후 정리합니다(강제 종료 때 남은 임시 폴더는 삭제해도 됩니다).
Windows Job으로 CLI 자식·손자 프로세스를 묶어 앱 종료 시 함께 종료합니다.

## 한국어 다듬기

DB v4의 기존 번역 자막 자리에 `ko` 영상에서는 **다듬은 자막**을 저장합니다.
원어 줄 ID와 시각을 유지하고 원어는 덮어쓰지 않습니다. 작업 종류는 원어 세대의 언어로
결정하며, 방식·모델·추론 강도·맥락·용어집·묶음·이어받기·보류·진행 저장을 번역과 공유합니다.
원어 언어 변경·전체 재생성은 이전 결과와 검수를 함께 교체하고, 구간 재생성은 교체한 줄만 처리합니다.

## 자막 검수와 구간 다시 생성

검수 로직은 `review.py`, 웹 화면은 `frontend/src/dialogs/DialogsLayer.tsx`에 있습니다. 화면은 웹 브리지를 통해 `AppCore` 공개 메서드를
호출합니다. 검색 색인은 이 기능이 별도로 갱신하지 않으며, 검색 모듈의 DB 트리거를 따릅니다.
`tests/test_review.py`는 줄 ID 유지·선택 재번역·검수 보호·동시 응답·구간 경계와 줄 수 변화·
실패와 취소·전체 교체·부분 SRT와 명시적 저장을 공개 코어 API로 검증합니다.

구간 다시 생성은 받아쓰기 어댑터에 `start`와 `duration`을 넘기며 FFmpeg가 해당 구간만 디코드합니다.
반환 시각은 구간 상대값이고 확장 범위로 자른 뒤 저장 때 시작 시각을 더합니다. 새 줄은 새 UUID를 받고
이전 줄의 번역·검수 기록은 CASCADE로 지웁니다. 새 줄만 추가 번역 대상으로 넣습니다.

`UNIQUE(transcript_id, ordinal)`을 유지하기 위해 기존 ordinal을 먼저 임시 음수로 옮긴 뒤
최종 순서로 돌립니다. 삭제·삽입·순서 변경·번역 요청은 한 트랜잭션입니다.

SRT는 기존 `transcript_srt`로 1부터 연속 번호와 `HH:MM:SS,mmm` 시각을 생성합니다.
