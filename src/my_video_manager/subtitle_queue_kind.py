"""대기열 작업의 종류. 번역·다듬기 같은 처리 단계와는 별개다."""

TRANSCRIPTION = "transcription"
ONSCREEN_SUBTITLE = "onscreen_subtitle"

# 대기열 화면에서 작업 종류를 구별하는 이름. 같은 영상의 두 작업이 섞여 보이지 않게 한다.
QUEUE_KIND_LABELS = {TRANSCRIPTION: "받아쓰기", ONSCREEN_SUBTITLE: "화면 자막"}


def queue_task_key(entry):
    """번역·다듬기 단계도 같은 받아쓰기 작업의 순서와 완료 기록을 쓴다."""
    return entry.video_id, entry.queue_kind
