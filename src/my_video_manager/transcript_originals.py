"""검수 전 원어 자막 원문: 받아쓰기가 만든 줄이 처음 바뀌기 직전의 모습(글자, 시작·끝 시각)을 한 번만 남긴다.

받아쓰기 품질을 판단할 근거(사용자가 무엇을 고쳤나)를 쌓는 분석용 기록이다. 화면에는 보이지 않는다.
- 검수로 원어 줄의 글자를 처음 고칠 때: 고치기 전 줄을 남긴다. 같은 줄을 다시 고쳐도 처음 기록은 바뀌지 않는다.
- 구간 다시 만들기가 줄을 지울 때: 아직 기록이 없으면 지우기 전 줄을 남기고, 지운 시각과 까닭(range)을 적는다.
- 전체 다시 생성이 원어 자막을 바꿀 때: 이미 남긴 기록에만 지운 시각과 까닭(whole)을 적는다. 고치지 않은 줄을 모두
  옮겨 적지는 않는다.
원어 줄(transcript_lines)의 글자·시각을 바꾸거나 줄을 지우는 새 코드도 바꾸기 전에 여기의 기록 함수를 불러야 한다.
DB 트리거로 두지 않은 것은 지운 까닭(구간·전체)과 앱의 시계를 트리거가 알 수 없기 때문이다.

기록은 줄·원어 자막이 지워져도 남도록 그 둘을 외래 키로 걸지 않고, 그 줄을 만든 받아쓰기 모델과 원어를 함께 적는다.
원어 자막의 모델(transcripts.model)은 전체 받아쓰기의 모델이라, 구간 다시 만들기가 다른 모델로 만든 줄은 그 모델을
transcript_line_models에 따로 둔다. v12 이전에 만든 원어 자막(transcripts.line_models_tracked = 0)은 그 전의 구간 다시
만들기가 쓴 모델을 알 수 없어, 따로 둔 모델이 없는 줄은 원어 자막의 모델로 적고 model_inferred로 표시한다.
DB 파일에 있으므로 백업과 백업 복원에 그대로 들어간다.
"""

from dataclasses import dataclass
from datetime import datetime

RANGE = "range"  # 구간 다시 만들기
WHOLE = "whole"  # 전체 다시 생성


def migrate_transcript_originals(db) -> None:
    """v12: 검수 전 원어 자막 원문. 이전과 최초 생성이 공유한다. 기존 라이브러리에는 기록이 없다(이미 덮어쓴 원문은 알 수
    없다)."""
    db.execute("""CREATE TABLE transcript_line_originals (
        line_id TEXT PRIMARY KEY,
        video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
        transcript_id TEXT NOT NULL,
        model TEXT NOT NULL,
        model_inferred INTEGER NOT NULL,
        spoken_language TEXT NOT NULL,
        start REAL NOT NULL,
        end REAL NOT NULL,
        text TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        removed_at TEXT,
        removed_by TEXT CHECK (removed_by IN ('range', 'whole')),
        CHECK ((removed_at IS NULL) = (removed_by IS NULL)))""")
    db.execute("CREATE INDEX transcript_line_originals_video ON transcript_line_originals(video_id)")
    # 구간 다시 만들기로 만든 줄의 받아쓰기 모델. 없는 줄은 원어 자막의 모델로 만든 줄이다. 원어 자막 표가 아직 없어도
    # 외래 키는 쓸 때 검사하므로 만들 수 있다.
    db.execute("""CREATE TABLE transcript_line_models (
        line_id TEXT PRIMARY KEY REFERENCES transcript_lines(id) ON DELETE CASCADE,
        model TEXT NOT NULL)""")
    # 이미 있는 원어 자막은 줄별 모델을 모른다. 원어 자막 표가 아직 없으면 자막 모듈이 이 열(기본 1)을 포함해 만든다.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transcripts'").fetchone():
        db.execute(f"ALTER TABLE transcripts ADD COLUMN {LINE_MODELS_TRACKED}")
        db.execute("UPDATE transcripts SET line_models_tracked = 0")


# 원어 자막 표의 열 정의. 자막 모듈의 최초 생성과 v12 이전이 같은 정의를 쓴다.
LINE_MODELS_TRACKED = "line_models_tracked INTEGER NOT NULL DEFAULT 1"


@dataclass(frozen=True)
class OriginalTranscriptLine:
    """줄 하나가 처음 바뀌기 직전의 모습. removed_by는 그 줄이 지워졌으면 range(구간 다시 만들기)나 whole(전체 다시
    생성)이고, 남아 있으면 None이다. spoken_language는 원어를 몰랐으면 None이다. model_inferred는 그 줄을 만든 모델을
    알 수 없어 원어 자막의 모델로 적었는지다(v12 이전 원어 자막의 줄)."""
    line_id: str
    video_id: int
    transcript_id: str
    model: str
    model_inferred: bool
    spoken_language: str | None
    start: float
    end: float
    text: str
    recorded_at: datetime
    removed_at: datetime | None = None
    removed_by: str | None = None


def record_before_change(db, line_ids, now: str) -> None:
    """줄들이 바뀌기 직전에 부른다. 아직 기록이 없는 줄만 지금 모습을 남긴다."""
    db.executemany(
        "INSERT OR IGNORE INTO transcript_line_originals"
        "(line_id, video_id, transcript_id, model, model_inferred, spoken_language, start, end, text, recorded_at) "
        "SELECT l.id, t.video_id, t.id, COALESCE(m.model, t.model), m.model IS NULL AND NOT t.line_models_tracked, "
        "t.spoken_language, l.start, l.end, l.text, ? "
        "FROM transcript_lines l JOIN transcripts t ON t.id = l.transcript_id "
        "LEFT JOIN transcript_line_models m ON m.line_id = l.id WHERE l.id = ?",
        [(now, line_id) for line_id in line_ids])


def record_line_models(db, line_ids, model: str) -> None:
    """구간 다시 만들기가 새로 만든 줄의 받아쓰기 모델을 남긴다."""
    db.executemany("INSERT INTO transcript_line_models VALUES (?, ?)", [(line_id, model) for line_id in line_ids])


def record_removed(db, line_ids, now: str, removed_by: str) -> None:
    """줄들이 지워지기 직전에 부른다. 기록이 없으면 남기고, 지운 시각과 까닭을 적는다(처음 지운 것만)."""
    line_ids = list(line_ids)
    record_before_change(db, line_ids, now)
    db.executemany("UPDATE transcript_line_originals SET removed_at = ?, removed_by = ? "
                   "WHERE line_id = ? AND removed_at IS NULL", [(now, removed_by, line_id) for line_id in line_ids])


def record_transcript_replaced(db, video_id, now: str) -> None:
    """전체 다시 생성이 그 영상의 원어 자막을 지우기 직전에 부른다. 이미 남긴 기록 가운데 지금 원어 자막의 줄에만
    지운 시각을 적는다."""
    db.execute("UPDATE transcript_line_originals SET removed_at = ?, removed_by = ? WHERE removed_at IS NULL "
               "AND transcript_id = (SELECT id FROM transcripts WHERE video_id = ?)", (now, WHOLE, video_id))


def originals(db, video_id) -> tuple[OriginalTranscriptLine, ...]:
    """영상의 기록. 처음 기록한 순서(같으면 줄 시작 시각 순서)다."""
    return tuple(OriginalTranscriptLine(
        row["line_id"], row["video_id"], row["transcript_id"], row["model"], bool(row["model_inferred"]),
        None if row["spoken_language"] == "und" else row["spoken_language"], row["start"], row["end"], row["text"],
        datetime.fromisoformat(row["recorded_at"]),
        datetime.fromisoformat(row["removed_at"]) if row["removed_at"] else None, row["removed_by"])
        for row in db.execute("SELECT * FROM transcript_line_originals WHERE video_id = ? "
                              "ORDER BY recorded_at, start, line_id", (video_id,)))
