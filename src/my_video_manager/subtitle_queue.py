"""자동 자막 규칙, 처리 순서와 영상별 대기열 표시 정책."""

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from .subtitles import normalize_spoken_language


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

    def sort(self, entries):
        with self.connect() as db:
            order = {r["video_id"]: (-r["promoted"], r["automatic"], r["sequence"])
                     for r in db.execute("SELECT * FROM subtitle_queue_order")}
        # 이전 버전 항목은 원래 FIFO를 유지하는 직접 요청으로 취급한다.
        return tuple(sorted(entries, key=lambda e: order.get(e.video_id, (0, 0, 0))))

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
        return tuple(v.id for v in videos if not v.missing and v.id not in pending and self.core.transcript(v.id) is None)

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

    def apply(self, video_id):
        video = next((v for v in self.core.videos() if v.id == video_id), None)
        if video is None or video.missing or self.core.transcript(video_id) is not None:
            return
        tags = {t.id for t in self.core.video_tags(video_id)}
        for rule in self.list():
            if ((rule.tag_id is not None and rule.tag_id in tags) or
                    (rule.folder is not None and any(loc.path.is_relative_to(rule.folder) for loc in video.locations))):
                self.core.request_automatic_subtitles(video_id, rule.spoken_language)
                return  # 겹치는 규칙은 먼저 만든 규칙을 따른다.


class SubtitleQueue:
    def __init__(self, core, order):
        self.core, self.order = core, order
        self._lock = RLock()
        self._outcomes = {}
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
            with self.order.connect() as db:
                db.execute("INSERT OR IGNORE INTO subtitle_queue_hidden VALUES (?)", (video_id,))

    def items(self):
        core = self.core
        subtitles = {e.video_id: e for e in core.subtitle_queue()}
        translations = {e.video_id: e for e in core.translation_queue()}
        with self.order.connect() as db:
            hidden = {r[0] for r in db.execute("SELECT video_id FROM subtitle_queue_hidden")}
        result = []
        for video in core.videos() + core.excluded_videos():
            if video.id in hidden:
                continue
            s, t = subtitles.get(video.id), translations.get(video.id)
            if s:
                result.append(SubtitleQueueItem(video.id, video.title, s.state, s.progress, s.error_detail or s.error))
            elif t:
                result.append(SubtitleQueueItem(video.id, video.title, t.state,
                                               t.completed_lines / max(1, t.total_lines), t.error_detail or t.error))
            elif core.transcript(video.id) is not None:
                result.append(SubtitleQueueItem(video.id, video.title, "completed", 1))
        return self.order.sort(result)

    def record(self, result):
        if result is None or result.state not in ("completed", "failed"):
            return
        with self._lock:
            with self.order.connect() as db:
                if db.execute("SELECT 1 FROM subtitle_queue_hidden WHERE video_id = ?", (result.video_id,)).fetchone():
                    return
            self._outcomes[result.video_id] = result.state

    def take_completion(self):
        with self._lock:
            if self._active:
                return None
            # 보류도 남은 작업이다. 한도 대기 중에는 완료 알림을 내지 않는다.
            if any(i.state in ("queued", "transcribing", "translating", "held") for i in self.items()):
                return None
            if not self._outcomes:
                return None
            counts = (sum(s == "completed" for s in self._outcomes.values()),
                      sum(s == "failed" for s in self._outcomes.values()))
            self._outcomes.clear()
            return counts
