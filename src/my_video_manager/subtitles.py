"""원어 자막과 영속 자막 대기열. 외부 받아쓰기 중에는 DB를 잠그지 않는다."""

from dataclasses import dataclass
from contextlib import nullcontext
from datetime import datetime
import math
import json
from pathlib import Path
import re
from threading import Event, Lock
from typing import Callable, Protocol
from uuid import uuid4


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriberResult:
    spoken_language: str
    segments: tuple[TranscriptSegment, ...]
    language_probability: float = 1.0


class TranscriberCancelled(Exception):
    """취소는 실패가 아니다. 원래 요청을 대기열에 남긴다."""


class TranscriberError(RuntimeError):
    def __init__(self, kind: str, detail: str):
        self.kind = kind
        self.detail = detail
        super().__init__({
            "gpu_unavailable": "GPU를 사용할 수 없습니다. 드라이버와 CUDA 환경을 확인하세요.",
            "decode": "영상의 음성을 읽을 수 없습니다.",
            "model_download": "받아쓰기 모델을 내려받을 수 없습니다. 연결과 저장 공간을 확인하세요.",
        }.get(kind, "받아쓰기에 실패했습니다. 자세한 내용을 확인하세요."))


class Transcriber(Protocol):
    def transcribe(self, path: Path, spoken_language: str | None, *,
                   cancellation: Event, progress: Callable[[float], None] | None = None,
                   start: float = 0, duration: float | None = None) -> TranscriberResult:
        """구간은 start·duration 초로 지정하며 결과 시각은 구간 시작에 상대적이다.

        취소 신호를 받으면 신속하게 정리하고 TranscriberCancelled를 발생시킨다.
        """
        ...


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
    spoken_language: str | None
    language_specified: bool
    created_at: datetime
    lines: tuple[TranscriptLine, ...]

    @property
    def translation_eligible(self) -> bool:
        return bool(self.lines) and self.spoken_language not in (None, "ko")


@dataclass(frozen=True)
class SubtitleQueueEntry:
    id: int
    video_id: int
    spoken_language: str | None
    requested_at: datetime
    state: str
    error: str | None
    error_detail: str | None = None
    progress: float = 0.0
    retry_guidance: str | None = None


def normalize_spoken_language(language: str | None) -> str | None:
    if language is None:
        return None
    language = language.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", language):
        raise ValueError("원어는 en, ko, ja 같은 언어 코드로 지정하세요.")
    return language


class Subtitles:
    def __init__(self, connect, clock, transcriber, playback_location, order):
        self._connect = connect
        self._clock = clock
        self._transcriber = transcriber
        self._playback_location = playback_location
        self._processing = Lock()
        self._cancellation = Event()
        self._order = order
        self._progress = {}
        self._active_video = None
        self._active_cancellation = None
        self._activity = Lock()
        self.review = None
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
            db.execute("UPDATE subtitle_queue SET state = 'queued' WHERE state = 'transcribing'")

    def request(self, video_id: int, spoken_language: str | None, *, automatic=False) -> SubtitleQueueEntry | None:
        language = normalize_spoken_language(spoken_language)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone():
                raise ValueError("영상을 찾을 수 없습니다.")
            old = db.execute("SELECT * FROM subtitle_queue WHERE video_id = ?", (video_id,)).fetchone()
            if automatic and (old or db.execute("SELECT 1 FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()):
                return self._entry(old) if old else None
            is_range = self.review and self.review.range_for(old["id"]) if old else False
            if old and not is_range and old["state"] in ("queued", "transcribing") and old["spoken_language"] == language:
                self._order.request(db, video_id, automatic=automatic)
                return self._entry(old)  # 같은 요청의 더블클릭은 순서를 바꾸지 않는다.
            self._order.request(db, video_id, automatic=automatic, renew=True)
            db.execute("DELETE FROM subtitle_queue WHERE video_id = ?", (video_id,))
            cursor = db.execute(
                "INSERT INTO subtitle_queue(video_id, spoken_language, requested_at) VALUES (?, ?, ?)",
                (video_id, language, self._clock().isoformat()),
            )
            return self._entry(db.execute("SELECT * FROM subtitle_queue WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def _entry(self, row):
        message, detail = row["error"], None
        if message:
            try:
                error = json.loads(message)
                if isinstance(error, dict) and "kind" in error and "detail" in error:
                    detail = error["detail"]
                    message = str(TranscriberError(error["kind"], detail))
            except (ValueError, TypeError):
                pass  # 이전 버전의 일반 문자열 오류도 읽는다.
        return SubtitleQueueEntry(row["id"], row["video_id"], row["spoken_language"],
                                  datetime.fromisoformat(row["requested_at"]), row["state"], message, detail,
                                  self._progress.get(row["id"], 0),
                                  self._retry_guidance(row["id"]) if message else None)

    def _retry_guidance(self, queue_id):
        return ("검수 창의 구간 다시 생성으로 재시도하세요"
                if self.review and self.review.range_for(queue_id) else "다시 요청하면 재시도합니다")

    def queue(self) -> tuple[SubtitleQueueEntry, ...]:
        with self._connect() as db:
            entries = tuple(self._entry(row) for row in db.execute("SELECT * FROM subtitle_queue ORDER BY id"))
        return self._order.sort(entries)

    def remove(self, video_id):
        with self._activity:
            with self._connect() as db:
                db.execute("DELETE FROM subtitle_queue WHERE video_id = ?", (video_id,))
            if self._active_video == video_id and self._active_cancellation:
                self._active_cancellation.set()

    def resume_processing(self):
        self._cancellation.clear()

    def transcript(self, video_id: int, *, connection=None) -> Transcript | None:
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            if not db.in_transaction:
                db.execute("BEGIN")  # 생성 세대와 줄을 같은 읽기 스냅샷에서 읽는다.
            row = db.execute("SELECT * FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
            if row is None:
                return None
            lines = tuple(TranscriptLine(line["id"], line["start"], line["end"], line["text"])
                          for line in db.execute("SELECT * FROM transcript_lines WHERE transcript_id = ? ORDER BY ordinal",
                                                 (row["id"],)))
            language = row["spoken_language"]
            if language == "und" or (not lines and not row["language_specified"]):
                language = None
            return Transcript(video_id, row["id"], language, bool(row["language_specified"]),
                              datetime.fromisoformat(row["created_at"]), lines)

    def has_transcript(self, video_id: int) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM transcripts WHERE video_id = ?", (video_id,)).fetchone() is not None

    def stop_processing(self) -> None:
        """현재 AppCore의 처리를 중단한다. 대기열은 다음 앱 실행에서 재개한다."""
        self._cancellation.set()
        with self._activity:
            if self._active_cancellation:
                self._active_cancellation.set()

    def process_next(self) -> SubtitleQueueEntry | None:
        # 한 AppCore의 작업자는 하나다. 재진입 호출은 현재 처리를 기다리거나 중복 실행하지 않는다.
        if self._cancellation.is_set() or not self._processing.acquire(blocking=False):
            return None
        try:
            pending = next((entry for entry in self.queue() if entry.state == "queued"), None)
            if pending is None:
                return None
            with self._activity:
                with self._connect() as db:
                    changed = db.execute("UPDATE subtitle_queue SET state = 'transcribing' WHERE id = ? AND state = 'queued'",
                                         (pending.id,)).rowcount
                    duration = db.execute("SELECT duration FROM videos WHERE id = ?", (pending.video_id,)).fetchone()[0]
                self._active_video = pending.video_id
                cancellation = self._active_cancellation = Event()
                if self._cancellation.is_set():
                    cancellation.set()
            if not changed:
                return None
            try:
                if self._transcriber is None:
                    raise RuntimeError("받아쓰기 어댑터가 설정되지 않았습니다.")
                interval = self.review.range_for(pending.id) if self.review else None
                options = {"start": interval["start"], "duration": interval["end"] - interval["start"]} if interval else {}
                duration = options.get("duration", duration)
                def report_progress(seconds):
                    self._progress[pending.id] = min(0.99, max(0, seconds / max(duration, 0.001)))
                result = self._transcriber.transcribe(self._playback_location(pending.video_id).path,
                                                     pending.spoken_language, cancellation=cancellation,
                                                     progress=report_progress, **options)
                if cancellation.is_set():
                    raise TranscriberCancelled
                language = normalize_spoken_language(pending.spoken_language or result.spoken_language)
                if language is None:
                    raise ValueError("받아쓰기 결과에 원어가 없습니다.")
                if pending.spoken_language is None and (not result.segments or result.language_probability < 0.5):
                    language = "und"  # DB의 기존 NOT NULL 계약을 유지하고 공개 API에서는 None.
                for segment in result.segments:
                    if (not math.isfinite(segment.start) or not math.isfinite(segment.end)
                            or (segment.start < 0 and interval is None)
                            or segment.end <= segment.start or not segment.text.strip()):
                        raise ValueError("받아쓰기 결과의 자막 줄이 올바르지 않습니다.")
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if self._cancellation.is_set():
                        raise TranscriberCancelled
                    # 실행 도중 원어를 바꿨으면 이전 결과로 최신 요청을 덮어쓰지 않는다.
                    if not db.execute("SELECT 1 FROM subtitle_queue WHERE id = ?", (pending.id,)).fetchone():
                        return pending
                    if interval:
                        self.review.replace_range(db, pending, interval, result.segments)
                        db.execute("DELETE FROM subtitle_queue WHERE id = ?", (pending.id,))
                        return SubtitleQueueEntry(pending.id, pending.video_id, pending.spoken_language,
                                                  pending.requested_at, "completed", None)
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
            except TranscriberCancelled:
                with self._connect() as db:
                    db.execute("UPDATE subtitle_queue SET state = 'queued' WHERE id = ?", (pending.id,))
                return pending
            except Exception as error:
                failure = error if isinstance(error, TranscriberError) else TranscriberError("other", str(error))
                with self._connect() as db:
                    db.execute("UPDATE subtitle_queue SET state = 'failed', error = ? WHERE id = ?",
                               (json.dumps({"kind": failure.kind, "detail": failure.detail}, ensure_ascii=False), pending.id))
                return SubtitleQueueEntry(pending.id, pending.video_id, pending.spoken_language,
                                          pending.requested_at, "failed", str(failure), failure.detail,
                                          retry_guidance=self._retry_guidance(pending.id))
        finally:
            with self._activity:
                self._active_video = self._active_cancellation = None
            if 'pending' in locals() and pending:
                self._progress.pop(pending.id, None)
            self._processing.release()


def normalize_subtitle_text(text: str) -> str:
    """큐 내부의 빈 줄을 제거해 SRT 블록 경계와 혼동되지 않게 한다."""
    return "\n".join(line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                     if line.strip())


def transcript_srt(transcript: Transcript) -> str:
    """플레이어 전달용 순수 변환. 영구 저장과 줄의 식별은 DB가 담당한다."""
    def timestamp(seconds):
        milliseconds = round(seconds * 1000)
        seconds, ms = divmod(milliseconds, 1000)
        minutes, sec = divmod(seconds, 60)
        hours, minute = divmod(minutes, 60)
        return f"{hours:02}:{minute:02}:{sec:02},{ms:03}"

    return "\n\n".join(f"{i}\n{timestamp(line.start)} --> {timestamp(line.end)}\n{normalize_subtitle_text(line.text)}"
                       for i, line in enumerate(transcript.lines, 1)) + "\n"
