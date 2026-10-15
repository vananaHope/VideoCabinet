"""자동 자막 규칙, 처리 순서와 영상별 대기열 표시 정책."""

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
import re
from threading import RLock

from .subtitles import normalize_spoken_language
from .translation_kind import translation_task


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
    error: str | None = None
    task_label: str = "받아쓰기"


@dataclass(frozen=True)
class SubtitleRetrySkipped:
    video_id: int
    reason: str


@dataclass(frozen=True)
class SubtitleRetryResult:
    retried: int
    skipped: tuple[SubtitleRetrySkipped, ...]

    @property
    def skipped_count(self):
        return len(self.skipped)


def subtitle_order_key(video_id, positions):
    """옛 항목은 직접 요청 등급의 마지막에서 기존 상대 순서를 유지한다."""
    return positions.get(video_id, (0, 0, float("inf")))


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
    def __init__(self, connect):
        self.connect = connect
        with connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS subtitle_queue_order (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE,
                    automatic INTEGER NOT NULL,
                    promoted INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS subtitle_queue_hidden (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE
                );
            """)

    def request(self, db, video_id, *, automatic=False, renew=False):
        db.execute("DELETE FROM subtitle_queue_hidden WHERE video_id = ?", (video_id,))
        if renew:
            db.execute("DELETE FROM subtitle_queue_order WHERE video_id = ?", (video_id,))
        db.execute("INSERT OR IGNORE INTO subtitle_queue_order(video_id, automatic) VALUES (?, ?)",
                   (video_id, automatic))
        if not automatic:
            db.execute("UPDATE subtitle_queue_order SET automatic = 0 WHERE video_id = ?", (video_id,))

    def finish(self, db, video_id):
        """받아쓰기·번역 항목이 모두 사라진 영상만 순번과 앞당기기를 끝낸다."""
        db.execute("DELETE FROM subtitle_queue_order WHERE video_id = ? "
                   "AND NOT EXISTS (SELECT 1 FROM subtitle_queue WHERE video_id = ?) "
                   "AND NOT EXISTS (SELECT 1 FROM translation_queue WHERE video_id = ?)",
                   (video_id, video_id, video_id))

    def sort(self, entries):
        if not entries:
            return ()
        order = {}
        ids = list({e.video_id for e in entries})
        with self.connect() as db:
            for start in range(0, len(ids), 800):
                batch = ids[start:start + 800]
                order.update({r["video_id"]: (-r["promoted"], r["automatic"], r["sequence"])
                              for r in db.execute("SELECT * FROM subtitle_queue_order WHERE video_id IN (" +
                                                  ",".join("?" for _ in batch) + ")", batch)})
        return tuple(sorted(entries, key=lambda e: subtitle_order_key(e.video_id, order)))

    def promote(self, video_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.request(db, video_id)
            db.execute("UPDATE subtitle_queue_order SET promoted = "
                       "(SELECT COALESCE(MAX(promoted), 0) + 1 FROM subtitle_queue_order) WHERE video_id = ?",
                       (video_id,))


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
        pending = {e.video_id for e in self.core.subtitle_queue()}
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

    def hide(self, video_id):
        with self._lock:
            self._outcomes.pop(video_id, None)
            self._completed.discard(video_id)
            self._notices.pop(video_id, None)
            with self.order.connect() as db:
                db.execute("INSERT OR IGNORE INTO subtitle_queue_hidden VALUES (?)", (video_id,))

    def items(self):
        core = self.core
        subtitles = {e.video_id: e for e in core.subtitle_queue()}
        translations = {e.video_id: e for e in core.translation_queue()}
        with self._lock:
            ids = list(subtitles.keys() | translations.keys() | self._completed)
        if not ids:
            return ()
        videos = []
        with self.order.connect() as db:
            for start in range(0, len(ids), 800):
                batch = ids[start:start + 800]
                videos.extend(db.execute(
                    "SELECT id, title, (SELECT spoken_language FROM transcripts WHERE video_id=v.id) AS language, "
                    "EXISTS(SELECT 1 FROM transcripts WHERE video_id = v.id) AS has_transcript, "
                    "EXISTS(SELECT 1 FROM translation_lines tr JOIN transcript_lines l ON l.id=tr.line_id "
                    "JOIN transcripts t ON t.id=l.transcript_id WHERE t.video_id=v.id) AS has_result "
                    "FROM videos v WHERE id IN (" + ",".join("?" for _ in batch) + ") "
                    "AND NOT EXISTS(SELECT 1 FROM subtitle_queue_hidden WHERE video_id = v.id)", batch).fetchall())
        result = []
        for video in videos:
            video_id, title = video["id"], video["title"]
            s, t = subtitles.get(video_id), translations.get(video_id)
            if s:
                result.append(SubtitleQueueItem(video_id, title, s.state, s.progress, s.error_detail or s.error))
            elif t:
                detail = _display_error_detail(t.error_detail)
                summary = t.error
                if summary and detail and detail.startswith(summary):
                    summary = None
                result.append(SubtitleQueueItem(video_id, title, t.state,
                                               t.completed_lines / max(1, t.total_lines),
                                               ' · '.join(filter(None, (summary, detail, t.notice))) or None,
                                               translation_task(video["language"]).label))
            elif video["has_transcript"]:
                result.append(SubtitleQueueItem(video_id, title, "completed", 1, self._notices.get(video_id),
                                                translation_task(video["language"]).label
                                                if video["has_result"] and video["language"] not in (None, "und")
                                                else "받아쓰기"))
        return self.order.sort(result)

    def record(self, result):
        if result is None or result.state not in ("completed", "failed"):
            return
        with self._lock:
            with self.order.connect() as db:
                if db.execute("SELECT 1 FROM subtitle_queue_hidden WHERE video_id = ?", (result.video_id,)).fetchone():
                    return
            self._notices[result.video_id] = getattr(result, "notice", "")
            self._outcomes[result.video_id] = result.state
            if result.state == "completed":
                self._completed.add(result.video_id)
            else:
                self._completed.discard(result.video_id)

    def take_completion(self):
        with self._lock:
            if self._active or not self._outcomes:
                return None
            # 보류도 남은 작업이다. 한도 대기 중에는 완료 알림을 내지 않는다.
            with self.order.connect() as db:
                pending = db.execute("SELECT EXISTS(SELECT 1 FROM subtitle_queue WHERE state IN ('queued', 'transcribing')) "
                                     "OR EXISTS(SELECT 1 FROM translation_queue WHERE state IN ('queued', 'translating', 'held'))").fetchone()[0]
                if pending:
                    return None
            counts = (sum(s == "completed" for s in self._outcomes.values()),
                      sum(s == "failed" for s in self._outcomes.values()))
            self._outcomes.clear()
            return counts
