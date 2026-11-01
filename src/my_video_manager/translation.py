"""번역 자막, 묶음 진행 저장, 보류와 재시도. 외부 호출 중 DB 잠금은 없다."""

import json
from dataclasses import dataclass
from contextlib import nullcontext
from datetime import datetime, timedelta
from threading import Event, Lock
from typing import Protocol
from uuid import uuid4

from .translation_source import TRANSCRIPT, TranslationSources
from .translation_schema import create_source_tables, install_transcript_references
from .subtitles import TranscriptLine, TranscriptSummary
from .translation_kind import translation_task, TranslationTask
from .translation_models import DEFAULT_PROVIDER, provider
from .translation_glossary import GlossaryStore, GlossaryEntry


CONTEXT_LINES = 10
CONTEXT_LIMIT = 100
MIN_BATCH_SIZE = 10
RECOVERY_SUCCESSES = 3


class TranslationCancelled(Exception):
    """진행한 묶음을 보존하고 다음 실행에서 이어 한다."""


class TranslationError(RuntimeError):
    def __init__(self, kind: str, detail: str, *, shrinkable=True):
        self.shrinkable = shrinkable
        self.kind, self.detail = kind, detail
        super().__init__({
            "usage_limit": "구독 사용량 한도로 보류했습니다. 잠시 뒤 자동으로 재시도합니다.",
            "usage_limit_repeated": "사용량 한도가 3회 반복되어 자동 재시도를 멈췄습니다. 한도 확인 후 직접 재시도하세요.",
            "authentication": "CLI 로그인이 필요합니다.",
            "missing_cli": "CLI가 없습니다. 선택한 CLI를 설치하거나 설정을 바꾸세요.",
            "configuration": "모델을 쓸 수 없음: 모델 이름 또는 추론 강도를 확인하세요.",
            "missing_key": "OpenCode Go 키가 등록되지 않았습니다.",
            "connection": "OpenCode Go에 연결하지 못했습니다.",
            "response_timeout": "OpenCode Go 응답 시간이 초과되었습니다.",
            "key_storage": "OpenCode Go 저장된 키를 읽지 못했습니다.",
            "request_rejected": "OpenCode Go가 요청을 거부했습니다.",
            "format": "응답의 줄 ID 또는 형식이 올바르지 않습니다.",
            "timeout": "CLI 응답 시간이 초과되었습니다.",
        }.get(kind, "자막 처리에 실패했습니다. 자세한 내용을 확인하세요."))


@dataclass(frozen=True)
class TranslatedLine:
    id: str  # 원어 자막 줄 ID
    text: str


@dataclass(frozen=True)
class ContextLine:
    id: str
    text: str
    translation: str | None = None


@dataclass(frozen=True)
class TranslationResponse:
    lines: tuple[TranslatedLine, ...]
    glossary: tuple[GlossaryEntry, ...] = ()

    def __iter__(self):
        return iter(self.lines)

    def __getitem__(self, index):
        return self.lines[index]

    def __len__(self):
        return len(self.lines)


@dataclass
class BatchProgress:
    size: int
    successes: int = 0

    def shrink(self, actual_size):
        self.successes = 0
        if actual_size <= MIN_BATCH_SIZE:
            return False
        self.size = max(MIN_BATCH_SIZE, actual_size // 2)
        return True

    def succeeded(self, ceiling):
        self.successes += 1
        if self.successes >= RECOVERY_SUCCESSES:
            self.size = min(ceiling, self.size * 2)
            self.successes = 0


class Translator(Protocol):
    def translate(self, lines: tuple[TranscriptLine, ...], spoken_language: str, *,
                  cli: str, cancellation: Event, model: str = "", effort: str = "",
                  context: tuple[ContextLine, ...] = (), glossary: tuple[GlossaryEntry, ...] = ()) -> TranslationResponse: ...


def validate_translation(lines, result, *, spoken_language=None) -> tuple[TranslatedLine, ...]:
    """응답 순서는 무관하지만 대상 ID와 정확히 일대일이어야 한다."""
    try:
        result = tuple(result)
        if translation_task(spoken_language).kind == 'refinement':
            originals = {line.id: line.text for line in lines}
            result = tuple(TranslatedLine(line.id, originals.get(line.id, line.text))
                           if isinstance(line.text, str) and not line.text.strip() else line
                           for line in result)
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
    source: str = TRANSCRIPT


@dataclass(frozen=True)
class TranslationSummary:
    translated_lines: int
    queue_state: str | None


def translation_skip_reason(original: TranscriptSummary) -> str | None:
    """번역·다듬기를 등록하지 않은 원어 자막의 이유. enqueue_eligible·request의 거절 조건과 같다."""
    if original.no_speech:
        return "no_speech"
    if original.has_transcript and original.spoken_language is None:
        return "unknown_language"
    return None


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
    queue_kind: str
    source: str
    notice: str = ""
    kind: str = "translation"


class Translations:
    def __init__(self, connect, clock, subtitles, settings, translator, *, batch_size=None,
                 retry_delay=timedelta(minutes=15), format_attempts=3, order=None, protected_lines=None, options=None, sources=None):
        if (batch_size is not None and batch_size < 1) or format_attempts < 1 or retry_delay.total_seconds() <= 0:
            raise ValueError("번역 묶음 크기, 재시도 횟수와 보류 시간은 양수여야 합니다.")
        self._connect, self._clock = connect, clock
        self._subtitles, self._settings, self._translator = subtitles, settings, translator
        self._batch_size, self._retry_delay, self._format_attempts = batch_size, retry_delay, format_attempts
        self._processing, self._cancellation = Lock(), Event()
        self._order = order
        self._options = options
        self._active_video = None
        self._active_cancellation = None
        self._cached_request = None
        self._cached_transcript = None
        self._activity = Lock()
        self.sources = sources or TranslationSources()
        self.sources.register(TRANSCRIPT, subtitles.transcript, queue_kind=self.sources.queue_kind(TRANSCRIPT),
                              protected_lines=protected_lines)
        self._glossaries = GlossaryStore()
        self._batch_progress = {}
        with connect() as db:
            create_source_tables(db)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS translation_cli_backoff (
                    cli TEXT PRIMARY KEY,
                    retry_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS translation_limit_attempts (
                    queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
                    cli TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    PRIMARY KEY(queue_id, cli)
                );
                CREATE TABLE IF NOT EXISTS translation_target_providers (
                    queue_id TEXT NOT NULL,
                    line_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    PRIMARY KEY(queue_id, line_id),
                    FOREIGN KEY(queue_id, line_id) REFERENCES translation_targets(queue_id, line_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS translation_routes (
                    queue_id TEXT PRIMARY KEY REFERENCES translation_queue(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS translation_job_options (
                    queue_id TEXT PRIMARY KEY REFERENCES translation_queue(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    selections TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS translation_fallback_notices (
                    queue_id TEXT PRIMARY KEY REFERENCES translation_queue(id) ON DELETE CASCADE,
                    message TEXT NOT NULL
                );
            """)
            install_transcript_references(db)
            db.execute("UPDATE translation_queue SET state = 'queued' WHERE state = 'translating'")
        self.enqueue_eligible()  # 원어 저장 직후 강제 종료된 경우도 복구한다.

    @property
    def cli(self):
        return self._settings.get("translation.cli", DEFAULT_PROVIDER)

    def set_cli(self, cli):
        provider(cli)
        self._settings.set("translation.cli", cli)

    def enqueue_eligible(self):
        with self._connect() as db:
            # 대기 중이거나 번역이 끝난 영상의 원어 전체를 묶음마다 다시 읽지 않는다.
            ids = [row[0] for row in db.execute("""
                SELECT video_id FROM transcripts t
                WHERE t.spoken_language NOT IN ('ko', 'und')
                  AND NOT EXISTS (SELECT 1 FROM translation_queue q WHERE q.video_id = t.video_id AND q.source = ?)
                  AND NOT EXISTS (SELECT 1 FROM translation_omissions o WHERE o.transcript_id = t.id AND o.source = ?)
                  AND EXISTS (SELECT 1 FROM transcript_lines l WHERE l.transcript_id = t.id
                              AND NOT EXISTS (SELECT 1 FROM translation_lines tr WHERE tr.line_id = l.id AND tr.source = ?))
            """, (TRANSCRIPT, TRANSCRIPT, TRANSCRIPT))]
        for video_id in ids:
            self.request(video_id, automatic=True)

    def _generation_current(self, db, source, video_id, generation_id):
        if source == TRANSCRIPT:
            return db.execute("SELECT 1 FROM transcripts WHERE id=? AND video_id=?",
                              (generation_id, video_id)).fetchone() is not None
        current = self.sources.lines(source, video_id, connection=db)
        return current is not None and current.id == generation_id

    def request(self, video_id: int, line_ids=None, *, automatic=False, connection=None,
                preserve_state=False, continue_order=False, source=TRANSCRIPT):
        transcript = self.sources.lines(source, video_id, connection=connection)
        if transcript is None or not transcript.lines or transcript.spoken_language in (None, "und"):
            if automatic:
                return None
            raise ValueError("원어를 알 수 없거나 비어 있는 자막은 처리할 수 없습니다.")
        selected = set(line_ids) if line_ids is not None else {line.id for line in transcript.lines}
        if not selected or not selected <= {line.id for line in transcript.lines}:
            raise ValueError("번역할 원어 자막 줄 ID를 확인하세요.")
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            if not self._generation_current(db, source, video_id, transcript.id):
                return None  # 동시에 원어가 교체됐다. 다음 자동 등록에서 새 세대를 처리한다.
            old = db.execute("SELECT * FROM translation_queue WHERE video_id = ? AND source = ?", (video_id, source)).fetchone()
            selected -= self.sources.protected_lines(source, db)
            if not selected:
                return self._entry(db, old) if old else None
            if automatic:
                if db.execute("SELECT 1 FROM translation_omissions WHERE transcript_id = ? AND source = ? AND video_id = ?", (transcript.id, source, video_id)).fetchone():
                    return None
                if old:
                    return self._entry(db, old)
                saved = {r[0] for r in db.execute(
                    "SELECT line_id FROM translation_lines WHERE video_id = ? AND source = ?", (video_id, source))}
                selected -= saved
                if not selected:
                    return None
            else:
                db.execute("DELETE FROM translation_omissions WHERE video_id = ? AND source = ?", (video_id, source))
            if self._order:
                # 새 직접 요청은 남은 순번 행과 무관하게 뒤에 서고, 후속 단계는 받은 순번을 잇는다.
                self._order.request(db, video_id, kind=self.sources.queue_kind(source), automatic=automatic,
                                    renew=not automatic and not continue_order
                                    and (old is None or old["state"] == "failed"))
            # 명시적인 전체 재시도는 저장한 묶음을 재사용한다.
            if old and line_ids is None:
                db.execute("DELETE FROM translation_limit_attempts WHERE queue_id = ?", (old["id"],))
                db.execute("UPDATE translation_queue SET state = 'queued', retry_at = NULL, "
                           "error_kind = NULL, error_detail = NULL WHERE id = ?", (old["id"],))
                queue_id = old["id"]
                db.execute("DELETE FROM translation_routes WHERE queue_id=?", (queue_id,))
                db.execute("DELETE FROM translation_job_options WHERE queue_id=?", (queue_id,))
                db.execute("DELETE FROM translation_fallback_notices WHERE queue_id=?", (queue_id,))
            else:
                # 줄 단위 재요청은 기존 미완료 대상도 유지하되 새 ID로 진행 중 응답을 무효화한다.
                retained = {}
                provenance = []
                if old:
                    retained = {r["line_id"]: r["text"] for r in db.execute(
                        "SELECT * FROM translation_targets WHERE queue_id = ?", (old["id"],))}
                    provenance = [(r['line_id'], r['provider']) for r in db.execute(
                        "SELECT line_id, provider FROM translation_target_providers WHERE queue_id = ?", (old['id'],))
                        if r['line_id'] not in selected]
                retained.update({line_id: None for line_id in selected})
                attempts = list(db.execute("SELECT cli, attempts FROM translation_limit_attempts WHERE queue_id = ?",
                                           (old["id"],))) if old and preserve_state else []
                glossary = self._glossaries.load(db, old['id']) if old else None
                db.execute("DELETE FROM translation_queue WHERE video_id = ? AND source = ?", (video_id, source))
                queue_id = uuid4().hex
                db.execute("INSERT INTO translation_queue(id, video_id, transcript_id, requested_at, source, spoken_language) "
                           "VALUES (?, ?, ?, ?, ?, ?)",
                           (queue_id, video_id, transcript.id, self._clock().isoformat(), source, transcript.spoken_language))
                if glossary is not None:
                    self._glossaries.save(db, queue_id, glossary)
                if old and preserve_state:
                    # 새 ID를 실행하는 작업자는 아직 없다. 옛 실행 결과는 ID 검사로 버린다.
                    state = "queued" if old["state"] == "translating" else old["state"]
                    db.execute("UPDATE translation_queue SET requested_at = ?, state = ?, retry_at = ?, "
                               "error_kind = ?, error_detail = ? WHERE id = ?",
                               (old["requested_at"], state, old["retry_at"], old["error_kind"], old["error_detail"], queue_id))
                    db.executemany("INSERT INTO translation_limit_attempts VALUES (?, ?, ?)",
                                   [(queue_id, r["cli"], r["attempts"]) for r in attempts])
                db.executemany("INSERT INTO translation_targets VALUES (?, ?, ?)",
                               [(queue_id, line_id, text) for line_id, text in retained.items()])
                db.executemany("INSERT INTO translation_target_providers VALUES (?, ?, ?)",
                               [(queue_id, line_id, name) for line_id, name in provenance])
            return self._entry(db, db.execute("SELECT * FROM translation_queue WHERE id = ?", (queue_id,)).fetchone())

    def task(self, video_id, *, connection=None) -> TranslationTask:
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            row = db.execute("SELECT spoken_language FROM transcripts WHERE video_id=?", (video_id,)).fetchone()
            return translation_task(row[0] if row else None)

    def request_refinement(self, video_id):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.task(video_id, connection=db).kind != 'refinement':
                raise ValueError('한국어 원어 자막이 있는 영상을 고르세요.')
            return self.request(video_id, connection=db)

    def _existing_refinements(self, db):
        rows = db.execute("""SELECT t.video_id,
                EXISTS (SELECT 1 FROM translation_omissions o WHERE o.transcript_id=t.id AND o.source=?) AS omitted
            FROM transcripts t JOIN videos v ON v.id=t.video_id
            WHERE t.spoken_language='ko' AND NOT v.excluded
              AND NOT EXISTS (SELECT 1 FROM translation_queue q WHERE q.video_id=t.video_id AND q.source=?)
              AND EXISTS (SELECT 1 FROM transcript_lines l WHERE l.transcript_id=t.id
                          AND NOT EXISTS (SELECT 1 FROM translation_lines tr WHERE tr.line_id=l.id AND tr.source=?))
              AND NOT EXISTS (SELECT 1 FROM subtitle_queue s WHERE s.video_id=t.video_id AND s.kind=?
                              AND s.state IN ('queued', 'transcribing'))""", (TRANSCRIPT, TRANSCRIPT, TRANSCRIPT, self.sources.queue_kind(TRANSCRIPT))).fetchall()
        return [r['video_id'] for r in rows if not r['omitted']], sum(r['omitted'] for r in rows)

    def existing_refinement_candidates(self):
        with self._connect() as db:
            ids, skipped = self._existing_refinements(db)
        return len(ids), skipped

    def request_existing_refinements(self):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            ids, skipped = self._existing_refinements(db)
            count = 0
            for video_id in ids:
                if self._order:
                    self._order.finish(db, video_id)
                count += self.request(video_id, automatic=True, connection=db) is not None
        return count, skipped

    def finish_ready(self, db, video_id, *, source=TRANSCRIPT):
        """검수/구간 삭제가 마지막 미완료 대상을 없앤 경우도 저장한 묶음을 확정한다."""
        row = db.execute("SELECT id FROM translation_queue WHERE video_id = ? AND source = ?", (video_id, source)).fetchone()
        if row is None or db.execute("SELECT 1 FROM translation_targets WHERE queue_id = ? AND text IS NULL",
                                     (row[0],)).fetchone():
            return
        protected = self.sources.protected_lines(source, db)
        targets = [(r["line_id"], r["text"]) for r in db.execute(
            "SELECT line_id, text FROM translation_targets WHERE queue_id = ?", (row[0],))
                   if r["line_id"] not in protected]
        db.executemany("DELETE FROM translation_lines WHERE video_id=? AND source=? AND line_id=?",
                       [(video_id, source, id_) for id_, _ in targets])
        db.executemany("INSERT INTO translation_lines VALUES (?, ?, ?, ?)",
                       [(id_, text, video_id, source) for id_, text in targets])
        self._commit_providers(db, row[0])
        db.execute("DELETE FROM translation_queue WHERE id = ?", (row[0],))
        if self._order:
            self._order.finish(db, video_id, kind=self.sources.queue_kind(source))

    def _entry(self, db, row):
        counts = db.execute("SELECT COUNT(text), COUNT(*) FROM translation_targets WHERE queue_id = ?",
                            (row["id"],)).fetchone()
        error = TranslationError(row["error_kind"], row["error_detail"]) if row["error_kind"] else None
        if error and row['error_kind'] != 'usage_limit_repeated' and row['error_detail'] and row['error_detail'].startswith('OpenCode Go'):
            error = row['error_detail']
        notice = db.execute("SELECT message FROM translation_fallback_notices WHERE queue_id=?", (row["id"],)).fetchone()
        language = row["spoken_language"]
        task = translation_task(language)
        return TranslationQueueEntry(row["id"], row["video_id"], row["state"], counts[0], counts[1],
                                     datetime.fromisoformat(row["retry_at"]) if row["retry_at"] else None,
                                     str(error) if error else None, row["error_detail"],
                                     queue_kind=self.sources.queue_kind(row["source"]), source=row["source"],
                                     notice=notice[0] if notice else "", kind=task.kind)

    def queue(self):
        with self._connect() as db:
            db.execute("BEGIN")
            entries = tuple(self._entry(db, row) for row in db.execute(
                "SELECT * FROM translation_queue ORDER BY requested_at, rowid"))
        return self._order.sort(entries) if self._order else entries

    def remove(self, video_id, *, source=TRANSCRIPT):
        with self._activity:
            with self._connect() as db:
                # 출처 조회가 읽기 트랜잭션을 열기 전에 쓰기를 예약한다.
                # 취소된 받아쓰기의 정리 쓰기와 읽기→쓰기 승격이 교착하지 않게 한다.
                db.execute("BEGIN IMMEDIATE")
                original = self.sources.lines(source, video_id, connection=db)
                if original:
                    db.execute("INSERT OR REPLACE INTO translation_omissions VALUES (?, ?, ?)",
                               (original.id, video_id, source))
                db.execute("DELETE FROM translation_queue WHERE video_id=? AND source=?", (video_id, source))
            if self._active_video == (video_id, source) and self._active_cancellation:
                self._active_cancellation.set()

    def resume_processing(self):
        self._cancellation.clear()

    def translation(self, video_id, *, source=TRANSCRIPT):
        with self._connect() as db:
            db.execute("BEGIN")
            original = self.sources.lines(source, video_id, connection=db)
            if original is None or not original.lines:
                return None
            saved = dict(db.execute("SELECT line_id, text FROM translation_lines WHERE video_id=? AND source=?",
                                    (video_id, source)))
            if any(line.id not in saved for line in original.lines):
                return None
            return Translation(video_id, original.id, tuple(
                TranscriptLine(line.id, line.start, line.end, saved[line.id]) for line in original.lines), source)

    def available(self, video_id):
        with self._connect() as db:
            return bool(db.execute("""SELECT 1 FROM transcripts t WHERE t.video_id=?
                AND EXISTS (SELECT 1 FROM transcript_lines l WHERE l.transcript_id=t.id)
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l WHERE l.transcript_id=t.id
                    AND NOT EXISTS (SELECT 1 FROM translation_lines tr WHERE tr.line_id=l.id AND tr.source=?))""",
                (video_id, TRANSCRIPT)).fetchone())

    def summary(self, video_id: int, *, connection=None) -> TranslationSummary:
        """확정 번역과 현재 요청의 저장된 부분 번역을 선택 영상 범위에서 센다."""
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            if not db.in_transaction:
                db.execute("BEGIN")
            transcript = db.execute("SELECT id FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
            queue = db.execute("SELECT id, state FROM translation_queue WHERE video_id = ? AND source = ?", (video_id, TRANSCRIPT)).fetchone()
            count = 0
            if transcript:
                count = db.execute("""
                    SELECT COUNT(*) FROM transcript_lines l
                    LEFT JOIN translation_lines tr ON tr.line_id = l.id AND tr.source = ?
                    LEFT JOIN translation_targets target ON target.queue_id = ? AND target.line_id = l.id
                    WHERE l.transcript_id = ? AND COALESCE(tr.text, target.text) IS NOT NULL
                """, (TRANSCRIPT, queue["id"] if queue else None, transcript[0])).fetchone()[0]
            return TranslationSummary(count, queue["state"] if queue else None)

    def stop_processing(self):
        self._cancellation.set()
        with self._activity:
            if self._active_cancellation:
                self._active_cancellation.set()

    def line_providers(self, video_id, *, source=TRANSCRIPT):
        with self._connect() as db:
            db.execute("BEGIN")
            original = self.sources.lines(source, video_id, connection=db)
            if original is None:
                return {}
            saved = dict(db.execute("SELECT line_id, provider FROM translation_line_providers "
                                    "WHERE video_id=? AND source=?", (video_id, source)))
            committed = {r[0] for r in db.execute("SELECT line_id FROM translation_lines "
                                                "WHERE video_id=? AND source=?", (video_id, source))}
            pending = dict(db.execute("SELECT p.line_id, p.provider FROM translation_target_providers p "
                                     "JOIN translation_queue q ON q.id=p.queue_id WHERE q.video_id=? AND q.source=?",
                                     (video_id, source)))
            return {line.id: (saved if line.id in committed else pending).get(line.id) for line in original.lines}

    @staticmethod
    def _commit_providers(db, queue_id):
        row = db.execute("SELECT video_id, source FROM translation_queue WHERE id=?", (queue_id,)).fetchone()
        db.execute("DELETE FROM translation_line_providers WHERE video_id=? AND source=? AND line_id IN "
                   "(SELECT line_id FROM translation_targets WHERE queue_id=?)", (*row, queue_id))
        db.execute("INSERT INTO translation_line_providers SELECT line_id, provider, ?, ? "
                   "FROM translation_target_providers WHERE queue_id=?", (*row, queue_id))

    def _route(self, db, queue_id, cli):
        route = db.execute("SELECT provider FROM translation_routes WHERE queue_id=?", (queue_id,)).fetchone()
        if route:
            return route[0]
        job = db.execute("SELECT provider FROM translation_job_options WHERE queue_id=?", (queue_id,)).fetchone()
        return job[0] if job else cli

    def _start_job(self, db, queue_id, cli):
        if db.execute("SELECT 1 FROM translation_job_options WHERE queue_id=?", (queue_id,)).fetchone():
            return
        selections = {p: self._options.selection(p) for p in ('codex', 'claude', 'opencode_go')} if self._options else {}
        db.execute("INSERT OR IGNORE INTO translation_job_options SELECT id, ?, ? FROM translation_queue WHERE id=?",
                   (cli, json.dumps(selections), queue_id))

    @staticmethod
    def _fallback(db, queue_id, cli, kind):
        reason = {'usage_limit': '사용량 한도', 'format': '형식 오류 재시도 소진',
                  'authentication': 'CLI 로그인 필요', 'missing_cli': 'CLI 없음',
                  'timeout': 'CLI 응답 시간 초과'}.get(kind, 'CLI 오류')
        language = db.execute("SELECT spoken_language FROM translation_queue WHERE id=?", (queue_id,)).fetchone()[0]
        message = f"{provider(cli).label} {reason} → OpenCode Go로 이어서 {translation_task(language).label}"
        db.execute("INSERT OR REPLACE INTO translation_routes VALUES (?, ?)", (queue_id, 'opencode_go'))
        db.execute("INSERT OR REPLACE INTO translation_fallback_notices VALUES (?, ?)", (queue_id, message))

    def _backoff(self, db, cli):
        row = db.execute("SELECT retry_at FROM translation_cli_backoff WHERE cli=?", (cli,)).fetchone()
        return datetime.fromisoformat(row[0]) if row and datetime.fromisoformat(row[0]) > self._clock() else None

    def _can_fallback(self, cli):
        return cli in ('codex', 'claude') and self._options is not None and self._options.fallback_enabled()

    def ready(self, *, cli=None):
        cli = self.cli if cli is None else cli
        blocked = {(e.video_id, e.queue_kind) for e in self._subtitles.queue()
                   if e.state in ("queued", "transcribing")}
        entries = sorted(self.queue(), key=lambda e: e.state == "held")
        with self._connect() as db:
            routes = dict(db.execute('SELECT queue_id, provider FROM translation_job_options'))
            routes.update(db.execute('SELECT queue_id, provider FROM translation_routes'))
            backoffs = {r[0] for r in db.execute('SELECT cli, retry_at FROM translation_cli_backoff')
                        if datetime.fromisoformat(r[1]) > self._clock()}
        for entry in entries:
            if (entry.video_id, entry.queue_kind) in blocked or entry.state not in ('queued', 'held'):
                continue
            route = routes.get(entry.id, cli)
            if route in backoffs and not (self._can_fallback(route) and 'opencode_go' not in backoffs):
                continue
            return entry
        return None

    def _translate_batch(self, remaining, language, cli, cancellation, queue_id, transcript, glossary, source):
        with self._connect() as db:
            row = db.execute('SELECT selections FROM translation_job_options WHERE queue_id=?', (queue_id,)).fetchone()
        if row is None:
            raise TranslationCancelled
        selected = json.loads(row[0]).get(cli, {})
        if cli == 'opencode_go':
            adapter = self._options.adapter(queue_id, selection=selected)
            kwargs = {}
        else:
            adapter = self._translator
            kwargs = dict(selected)
            kwargs.pop('provider', None)
        if adapter is None:
            raise TranslationError('missing_cli', '번역 어댑터가 설정되지 않았습니다.')
        ceiling = self._batch_size or provider(cli).batch_size
        progress = self._batch_progress.setdefault((queue_id, cli), BatchProgress(ceiling))
        positions = {line.id: i for i, line in enumerate(transcript.lines)}
        attempt = 0
        while True:
            if cancellation.is_set():
                raise TranslationCancelled
            with self._connect() as db:
                current = db.execute("""SELECT 1 FROM translation_queue q WHERE q.id=?
                    AND NOT EXISTS (SELECT 1 FROM subtitle_queue s WHERE s.video_id=q.video_id AND s.kind=?
                                    AND s.state IN ('queued', 'transcribing'))""", (queue_id, self.sources.queue_kind(source))).fetchone()
            if not current:
                raise TranslationCancelled
            lines = remaining[:progress.size]
            # 떨어진 각 구간에 적어도 가장 가까운 앞 줄 하나를 줄 수 있게
            # 맥락 예산을 넘는 구간은 다음 호출로 넘긴다. 연속 묶음 크기는 유지한다.
            groups = 0
            previous = -1
            for offset, line in enumerate(lines):
                index = positions[line.id]
                if index > previous + 1:
                    groups += 1
                if groups > CONTEXT_LIMIT:
                    lines = lines[:offset]
                    break
                previous = index
            with self._connect() as db:
                context = self._context(db, transcript, lines, queue_id, source)
            try:
                response = adapter.translate(lines, language, cli=cli, cancellation=cancellation,
                                             context=context, glossary=glossary.entries, **kwargs)
                return TranslationResponse(validate_translation(lines, response, spoken_language=language),
                                           response.glossary if isinstance(response, TranslationResponse) else ())
            except TranslationError as error:
                progress.successes = 0
                if error.kind not in ('format', 'response_timeout'):
                    raise
                if cancellation.is_set():
                    raise TranslationCancelled
                if error.shrinkable and progress.shrink(len(lines)):
                    attempt = 0
                    continue
                if error.kind == 'response_timeout':
                    raise
                attempt += 1
                if attempt >= self._format_attempts:
                    raise
            except TranslationCancelled:
                raise
            except Exception as error:
                progress.successes = 0
                raise TranslationError('other', str(error)) from error

    def _context(self, db, transcript, targets, queue_id, source):
        target_ids = {line.id for line in targets}
        indices = [i for i, line in enumerate(transcript.lines) if line.id in target_ids]
        # 각 대상의 가까운 앞 줄부터 공평하게 모으고 원어 순서로 보낸다.
        selected = set()
        for distance in range(1, CONTEXT_LINES + 1):
            for index in indices:
                previous = index - distance
                if previous >= 0 and transcript.lines[previous].id not in target_ids:
                    selected.add(previous)
                if len(selected) >= CONTEXT_LIMIT:
                    break
            if len(selected) >= CONTEXT_LIMIT:
                break
        preceding = [transcript.lines[i] for i in sorted(selected)]
        if not preceding:
            return ()
        # 미번역 대상은 옛 확정 번역보다 우선한다. 수정 후 낡은 번역을 맥락에 넣지 않는다.
        marks = ','.join('?' for _ in preceding)
        ids = tuple(line.id for line in preceding)
        translated = dict(db.execute(
            f"SELECT line_id, text FROM translation_lines WHERE video_id=? AND source=? AND line_id IN ({marks})",
            (transcript.video_id, source, *ids)))
        translated.update(db.execute(
            f"SELECT line_id, text FROM translation_targets WHERE queue_id=? AND line_id IN ({marks})",
            (queue_id, *ids)))
        return tuple(ContextLine(line.id, line.text, translated.get(line.id)) for line in preceding)

    def _prune_progress(self, db):
        live = {r[0] for r in db.execute('SELECT id FROM translation_queue')}
        self._batch_progress = {key: value for key, value in self._batch_progress.items() if key[0] in live}

    def process_next(self):
        """한 번에 한 묶음. 성공한 묶음은 저장하고 전체/선택 줄 교체는 마지막에 원자적으로 한다."""
        if self._cancellation.is_set() or not self._processing.acquire(blocking=False):
            return None
        try:
            self.enqueue_eligible()
            cli = self.cli  # 조회와 호출은 같은 CLI를 사용한다. 실행 중 설정 변경도 분리한다.
            pending = self.ready(cli=cli)
            if pending is None:
                return None
            # 줄 수정·구간 교체는 요청 ID를 바꾸므로 다음 묶음은 새 원어를 읽는다.
            # 캐시는 현재 요청 하나만 보관하며 다른 영상으로 넘어가면 교체한다.
            if self._cached_request != pending.id:
                self._cached_transcript = self.sources.lines(pending.source, pending.video_id)
                self._cached_request = pending.id
            transcript = self._cached_transcript
            if transcript is None:
                return None
            with self._connect() as db:
                self._prune_progress(db)
                ids = {r[0] for r in db.execute("SELECT line_id FROM translation_targets "
                                               "WHERE queue_id = ? AND text IS NULL", (pending.id,))}
                self._start_job(db, pending.id, cli)
                cli = self._route(db, pending.id, cli)
                if self._backoff(db, cli) and self._can_fallback(cli):
                    self._fallback(db, pending.id, cli, 'usage_limit')
                    cli = 'opencode_go'
            lines = tuple(line for line in transcript.lines if line.id in ids)
            if not lines:
                return None  # 요청 또는 원어 세대가 읽는 도중 교체됐다.
            with self._connect() as db:
                glossary = self._glossaries.load(db, pending.id)
            with self._activity:
                with self._connect() as db:
                    if not db.execute("UPDATE translation_queue SET state = 'translating' WHERE id = ?", (pending.id,)).rowcount:
                        return None
                self._active_video = (pending.video_id, pending.source)
                cancellation = self._active_cancellation = Event()
                if self._cancellation.is_set():
                    cancellation.set()
            try:
                try:
                    result = self._translate_batch(lines, transcript.spoken_language, cli, cancellation,
                                                   pending.id, transcript, glossary, pending.source)
                except TranslationError as error:
                    if cancellation.is_set():
                        raise TranslationCancelled
                    if error.kind not in ('usage_limit', 'other', 'authentication', 'missing_cli', 'timeout', 'format') or not self._can_fallback(cli):
                        raise
                    with self._connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        if error.kind == 'usage_limit':
                            retry = getattr(error, 'retry_at', None) or self._clock() + self._retry_delay
                            db.execute('INSERT OR REPLACE INTO translation_cli_backoff VALUES (?, ?)', (cli, retry.isoformat()))
                        current = db.execute('SELECT 1 FROM translation_queue WHERE id=?', (pending.id,)).fetchone()
                        if current:
                            self._fallback(db, pending.id, cli, error.kind)
                        backoff = self._backoff(db, 'opencode_go')
                    if not current:
                        raise TranslationCancelled
                    cli = 'opencode_go'
                    if backoff:
                        from .opencode_go import OpenCodeGoError
                        raise OpenCodeGoError('usage_limit', retry_at=backoff)
                    result = self._translate_batch(lines, transcript.spoken_language, cli, cancellation,
                                                   pending.id, transcript, glossary, pending.source)
                if cancellation.is_set():
                    raise TranslationCancelled
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    current = db.execute("SELECT * FROM translation_queue WHERE id = ?", (pending.id,)).fetchone()
                    # 재생성 중이거나 요청/원어 세대가 바뀌면 진행 중의 낡은 응답을 버린다.
                    if (current is None or current["transcript_id"] != transcript.id
                            or not self._generation_current(db, pending.source, pending.video_id, transcript.id) or db.execute(
                            "SELECT 1 FROM subtitle_queue WHERE video_id = ? AND kind = ? AND state IN ('queued', 'transcribing')",
                            (pending.video_id, pending.queue_kind)).fetchone()):
                        return None
                    if self._cancellation.is_set():
                        raise TranslationCancelled
                    db.execute("DELETE FROM translation_limit_attempts WHERE queue_id = ? AND cli = ?",
                               (pending.id, cli))
                    db.executemany("UPDATE translation_targets SET text = ? WHERE queue_id = ? AND line_id = ?",
                                   [(line.text, pending.id, line.id) for line in result])
                    db.executemany("INSERT OR REPLACE INTO translation_target_providers "
                                   "SELECT queue_id, line_id, ? FROM translation_targets WHERE queue_id=? AND line_id=?",
                                   [(cli, pending.id, line.id) for line in result])
                    self._glossaries.save(db, pending.id, glossary.updated(lines[:len(result)], result.glossary))
                    done = not db.execute("SELECT 1 FROM translation_targets WHERE queue_id = ? AND text IS NULL",
                                          (pending.id,)).fetchone()
                    if done:
                        db.execute("DELETE FROM translation_lines WHERE video_id=? AND source=? AND line_id IN "
                                   "(SELECT line_id FROM translation_targets WHERE queue_id=?)",
                                   (pending.video_id, pending.source, pending.id))
                        db.execute("INSERT INTO translation_lines SELECT line_id, text, ?, ? FROM translation_targets "
                                   "WHERE queue_id=?", (pending.video_id, pending.source, pending.id))
                    db.execute("UPDATE translation_queue SET state = ?, retry_at = NULL, error_kind = NULL, "
                               "error_detail = NULL WHERE id = ?", ("completed" if done else "queued", pending.id))
                    entry = self._entry(db, db.execute("SELECT * FROM translation_queue WHERE id = ?", (pending.id,)).fetchone())
                    if done:
                        self._commit_providers(db, pending.id)
                        db.execute("DELETE FROM translation_queue WHERE id = ?", (pending.id,))
                        if self._order:
                            self._order.finish(db, pending.video_id, kind=pending.queue_kind)
                self._batch_progress[(pending.id, cli)].succeeded(self._batch_size or provider(cli).batch_size)
                with self._connect() as db:
                    self._prune_progress(db)
                return entry
            except TranslationCancelled:
                with self._connect() as db:
                    db.execute("UPDATE translation_queue SET state = ? WHERE id = ? AND state = 'translating'",
                               (pending.state, pending.id))
                return pending
            except Exception as error:
                failure = error if isinstance(error, TranslationError) else TranslationError("other", str(error))
                held = failure.kind == "usage_limit"
                retry_at = (getattr(failure, "retry_at", None) or self._clock() + self._retry_delay) if held else None
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if held:
                        # 원어 세대/요청이 교체됐어도 실제로 받은 계정 한도는 유지한다.
                        # 옛 요청의 응답은 새 요청 상태·횟수를 바꾸지 않는다. ID가 같은 요청만 센다.
                        db.execute("INSERT INTO translation_cli_backoff VALUES (?, ?) "
                                   "ON CONFLICT(cli) DO UPDATE SET retry_at = excluded.retry_at",
                                   (cli, retry_at.isoformat()))
                        if db.execute("SELECT 1 FROM translation_queue WHERE id = ?", (pending.id,)).fetchone():
                            db.execute("INSERT INTO translation_limit_attempts VALUES (?, ?, 1) "
                                       "ON CONFLICT(queue_id, cli) DO UPDATE SET attempts = attempts + 1",
                                       (pending.id, cli))
                            attempts = db.execute("SELECT attempts FROM translation_limit_attempts "
                                                  "WHERE queue_id = ? AND cli = ?", (pending.id, cli)).fetchone()[0]
                            if attempts >= 3:
                                failure = TranslationError("usage_limit_repeated", failure.detail)
                                held, retry_at = False, None
                    db.execute("UPDATE translation_queue SET state = ?, retry_at = ?, error_kind = ?, error_detail = ? "
                               "WHERE id = ?", ("held" if held else "failed", retry_at.isoformat() if retry_at else None,
                                                failure.kind, failure.detail, pending.id))
                    row = db.execute("SELECT * FROM translation_queue WHERE id = ?", (pending.id,)).fetchone()
                    return self._entry(db, row) if row else None
        finally:
            with self._activity:
                self._active_video = self._active_cancellation = None
            if 'pending' in locals() and pending:
                with self._connect() as db:
                    db.execute("UPDATE translation_queue SET state = ? WHERE id = ? AND state = 'translating'",
                               (pending.state, pending.id))
            self._processing.release()


class SubtitleSelection:
    """외국어는 원어, 한국어는 다듬은 자막을 기본으로 하며 직접 선택을 유지한다."""
    def __init__(self, translations):
        self._translations = translations
        self.video_id = None
        self.translated = False
        self.chosen = False

    def playback_started(self, session, position):
        self.video_id, self.translated = session.video_id, False
        self.chosen = False
        self.select_default()

    def playback_position(self, session, position, seeked):
        pass

    def playback_ended(self, session, position):
        self.video_id, self.translated = None, False

    def select_default(self):
        if (self.video_id is not None and not self.chosen and not self.translated
                and self._translations.task(self.video_id).kind == 'refinement'
                and self._translations.available(self.video_id)):
            self.translated = True

    def toggle(self):
        if self.video_id is None:
            return False, "재생 중인 영상이 없습니다."
        task = self._translations.task(self.video_id)
        if not self.translated and self._translations.translation(self.video_id) is None:
            return False, f"{task.subtitle_label}이 아직 없습니다. 원어 자막을 유지합니다."
        self.chosen = True
        self.translated = not self.translated
        return True, task.subtitle_label if self.translated else "원어 자막"
