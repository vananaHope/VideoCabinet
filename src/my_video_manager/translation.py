"""번역 자막, 묶음 진행 저장, 보류와 재시도. CLI 호출 중 DB 잠금은 없다."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event, Lock
from typing import Protocol
from uuid import uuid4

from .subtitles import TranscriptLine


class TranslationCancelled(Exception):
    """진행한 묶음을 보존하고 다음 실행에서 이어 한다."""


class TranslationError(RuntimeError):
    def __init__(self, kind: str, detail: str):
        self.kind, self.detail = kind, detail
        super().__init__({
            "usage_limit": "구독 사용량 한도로 보류했습니다. 잠시 뒤 자동으로 재시도합니다.",
            "authentication": "번역 CLI 로그인이 필요합니다.",
            "missing_cli": "번역 CLI가 없습니다. 선택한 CLI를 설치하거나 설정을 바꾸세요.",
            "format": "번역 응답의 줄 ID 또는 형식이 올바르지 않습니다.",
            "timeout": "번역 CLI 응답 시간이 초과되었습니다.",
        }.get(kind, "번역에 실패했습니다. 자세한 내용을 확인하세요."))


@dataclass(frozen=True)
class TranslatedLine:
    id: str  # 원어 자막 줄 ID
    text: str


class Translator(Protocol):
    def translate(self, lines: tuple[TranscriptLine, ...], spoken_language: str, *,
                  cli: str, cancellation: Event) -> tuple[TranslatedLine, ...]: ...


def validate_translation(lines, result) -> tuple[TranslatedLine, ...]:
    """응답 순서는 무관하지만 대상 ID와 정확히 일대일이어야 한다."""
    try:
        result = tuple(result)
        ids = [line.id for line in result]
        if (len(ids) != len(lines) or len(set(ids)) != len(ids)
                or set(ids) != {line.id for line in lines}
                or any(not isinstance(line.text, str) or not line.text.strip() for line in result)):
            raise ValueError("ID 누락·추가·중복 또는 빈 번역")
        by_id = {line.id: line.text.strip() for line in result}
        return tuple(TranslatedLine(line.id, by_id[line.id]) for line in lines)
    except (TypeError, AttributeError, ValueError) as error:
        raise TranslationError("format", str(error)) from error


@dataclass(frozen=True)
class Translation:
    video_id: int
    transcript_id: str
    lines: tuple[TranscriptLine, ...]  # 같은 ID와 시각, 한국어 텍스트


@dataclass(frozen=True)
class TranslationQueueEntry:
    id: str
    video_id: int
    state: str
    completed_lines: int
    total_lines: int
    retry_at: datetime | None
    error: str | None
    error_detail: str | None


class Translations:
    def __init__(self, connect, clock, subtitles, settings, translator, *, batch_size=30,
                 retry_delay=timedelta(minutes=15), format_attempts=3):
        if batch_size < 1 or format_attempts < 1 or retry_delay.total_seconds() <= 0:
            raise ValueError("번역 묶음 크기, 재시도 횟수와 보류 시간은 양수여야 합니다.")
        self._connect, self._clock = connect, clock
        self._subtitles, self._settings, self._translator = subtitles, settings, translator
        self._batch_size, self._retry_delay, self._format_attempts = batch_size, retry_delay, format_attempts
        self._processing, self._cancellation = Lock(), Event()
        with connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS translation_lines (
                    line_id TEXT PRIMARY KEY REFERENCES transcript_lines(id) ON DELETE CASCADE,
                    text TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS translation_queue (
                    id TEXT PRIMARY KEY,
                    video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
                    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    requested_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    retry_at TEXT,
                    error_kind TEXT,
                    error_detail TEXT
                );
                CREATE TABLE IF NOT EXISTS translation_targets (
                    queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
                    line_id TEXT NOT NULL REFERENCES transcript_lines(id) ON DELETE CASCADE,
                    text TEXT,
                    PRIMARY KEY(queue_id, line_id)
                );
            """)
        self.enqueue_eligible()  # 원어 저장 직후 강제 종료된 경우도 복구한다.

    @property
    def cli(self):
        return self._settings.get("translation.cli", "codex")

    def set_cli(self, cli):
        if cli not in ("codex", "claude"):
            raise ValueError("번역 CLI는 codex 또는 claude를 고르세요.")
        self._settings.set("translation.cli", cli)

    def enqueue_eligible(self):
        with self._connect() as db:
            ids = [row[0] for row in db.execute("SELECT video_id FROM transcripts")]
        for video_id in ids:
            self.request(video_id, automatic=True)

    def request(self, video_id: int, line_ids=None, *, automatic=False):
        transcript = self._subtitles.transcript(video_id)
        if transcript is None or not transcript.translation_eligible:
            if automatic:
                return None
            raise ValueError("한국어이거나 원어를 알 수 없는 자막은 번역할 수 없습니다.")
        selected = set(line_ids) if line_ids is not None else {line.id for line in transcript.lines}
        if not selected or not selected <= {line.id for line in transcript.lines}:
            raise ValueError("번역할 원어 자막 줄 ID를 확인하세요.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM transcripts WHERE id = ?", (transcript.id,)).fetchone():
                return None  # 동시에 원어가 교체됐다. 다음 자동 등록에서 새 세대를 처리한다.
            old = db.execute("SELECT * FROM translation_queue WHERE video_id = ?", (video_id,)).fetchone()
            if automatic:
                if old:
                    return self._entry(db, old)
                saved = {r[0] for r in db.execute(
                    "SELECT line_id FROM translation_lines JOIN transcript_lines ON id = line_id "
                    "WHERE transcript_id = ?", (transcript.id,))}
                selected -= saved
                if not selected:
                    return None
            # 명시적인 전체 재시도는 저장한 묶음을 재사용한다.
            if old and line_ids is None:
                db.execute("UPDATE translation_queue SET state = 'queued', retry_at = NULL, "
                           "error_kind = NULL, error_detail = NULL WHERE id = ?", (old["id"],))
                queue_id = old["id"]
            else:
                # 줄 단위 재요청은 기존 미완료 대상도 유지하되 새 ID로 진행 중 응답을 무효화한다.
                retained = {}
                if old:
                    retained = {r["line_id"]: r["text"] for r in db.execute(
                        "SELECT * FROM translation_targets WHERE queue_id = ?", (old["id"],))}
                retained.update({line_id: None for line_id in selected})
                db.execute("DELETE FROM translation_queue WHERE video_id = ?", (video_id,))
                queue_id = uuid4().hex
                db.execute("INSERT INTO translation_queue(id, video_id, transcript_id, requested_at) VALUES (?, ?, ?, ?)",
                           (queue_id, video_id, transcript.id, self._clock().isoformat()))
                db.executemany("INSERT INTO translation_targets VALUES (?, ?, ?)",
                               [(queue_id, line_id, text) for line_id, text in retained.items()])
            return self._entry(db, db.execute("SELECT * FROM translation_queue WHERE id = ?", (queue_id,)).fetchone())

    @staticmethod
    def _entry(db, row):
        counts = db.execute("SELECT COUNT(text), COUNT(*) FROM translation_targets WHERE queue_id = ?",
                            (row["id"],)).fetchone()
        error = TranslationError(row["error_kind"], row["error_detail"]) if row["error_kind"] else None
        return TranslationQueueEntry(row["id"], row["video_id"], row["state"], counts[0], counts[1],
                                     datetime.fromisoformat(row["retry_at"]) if row["retry_at"] else None,
                                     str(error) if error else None, row["error_detail"])

    def queue(self):
        with self._connect() as db:
            db.execute("BEGIN")
            return tuple(self._entry(db, row) for row in db.execute(
                "SELECT * FROM translation_queue ORDER BY requested_at, rowid"))

    def translation(self, video_id):
        with self._connect() as db:
            db.execute("BEGIN")
            transcript = db.execute("SELECT id FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
            if transcript is None:
                return None
            rows = db.execute("SELECT t.*, tr.text AS translated FROM transcript_lines t "
                              "LEFT JOIN translation_lines tr ON tr.line_id = t.id "
                              "WHERE transcript_id = ? ORDER BY ordinal", (transcript[0],)).fetchall()
            if not rows or any(row["translated"] is None for row in rows):
                return None
            return Translation(video_id, transcript[0], tuple(
                TranscriptLine(r["id"], r["start"], r["end"], r["translated"]) for r in rows))

    def stop_processing(self):
        self._cancellation.set()

    def ready(self):
        blocked = {e.video_id for e in self._subtitles.queue() if e.state == "queued"}
        now = self._clock()
        return next((e for e in self.queue() if e.video_id not in blocked and
                     (e.state == "queued" or (e.state == "held" and e.retry_at <= now))), None)

    def process_next(self):
        """한 번에 한 묶음. 성공한 묶음은 저장하고 전체/선택 줄 교체는 마지막에 원자적으로 한다."""
        if self._cancellation.is_set() or not self._processing.acquire(blocking=False):
            return None
        try:
            self.enqueue_eligible()
            pending = self.ready()
            if pending is None:
                return None
            transcript = self._subtitles.transcript(pending.video_id)
            if transcript is None:
                return None
            with self._connect() as db:
                ids = {r[0] for r in db.execute("SELECT line_id FROM translation_targets "
                                               "WHERE queue_id = ? AND text IS NULL", (pending.id,))}
            lines = tuple(line for line in transcript.lines if line.id in ids)[:self._batch_size]
            if not lines:
                return None  # 요청 또는 원어 세대가 읽는 도중 교체됐다.
            try:
                if self._translator is None:
                    raise TranslationError("missing_cli", "번역 어댑터가 설정되지 않았습니다.")
                cli = self.cli
                for attempt in range(self._format_attempts):
                    if self._cancellation.is_set():
                        raise TranslationCancelled
                    try:
                        result = validate_translation(lines, self._translator.translate(
                            lines, transcript.spoken_language, cli=cli, cancellation=self._cancellation))
                        break
                    except TranslationError as error:
                        if error.kind != "format" or attempt + 1 == self._format_attempts:
                            raise
                if self._cancellation.is_set():
                    raise TranslationCancelled
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    current = db.execute("SELECT * FROM translation_queue WHERE id = ?", (pending.id,)).fetchone()
                    # 재생성 중이거나 요청/원어 세대가 바뀌면 진행 중의 낡은 응답을 버린다.
                    if (current is None or current["transcript_id"] != transcript.id or db.execute(
                            "SELECT 1 FROM subtitle_queue WHERE video_id = ? AND state = 'queued'",
                            (pending.video_id,)).fetchone()):
                        return None
                    if self._cancellation.is_set():
                        raise TranslationCancelled
                    db.executemany("UPDATE translation_targets SET text = ? WHERE queue_id = ? AND line_id = ?",
                                   [(line.text, pending.id, line.id) for line in result])
                    done = not db.execute("SELECT 1 FROM translation_targets WHERE queue_id = ? AND text IS NULL",
                                          (pending.id,)).fetchone()
                    if done:
                        db.execute("DELETE FROM translation_lines WHERE line_id IN "
                                   "(SELECT line_id FROM translation_targets WHERE queue_id = ?)", (pending.id,))
                        db.execute("INSERT INTO translation_lines SELECT line_id, text FROM translation_targets "
                                   "WHERE queue_id = ?", (pending.id,))
                    db.execute("UPDATE translation_queue SET state = ?, retry_at = NULL, error_kind = NULL, "
                               "error_detail = NULL WHERE id = ?", ("completed" if done else "queued", pending.id))
                    entry = self._entry(db, db.execute("SELECT * FROM translation_queue WHERE id = ?", (pending.id,)).fetchone())
                    if done:
                        db.execute("DELETE FROM translation_queue WHERE id = ?", (pending.id,))
                    return entry
            except TranslationCancelled:
                return pending
            except Exception as error:
                failure = error if isinstance(error, TranslationError) else TranslationError("other", str(error))
                held = failure.kind == "usage_limit"
                retry_at = self._clock() + self._retry_delay if held else None
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("UPDATE translation_queue SET state = ?, retry_at = ?, error_kind = ?, error_detail = ? "
                               "WHERE id = ?", ("held" if held else "failed", retry_at.isoformat() if retry_at else None,
                                                failure.kind, failure.detail, pending.id))
                    row = db.execute("SELECT * FROM translation_queue WHERE id = ?", (pending.id,)).fetchone()
                    return self._entry(db, row) if row else None
        finally:
            self._processing.release()


class SubtitleSelection:
    """재생마다 원어로 시작하며 없는 번역으로 전환하지 않는다."""
    def __init__(self, translations):
        self._translations = translations
        self.video_id = None
        self.translated = False

    def playback_started(self, session, position):
        self.video_id, self.translated = session.video_id, False

    def playback_position(self, session, position, seeked):
        pass

    def playback_ended(self, session, position):
        self.video_id, self.translated = None, False

    def toggle(self):
        if self.video_id is None:
            return False, "재생 중인 영상이 없습니다."
        if not self.translated and self._translations.translation(self.video_id) is None:
            return False, "번역 자막이 아직 없습니다. 원어 자막을 유지합니다."
        self.translated = not self.translated
        return True, "번역 자막" if self.translated else "원어 자막"
