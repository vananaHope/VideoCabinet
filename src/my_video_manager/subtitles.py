"""원어 자막과 영속 자막 대기열. 외부 받아쓰기 중에는 DB를 잠그지 않는다."""

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import re
from threading import Lock
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcription:
    spoken_language: str
    segments: tuple[TranscriptSegment, ...]


class Transcriber(Protocol):
    def transcribe(self, path: Path, spoken_language: str | None) -> Transcription: ...


@dataclass(frozen=True)
class TranscriptLine:
    id: str
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    video_id: int
    id: str
    spoken_language: str
    language_specified: bool
    created_at: datetime
    lines: tuple[TranscriptLine, ...]


@dataclass(frozen=True)
class SubtitleQueueEntry:
    id: int
    video_id: int
    spoken_language: str | None
    requested_at: datetime
    state: str
    error: str | None


def normalize_spoken_language(language: str | None) -> str | None:
    if language is None:
        return None
    language = language.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", language):
        raise ValueError("원어는 en, ko, ja 같은 언어 코드로 지정하세요.")
    return language


class Subtitles:
    def __init__(self, connect, clock, transcriber, playback_location):
        self._connect = connect
        self._clock = clock
        self._transcriber = transcriber
        self._playback_location = playback_location
        self._processing = Lock()
        with connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS subtitle_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
                    spoken_language TEXT,
                    requested_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS transcripts (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id),
                    id TEXT NOT NULL UNIQUE,
                    spoken_language TEXT NOT NULL,
                    language_specified INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transcript_lines (
                    id TEXT PRIMARY KEY,
                    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    start REAL NOT NULL,
                    end REAL NOT NULL,
                    text TEXT NOT NULL,
                    UNIQUE(transcript_id, ordinal)
                );
            """)

    def request(self, video_id: int, spoken_language: str | None) -> SubtitleQueueEntry:
        language = normalize_spoken_language(spoken_language)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone():
                raise ValueError("영상을 찾을 수 없습니다.")
            old = db.execute("SELECT * FROM subtitle_queue WHERE video_id = ?", (video_id,)).fetchone()
            if old and old["state"] == "queued" and old["spoken_language"] == language:
                return self._entry(old)  # 같은 요청의 더블클릭은 순서를 바꾸지 않는다.
            db.execute("DELETE FROM subtitle_queue WHERE video_id = ?", (video_id,))
            cursor = db.execute(
                "INSERT INTO subtitle_queue(video_id, spoken_language, requested_at) VALUES (?, ?, ?)",
                (video_id, language, self._clock().isoformat()),
            )
            return self._entry(db.execute("SELECT * FROM subtitle_queue WHERE id = ?", (cursor.lastrowid,)).fetchone())

    @staticmethod
    def _entry(row):
        return SubtitleQueueEntry(row["id"], row["video_id"], row["spoken_language"],
                                  datetime.fromisoformat(row["requested_at"]), row["state"], row["error"])

    def queue(self) -> tuple[SubtitleQueueEntry, ...]:
        with self._connect() as db:
            return tuple(self._entry(row) for row in db.execute("SELECT * FROM subtitle_queue ORDER BY id"))

    def transcript(self, video_id: int) -> Transcript | None:
        with self._connect() as db:
            db.execute("BEGIN")  # 생성 세대와 줄을 같은 읽기 스냅샷에서 읽는다.
            row = db.execute("SELECT * FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
            if row is None:
                return None
            lines = tuple(TranscriptLine(line["id"], line["start"], line["end"], line["text"])
                          for line in db.execute("SELECT * FROM transcript_lines WHERE transcript_id = ? ORDER BY ordinal",
                                                 (row["id"],)))
            return Transcript(video_id, row["id"], row["spoken_language"], bool(row["language_specified"]),
                              datetime.fromisoformat(row["created_at"]), lines)

    def process_next(self) -> SubtitleQueueEntry | None:
        # 한 AppCore의 작업자는 하나다. 재진입 호출은 현재 처리를 기다리거나 중복 실행하지 않는다.
        if not self._processing.acquire(blocking=False):
            return None
        try:
            pending = next((entry for entry in self.queue() if entry.state == "queued"), None)
            if pending is None:
                return None
            try:
                if self._transcriber is None:
                    raise RuntimeError("받아쓰기 어댑터가 설정되지 않았습니다.")
                result = self._transcriber.transcribe(self._playback_location(pending.video_id).path,
                                                     pending.spoken_language)
                language = normalize_spoken_language(pending.spoken_language or result.spoken_language)
                if language is None:
                    raise ValueError("받아쓰기 결과에 원어가 없습니다.")
                for segment in result.segments:
                    if (not math.isfinite(segment.start) or not math.isfinite(segment.end)
                            or segment.start < 0 or segment.end <= segment.start or not segment.text.strip()):
                        raise ValueError("받아쓰기 결과의 자막 줄이 올바르지 않습니다.")
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    # 실행 도중 원어를 바꿨으면 이전 결과로 최신 요청을 덮어쓰지 않는다.
                    if not db.execute("SELECT 1 FROM subtitle_queue WHERE id = ?", (pending.id,)).fetchone():
                        return pending
                    transcript_id = uuid4().hex
                    db.execute("DELETE FROM transcripts WHERE video_id = ?", (pending.video_id,))
                    db.execute("INSERT INTO transcripts VALUES (?, ?, ?, ?, ?)",
                               (pending.video_id, transcript_id, language, pending.spoken_language is not None,
                                self._clock().isoformat()))
                    db.executemany("INSERT INTO transcript_lines VALUES (?, ?, ?, ?, ?, ?)",
                                   [(uuid4().hex, transcript_id, i, s.start, s.end, s.text.strip())
                                    for i, s in enumerate(result.segments)])
                    db.execute("DELETE FROM subtitle_queue WHERE id = ?", (pending.id,))
                return SubtitleQueueEntry(pending.id, pending.video_id, pending.spoken_language,
                                          pending.requested_at, "completed", None)
            except Exception as error:
                with self._connect() as db:
                    db.execute("UPDATE subtitle_queue SET state = 'failed', error = ? WHERE id = ?",
                               (str(error), pending.id))
                return SubtitleQueueEntry(pending.id, pending.video_id, pending.spoken_language,
                                          pending.requested_at, "failed", str(error))
        finally:
            # 처리 중에도 DB에는 queued를 유지한다. 강제 종료되면 다음 실행에서 처음부터 재시도한다.
            self._processing.release()


def transcript_srt(transcript: Transcript) -> str:
    """플레이어 전달용 순수 변환. 영구 저장과 줄의 식별은 DB가 담당한다."""
    def timestamp(seconds):
        milliseconds = round(seconds * 1000)
        seconds, ms = divmod(milliseconds, 1000)
        minutes, sec = divmod(seconds, 60)
        hours, minute = divmod(minutes, 60)
        return f"{hours:02}:{minute:02}:{sec:02},{ms:03}"

    return "\n\n".join(f"{i}\n{timestamp(line.start)} --> {timestamp(line.end)}\n{line.text}"
                       for i, line in enumerate(transcript.lines, 1)) + "\n"
