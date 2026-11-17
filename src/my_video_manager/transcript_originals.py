"""검수 전 원어 자막 원문: 받아쓰기가 만든 줄이 처음 바뀌기 직전의 모습(글자, 시작·끝 시각)을 한 번만 남긴다.

받아쓰기 품질을 판단할 근거(사용자가 무엇을 고쳤나)를 쌓는 분석용 기록이다. 화면에는 보이지 않는다.
- 검수로 원어 줄의 글자를 처음 고칠 때: 고치기 전 줄을 남긴다. 같은 줄을 다시 고쳐도 처음 기록은 바뀌지 않는다.
- 구간 다시 만들기가 줄을 지울 때: 아직 기록이 없으면 지우기 전 줄을 남기고, 지운 시각과 까닭(range)을 적는다.
- 전체 다시 생성이 원어 자막을 바꿀 때: 이미 남긴 기록에만 지운 시각과 까닭(whole)을 적는다. 고치지 않은 줄을 모두
  옮겨 적지는 않는다.

기록은 줄·원어 자막이 지워져도 남도록 그 둘을 외래 키로 걸지 않고, 그 줄을 만든 받아쓰기 모델과 원어를 함께 적는다.
원어 자막의 모델(transcripts.model)은 전체 받아쓰기의 모델이라, 구간 다시 만들기가 다른 모델로 만든 줄은 그 모델을
transcript_line_models에 따로 둔다. DB 파일에 있으므로 백업과 백업 복원에 그대로 들어간다.
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


@dataclass(frozen=True)
class OriginalTranscriptLine:
    """줄 하나가 처음 바뀌기 직전의 모습. removed_by는 그 줄이 지워졌으면 range(구간 다시 만들기)나 whole(전체 다시
    생성)이고, 남아 있으면 None이다. spoken_language는 원어를 몰랐으면 None이다."""
    line_id: str
    video_id: int
    transcript_id: str
    model: str
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
        "(line_id, video_id, transcript_id, model, spoken_language, start, end, text, recorded_at) "
        "SELECT l.id, t.video_id, t.id, COALESCE(m.model, t.model), t.spoken_language, l.start, l.end, l.text, ? "
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
    _mark_removed(db, "line_id = ?", [(line_id,) for line_id in line_ids], now, removed_by)


def record_transcript_replaced(db, video_id, now: str) -> None:
    """전체 다시 생성이 그 영상의 원어 자막을 지우기 직전에 부른다. 이미 남긴 기록 가운데 지금 원어 자막의 줄에만
    지운 시각을 적는다."""
    _mark_removed(db, "transcript_id = (SELECT id FROM transcripts WHERE video_id = ?)", [(video_id,)], now, WHOLE)


def _mark_removed(db, where, parameters, now, removed_by) -> None:
    db.executemany(f"UPDATE transcript_line_originals SET removed_at = ?, removed_by = ? "
                   f"WHERE removed_at IS NULL AND {where}", [(now, removed_by, *values) for values in parameters])


def originals(db, video_id) -> tuple[OriginalTranscriptLine, ...]:
    """영상의 기록. 처음 기록한 순서(같으면 줄 시작 시각 순서)다."""
    return tuple(OriginalTranscriptLine(
        row["line_id"], row["video_id"], row["transcript_id"], row["model"],
        None if row["spoken_language"] == "und" else row["spoken_language"], row["start"], row["end"], row["text"],
        datetime.fromisoformat(row["recorded_at"]),
        datetime.fromisoformat(row["removed_at"]) if row["removed_at"] else None, row["removed_by"])
        for row in db.execute("SELECT * FROM transcript_line_originals WHERE video_id = ? "
                              "ORDER BY recorded_at, start, line_id", (video_id,)))
