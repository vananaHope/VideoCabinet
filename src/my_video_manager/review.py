"""줄 검수와 구간 교체. 기존 자막 테이블의 구조와 줄 식별 계약을 유지한다."""

from dataclasses import dataclass, replace
from contextlib import nullcontext
import math
from pathlib import Path
import re
from uuid import uuid4

from .subtitles import TranscriptLine, transcript_srt


class ReviewConfirmationRequired(ValueError):
    pass


@dataclass(frozen=True)
class ReviewLine:
    original: TranscriptLine
    translation: str | None
    original_reviewed: bool
    translation_reviewed: bool


@dataclass(frozen=True)
class SubtitleExport:
    text: str
    missing_lines: int
    default_path: Path


@dataclass(frozen=True)
class ReviewPlayback:
    video_id: int
    start: float
    action: str  # play 또는 seek. 재생 엔진이 수행할 동작.


class Review:
    def __init__(self, connect, clock, subtitles, playback_location):
        self._connect, self._clock = connect, clock
        self._subtitles, self._playback_location = subtitles, playback_location
        self.translations = None
        with connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS subtitle_reviews (
                    line_id TEXT PRIMARY KEY REFERENCES transcript_lines(id) ON DELETE CASCADE,
                    original_reviewed INTEGER NOT NULL DEFAULT 0,
                    translation_reviewed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS subtitle_review_ranges (
                    queue_id INTEGER PRIMARY KEY REFERENCES subtitle_queue(id) ON DELETE CASCADE,
                    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    start REAL NOT NULL,
                    end REAL NOT NULL
                );
            """)

    def lines(self, video_id, *, connection=None):
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            rows = db.execute("""
                SELECT l.*, r.original_reviewed, r.translation_reviewed,
                       COALESCE(tr.text, target.text) AS translated
                FROM transcript_lines l JOIN transcripts t ON t.id = l.transcript_id
                LEFT JOIN subtitle_reviews r ON r.line_id = l.id
                LEFT JOIN translation_lines tr ON tr.line_id = l.id
                LEFT JOIN translation_targets target ON target.line_id = l.id
                WHERE t.video_id = ? ORDER BY l.ordinal
            """, (video_id,)).fetchall()
        return tuple(ReviewLine(TranscriptLine(r["id"], r["start"], r["end"], r["text"]),
                                r["translated"], bool(r["original_reviewed"]),
                                bool(r["translation_reviewed"])) for r in rows)

    def reviewed_count(self, video_id):
        return sum(line.original_reviewed or line.translation_reviewed for line in self.lines(video_id))

    def regeneration_warning(self, video_id):
        return (f"전체를 다시 생성하면 검수한 {self.reviewed_count(video_id)}줄(원어 수정·번역 직접 수정)을 "
                "포함한 기존 원어 자막과 번역 자막이 사라집니다. 계속할까요?")

    @staticmethod
    def _line(db, video_id, line_id):
        row = db.execute("SELECT l.*, t.spoken_language FROM transcript_lines l JOIN transcripts t "
                         "ON t.id = l.transcript_id WHERE l.id = ? AND t.video_id = ?",
                         (line_id, video_id)).fetchone()
        if row is None:
            raise ValueError("자막 줄이 바뀌었습니다. 목록을 새로 확인하세요.")
        return row

    @staticmethod
    def _editable(db, video_id):
        if db.execute("SELECT 1 FROM subtitle_queue WHERE video_id = ? AND state = 'queued'",
                      (video_id,)).fetchone():
            raise ValueError("원어 자막 재생성이 끝난 뒤 검수하세요.")

    def edit(self, video_id, line_id, text, *, translated=False, overwrite_reviewed=False):
        text = text.strip()
        if not text:
            raise ValueError("자막 텍스트를 입력하세요.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._line(db, video_id, line_id)
            self._editable(db, video_id)
            eligible = row["spoken_language"] not in ("ko", "und")
            if translated and not eligible:
                raise ValueError("한국어이거나 원어를 알 수 없는 자막은 번역할 수 없습니다.")
            if not translated and row["text"] == text:
                return
            reviewed = db.execute("SELECT translation_reviewed FROM subtitle_reviews WHERE line_id = ?",
                                  (line_id,)).fetchone()
            if not translated and reviewed and reviewed[0] and not overwrite_reviewed:
                raise ReviewConfirmationRequired("직접 고친 번역이 덮어써집니다. 계속할까요?")
            db.execute("INSERT OR IGNORE INTO subtitle_reviews(line_id) VALUES (?)", (line_id,))
            if translated:
                db.execute("UPDATE subtitle_reviews SET translation_reviewed = 1 WHERE line_id = ?", (line_id,))
                db.execute("INSERT INTO translation_lines VALUES (?, ?) ON CONFLICT(line_id) "
                           "DO UPDATE SET text = excluded.text", (line_id, text))
                # 이미 실행 중인 응답도 이 줄을 다시 쓰지 못한다.
                db.execute("DELETE FROM translation_targets WHERE line_id = ?", (line_id,))
                self.translations.finish_ready(db, video_id)
            else:
                db.execute("UPDATE transcript_lines SET text = ? WHERE id = ?", (text, line_id))
                db.execute("UPDATE subtitle_reviews SET original_reviewed = 1, translation_reviewed = 0 "
                           "WHERE line_id = ?", (line_id,))
                if eligible:
                    self.translations.request(video_id, [line_id], connection=db)

    def request_range(self, video_id, start, end):
        self._playback_location(video_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            duration = db.execute("SELECT duration FROM videos WHERE id = ?", (video_id,)).fetchone()[0]
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration):
                raise ValueError("구간은 0 이상 영상 길이 이하이며 끝이 시작보다 뒤여야 합니다.")
            self._editable(db, video_id)
            transcript = db.execute("SELECT * FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
            if transcript is None:
                raise ValueError("먼저 원어 자막을 만드세요.")
            db.execute("DELETE FROM subtitle_queue WHERE video_id = ?", (video_id,))
            language = transcript["spoken_language"]
            cursor = db.execute("INSERT INTO subtitle_queue(video_id, spoken_language, requested_at) VALUES (?, ?, ?)",
                                (video_id, None if language == "und" else language, self._clock().isoformat()))
            db.execute("INSERT INTO subtitle_review_ranges VALUES (?, ?, ?, ?)",
                       (cursor.lastrowid, transcript["id"], start, end))
        return next(e for e in self._subtitles.queue() if e.id == cursor.lastrowid)

    def range_for(self, queue_id):
        with self._connect() as db:
            return db.execute("SELECT * FROM subtitle_review_ranges WHERE queue_id = ?", (queue_id,)).fetchone()

    def replace_range(self, db, pending, interval, segments):
        """상대 시각 결과를 [start, end)로 옮기고 시작이 구간 안인 줄만 교체한다."""
        start, end = interval["start"], interval["end"]
        transcript_id = interval["transcript_id"]
        if any(s.start >= end - start or s.end > end - start + 0.001 for s in segments):
            raise ValueError("받아쓰기 결과가 요청한 구간을 벗어났습니다.")
        db.execute("DELETE FROM transcript_lines WHERE transcript_id = ? AND start >= ? AND start < ?",
                   (transcript_id, start, end))
        retained = db.execute("SELECT id, start FROM transcript_lines WHERE transcript_id = ? ORDER BY ordinal",
                              (transcript_id,)).fetchall()
        # UNIQUE는 행마다 검사된다. 모든 기존 순서를 먼저 충돌하지 않는 음수로 이동한다.
        db.execute("UPDATE transcript_lines SET ordinal = -ordinal - 1 WHERE transcript_id = ?", (transcript_id,))
        new = [(uuid4().hex, s) for s in segments]
        ordered = [(r["id"], r["start"]) for r in retained] + [(id_, start + s.start) for id_, s in new]
        ordered.sort(key=lambda item: item[1])
        ordinals = {id_: i for i, (id_, _) in enumerate(ordered)}
        db.executemany("UPDATE transcript_lines SET ordinal = ? WHERE id = ?",
                       [(ordinals[r["id"]], r["id"]) for r in retained])
        db.executemany("INSERT INTO transcript_lines VALUES (?, ?, ?, ?, ?, ?)",
                       [(id_, transcript_id, ordinals[id_], start + s.start, min(end, start + s.end), s.text.strip())
                        for id_, s in new])
        language = db.execute("SELECT spoken_language FROM transcripts WHERE id = ?", (transcript_id,)).fetchone()[0]
        if new and language not in ("ko", "und"):
            self.translations.request(pending.video_id, [id_ for id_, _ in new], connection=db)
        self.translations.finish_ready(db, pending.video_id)

    def export(self, video_id, *, translated=False):
        with self._connect() as db:
            db.execute("BEGIN")
            transcript = self._subtitles.transcript(video_id, connection=db)
            if transcript is None:
                raise ValueError("내보낼 원어 자막이 없습니다.")
            lines = self.lines(video_id, connection=db)
            title = db.execute("SELECT title FROM videos WHERE id = ?", (video_id,)).fetchone()[0]
        selected = tuple(replace(line.original, text=line.translation) if translated else line.original
                         for line in lines if not translated or line.translation is not None)
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).rstrip(". ") or "영상"
        language = "ko" if translated else transcript.spoken_language or "und"
        # 파일 없음 영상도 검수·내보내기는 가능하다. 위치가 없으면 홈 폴더를 제안한다.
        try:
            folder = self._playback_location(video_id).path.parent
        except (ValueError, FileNotFoundError):
            folder = Path.home()
        return SubtitleExport(transcript_srt(replace(transcript, lines=selected)),
                              len(lines) - len(selected), folder / f"{filename}.{language}.srt")
