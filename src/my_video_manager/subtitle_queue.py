"""자동 자막 규칙, 처리 순서와 영상별 대기열 표시 정책."""

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
import re
from threading import RLock
from typing import NamedTuple

from .onscreen_subtitles import NO_TEXT_NOTICE
from .subtitles import normalize_spoken_language
from .translation_kind import translation_task
from .subtitle_queue_kind import QUEUE_KIND_LABELS, ONSCREEN_SUBTITLE, TRANSCRIPTION, queue_task_key
from .translation_source import ONSCREEN, TRANSCRIPT, TranslationSources


@dataclass(frozen=True)
class AutoSubtitleRule:
    id: int
    folder: Path | None
    tag_id: int | None
    spoken_language: str | None


@dataclass(frozen=True)
class SubtitleQueueItem:
    video_id: int
    title: str
    state: str
    progress: float
    error: str | None
    task_label: str
    queue_kind: str = TRANSCRIPTION


NO_SPEECH_NOTICE = "말소리를 찾지 못했습니다."


class SubtitleQueueCompletion(NamedTuple):
    """이번 처리의 결과 수. 말소리 없음과 읽은 글자 없음은 완료와 따로 센다."""
    completed: int
    failed: int
    no_speech: int
    no_text: int = 0


@dataclass(frozen=True)
class SubtitleRetrySkipped:
    video_id: int
    reason: str
    queue_kind: str = TRANSCRIPTION


@dataclass(frozen=True)
class SubtitleRetryResult:
    retried: int
    skipped: tuple[SubtitleRetrySkipped, ...]

    @property
    def skipped_count(self):
        return len(self.skipped)


def subtitle_order_key(video_id, positions, kind=TRANSCRIPTION):
    """옛 항목은 직접 요청 등급의 마지막에서 기존 상대 순서를 유지한다."""
    return positions.get((video_id, kind), (0, 0, float("inf")))


def _display_error_detail(detail):
    """CLI 진단의 원인은 남기되 인증 값과 로컬 절대 경로는 표시하지 않는다."""
    if not detail:
        return None
    detail = re.sub(r'(?i)\bBearer\s+[^\s\"\'<>;,]+', 'Bearer [가림]', detail)
    detail = re.sub(
        r'''(?ix)(\b[\w-]*(?:key|token|secret|password)\b["']?\s*[:=]\s*)
            (?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)''',
        r'\1[가림]', detail)
    detail = re.sub(r'\bsk-[\w-]+', '[가림]', detail)
    # 따옴표로 둘러싼 경로는 공백을 포함한 전체를 먼저 가린다.
    detail = re.sub(r'''(["'])(?:[A-Za-z]:[\\/]|\\\\|/)[^\r\n]*?\1''', '[가림]', detail)
    detail = re.sub(r'''(?:[A-Za-z]:[\\/]|\\\\)[^\r\n"'<>|;,]+|(?<![\w:])/[^\r\n"'<>;,]+''',
                    '[가림]', detail)
    return detail


class QueueOrder:
    def __init__(self, connect, *, sources=None):
        self.connect = connect
        self.sources = sources or TranslationSources()
        with connect() as db:
            db.executescript(f"""
                CREATE TABLE IF NOT EXISTS subtitle_queue_order (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    automatic INTEGER NOT NULL,
                    promoted INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL DEFAULT '{TRANSCRIPTION}',
                    UNIQUE(video_id, kind)
                );
                CREATE TABLE IF NOT EXISTS subtitle_queue_hidden (
                    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL DEFAULT '{TRANSCRIPTION}',
                    PRIMARY KEY(video_id, kind)
                );
            """)

    def request(self, db, video_id, *, kind=TRANSCRIPTION, automatic=False, renew=False):
        db.execute("DELETE FROM subtitle_queue_hidden WHERE video_id = ? AND kind = ?", (video_id, kind))
        if renew:
            db.execute("DELETE FROM subtitle_queue_order WHERE video_id = ? AND kind = ?", (video_id, kind))
        db.execute("INSERT OR IGNORE INTO subtitle_queue_order(video_id, kind, automatic) VALUES (?, ?, ?)",
                   (video_id, kind, automatic))
        if not automatic:
            db.execute("UPDATE subtitle_queue_order SET automatic = 0 WHERE video_id = ? AND kind = ?",
                       (video_id, kind))

    def finish(self, db, video_id, *, kind=TRANSCRIPTION):
        """같은 종류의 후속 단계까지 사라진 작업만 순번과 앞당기기를 끝낸다."""
        db.execute("DELETE FROM subtitle_queue_order WHERE video_id = ? AND kind = ? "
                   "AND NOT EXISTS (SELECT 1 FROM subtitle_queue WHERE video_id = ? AND kind = ?) "
                   "AND NOT EXISTS (SELECT 1 FROM translation_queue WHERE video_id = ? AND source = ?)",
                   (video_id, kind, video_id, kind, video_id, self.sources.for_queue_kind(kind)))

    def sort(self, entries):
        if not entries:
            return ()
        order = {}
        ids = list({e.video_id for e in entries})
        with self.connect() as db:
            for start in range(0, len(ids), 800):
                batch = ids[start:start + 800]
                order.update({(r["video_id"], r["kind"]): (-r["promoted"], r["automatic"], r["sequence"])
                              for r in db.execute("SELECT * FROM subtitle_queue_order WHERE video_id IN (" +
                                                  ",".join("?" for _ in batch) + ")", batch)})
        return tuple(sorted(entries, key=lambda e: subtitle_order_key(e.video_id, order, queue_task_key(e)[1])))

    def promote(self, video_id, *, kind=TRANSCRIPTION):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.request(db, video_id, kind=kind)
            db.execute("UPDATE subtitle_queue_order SET promoted = "
                       "(SELECT COALESCE(MAX(promoted), 0) + 1 FROM subtitle_queue_order) WHERE video_id = ? AND kind = ?",
                       (video_id, kind))


class AutoSubtitleRules:
    def __init__(self, connect, core):
        self.connect, self.core = connect, core
        with connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS auto_subtitle_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder TEXT UNIQUE REFERENCES watched_folders(path) ON DELETE CASCADE,
                    tag_id INTEGER UNIQUE REFERENCES tags(id) ON DELETE CASCADE,
                    spoken_language TEXT,
                    CHECK ((folder IS NULL) != (tag_id IS NULL))
                );
            """)

    def list(self):
        with self.connect() as db:
            return tuple(AutoSubtitleRule(r["id"], Path(r["folder"]) if r["folder"] else None,
                                         r["tag_id"], r["spoken_language"])
                         for r in db.execute("SELECT * FROM auto_subtitle_rules ORDER BY id"))

    def candidates(self, *, folder=None, tag_id=None):
        if (folder is None) == (tag_id is None):
            raise ValueError("감시 폴더 또는 태그 하나를 고르세요.")
        if folder is not None:
            folder = Path(folder).resolve()
            if folder not in {f.path for f in self.core.watched_folders()}:
                raise ValueError("감시 폴더를 찾을 수 없습니다.")
            videos = [v for v in self.core.videos()
                      if any(loc.path.is_relative_to(folder) for loc in v.locations)]
        else:
            videos = self.core.videos_for_tag(tag_id)
        pending = {e.video_id for e in self.core.subtitle_queue() if e.queue_kind == TRANSCRIPTION}
        return tuple(v.id for v in videos if not v.missing and v.id not in pending and not self.core.has_transcript(v.id))

    def set(self, *, folder=None, tag_id=None, spoken_language=None, include_existing=False):
        language = normalize_spoken_language(spoken_language)
        candidates = self.candidates(folder=folder, tag_id=tag_id)
        folder = str(Path(folder).resolve()) if folder is not None else None
        column, value = ("folder", folder) if folder else ("tag_id", tag_id)
        with self.connect() as db:
            db.execute(f"INSERT INTO auto_subtitle_rules(folder, tag_id, spoken_language) VALUES (?, ?, ?) "
                       f"ON CONFLICT({column}) DO UPDATE SET spoken_language = excluded.spoken_language",
                       (folder, tag_id, language))
            rule_id = db.execute(f"SELECT id FROM auto_subtitle_rules WHERE {column} = ?", (value,)).fetchone()[0]
        if include_existing:
            for video_id in candidates:
                self.core.request_automatic_subtitles(video_id, language)
        return next(r for r in self.list() if r.id == rule_id)

    def remove(self, rule_id):
        with self.connect() as db:
            db.execute("DELETE FROM auto_subtitle_rules WHERE id = ?", (rule_id,))

    def apply(self, video_id, *, tag_id=None, rules=None):
        # 등록 계기는 폴더 규칙, 태그 부착 계기는 그 태그 규칙만 적용한다.
        rules = [r for r in (self.list() if rules is None else rules)
                 if (r.folder is not None if tag_id is None else r.tag_id == tag_id)]
        if not rules:
            return
        video = self.core.video(video_id)
        if video.excluded or video.missing or self.core.has_transcript(video_id):
            return
        for rule in rules:
            if tag_id is not None or any(loc.path.is_relative_to(rule.folder) for loc in video.locations):
                self.core.request_automatic_subtitles(video_id, rule.spoken_language)
                return  # 겹치는 규칙은 먼저 만든 규칙을 따른다.


class SubtitleQueue:
    def __init__(self, core, order):
        self.core, self.order = core, order
        self._lock = RLock()
        self._outcomes = {}
        self._completed = set()
        self._notices = {}
        self._active = 0

    @contextmanager
    def processing(self):
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1

    def hide(self, video_id, *, kind=TRANSCRIPTION):
        key = video_id, kind
        with self._lock:
            self._outcomes.pop(key, None)
            self._completed.discard(key)
            self._notices.pop(key, None)
            with self.order.connect() as db:
                db.execute("INSERT OR IGNORE INTO subtitle_queue_hidden(video_id, kind) VALUES (?, ?)", key)

    def items(self):
        core = self.core
        subtitles = {queue_task_key(e): e for e in core.subtitle_queue(kind=None)}
        translations = {queue_task_key(e): e for e in core.translation_queue()}
        with self._lock:
            completed, notices = self._completed.copy(), self._notices.copy()
        keys = subtitles.keys() | translations.keys() | completed
        ids = list({video_id for video_id, _ in keys})
        if not ids:
            return ()
        videos, hidden = {}, set()
        with self.order.connect() as db:
            for start in range(0, len(ids), 800):
                batch = ids[start:start + 800]
                placeholders = ",".join("?" for _ in batch)
                videos.update((r["id"], r) for r in db.execute(
                    "SELECT id, title, (SELECT spoken_language FROM transcripts WHERE video_id=v.id) AS language, "
                    "EXISTS(SELECT 1 FROM transcripts WHERE video_id = v.id) AS has_transcript, "
                    "EXISTS(SELECT 1 FROM translation_lines tr JOIN transcript_lines l ON l.id=tr.line_id "
                    "JOIN transcripts t ON t.id=l.transcript_id WHERE t.video_id=v.id AND tr.source=?) AS has_result, "
                    "EXISTS(SELECT 1 FROM translation_lines tr WHERE tr.video_id=v.id AND tr.source=?) AS has_onscreen_result "
                    "FROM videos v WHERE id IN (" + placeholders + ")", (TRANSCRIPT, ONSCREEN, *batch)))
                hidden.update((r["video_id"], r["kind"]) for r in db.execute(
                    "SELECT video_id, kind FROM subtitle_queue_hidden WHERE video_id IN (" + placeholders + ")", batch))
        result = []
        for key in sorted(keys - hidden):
            video_id, kind = key
            video = videos.get(video_id)
            if video is None:
                continue
            title = video["title"]
            s, t = subtitles.get(key), translations.get(key)
            if s:
                result.append(SubtitleQueueItem(video_id, title, s.state, s.progress,
                                               s.error_detail or s.error, QUEUE_KIND_LABELS.get(kind, kind), queue_kind=kind))
            elif t:
                detail = _display_error_detail(t.error_detail)
                summary = t.error
                if summary and t.error_detail and t.error_detail.startswith(summary):
                    summary = None
                result.append(SubtitleQueueItem(video_id, title, t.state,
                                               t.completed_lines / max(1, t.total_lines),
                                               ' · '.join(filter(None, (summary, detail, t.notice))) or None,
                                               translation_task(video["language"], source=t.source).label, queue_kind=kind))
            elif key in completed and (kind != TRANSCRIPTION or video["has_transcript"]):
                result.append(SubtitleQueueItem(video_id, title, "completed", 1, notices.get(key),
                                                translation_task(None, source=ONSCREEN).label
                                                if kind == ONSCREEN_SUBTITLE and video['has_onscreen_result'] else
                                                translation_task(video["language"]).label
                                                if kind == TRANSCRIPTION and video["has_result"]
                                                and video["language"] not in (None, "und") else QUEUE_KIND_LABELS.get(kind, kind),
                                                queue_kind=kind))
        return self.order.sort(result)

    def record(self, result):
        if result is None or result.state not in ("completed", "failed"):
            return
        key = queue_task_key(result)
        with self._lock:
            with self.order.connect() as db:
                if db.execute("SELECT 1 FROM subtitle_queue_hidden WHERE video_id = ? AND kind = ?", key).fetchone():
                    return
            no_speech, no_text = getattr(result, "no_speech", False), getattr(result, "no_text", False)
            self._notices[key] = (NO_SPEECH_NOTICE if no_speech else NO_TEXT_NOTICE if no_text
                                  else getattr(result, "notice", ""))
            self._outcomes[key] = "no_speech" if no_speech else "no_text" if no_text else result.state
            if result.state == "completed":
                self._completed.add(key)
            else:
                self._completed.discard(key)

    def take_completion(self):
        """대기열 전체가 끝났을 때 한 번만 결과를 센다. 받아쓰기·화면 자막을 종류별로 나누지 않고 한 처리 묶음으로 알린다."""
        with self._lock:
            if self._active or not self._outcomes:
                return None
            # 보류도 남은 작업이다. 한도 대기 중에는 완료 알림을 내지 않는다.
            with self.order.connect() as db:
                pending = db.execute("SELECT EXISTS(SELECT 1 FROM subtitle_queue WHERE state IN ('queued', 'transcribing', 'reading')) "
                                     "OR EXISTS(SELECT 1 FROM translation_queue WHERE state IN ('queued', 'translating', 'held'))").fetchone()[0]
                if pending:
                    return None
            counts = SubtitleQueueCompletion(*(sum(s == state for s in self._outcomes.values())
                                               for state in ("completed", "failed", "no_speech", "no_text")))
            self._outcomes.clear()
            return counts
