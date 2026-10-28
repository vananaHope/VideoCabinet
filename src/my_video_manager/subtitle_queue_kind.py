"""대기열 작업의 종류. 번역·다듬기 같은 처리 단계와는 별개다."""

TRANSCRIPTION = "transcription"


def queue_task_key(entry):
    """번역·다듬기 단계도 같은 받아쓰기 작업의 순서와 완료 기록을 쓴다."""
    return entry.video_id, entry.queue_kind
