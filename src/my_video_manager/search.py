"""검색 결과와 자막 FTS5 색인. 트리거는 앱 전용 SQL 함수에 의존하지 않는다."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Literal
import unicodedata


SearchSource = Literal["title", "filename", "tag", "note", "transcript", "translation", "external"]
SEARCH_LIMIT = 500
SOURCE_LABELS = {"title": "제목", "filename": "파일 이름", "tag": "태그", "note": "메모",
                 "transcript": "원어 자막", "translation": "번역 자막", "external": "외부 자막"}
SUBTITLE_SOURCES = (("transcript", "transcript_lines", "id"),
                    ("translation", "translation_lines", "line_id"),
                    ("external", "external_subtitle_lines", "id"))
BULK_NORMALIZATION_THRESHOLD = 10_000

CONTENT_UPDATE_TRIGGER = """CREATE TRIGGER IF NOT EXISTS search_content_update
    AFTER UPDATE ON search_subtitle_lines BEGIN
    INSERT INTO subtitle_search_v2(subtitle_search_v2, rowid, normalized)
        SELECT 'delete', old.id, old.normalized WHERE old.normalized IS NOT NULL;
    INSERT INTO subtitle_search_v2(rowid, normalized)
        SELECT new.id, new.normalized WHERE new.normalized IS NOT NULL; END"""


@dataclass(frozen=True)
class SearchResult:
    video_id: int
    title: str
    source: SearchSource
    text: str
    start: float | None = None
    missing: bool = False
    language: str | None = None


@dataclass(frozen=True)
class SearchResponse:
    results: tuple[SearchResult, ...] = ()
    truncated: bool = False


def search_key(text: str) -> str:
    """띄어쓰기·대소문자·Unicode 표현 차이를 무시한 리터럴 부분 검색."""
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


class Search:
    def __init__(self, connect):
        self._connect = connect
        self._ready = Event()
        self._preparing = Lock()
        # 쓰기 경로는 준비 작업 전에 호출되어도 안전해야 한다. 가벼운 스키마와
        # 함수에 의존하지 않는 트리거만 즉시 설치하고 기존 데이터 처리는 미룬다.
        self._install_schema()

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def prepare(self) -> None:
        """별도 스레드에서 호출할 수 있다. 동시 요청은 한 번의 준비 작업을 공유한다."""
        if self.ready:
            return
        with self._preparing:
            if not self.ready:
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    for source, table, identifier in SUBTITLE_SOURCES:
                        self._backfill_source(db, source, table, identifier)
                    self._normalize_pending(db)
                self._ready.set()

    def _install_schema(self):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # 이전 검색 빌드의 함수 의존 트리거를 반드시 교체한다.
            for source, _, _ in SUBTITLE_SOURCES:
                for event in ("insert", "delete", "update"):
                    db.execute(f"DROP TRIGGER IF EXISTS search_{source}_{event}")
            db.execute("DROP TABLE IF EXISTS subtitle_search")
            db.execute("""CREATE TABLE IF NOT EXISTS search_subtitle_lines (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, line_id TEXT NOT NULL,
                text TEXT NOT NULL, normalized TEXT, UNIQUE(source, line_id)
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS search_pending_normalization
                ON search_subtitle_lines(id) WHERE normalized IS NULL""")
            db.execute("CREATE TABLE IF NOT EXISTS search_backfill_sources (source TEXT PRIMARY KEY)")
            db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS subtitle_search_v2 USING fts5(
                normalized, content='search_subtitle_lines', content_rowid='id', tokenize='trigram'
            )""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS search_content_insert
                AFTER INSERT ON search_subtitle_lines WHEN new.normalized IS NOT NULL BEGIN
                INSERT INTO subtitle_search_v2(rowid, normalized) VALUES(new.id, new.normalized); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS search_content_delete
                AFTER DELETE ON search_subtitle_lines WHEN old.normalized IS NOT NULL BEGIN
                INSERT INTO subtitle_search_v2(subtitle_search_v2, rowid, normalized)
                VALUES('delete', old.id, old.normalized); END""")
            db.execute(CONTENT_UPDATE_TRIGGER)
            for source, table, identifier in SUBTITLE_SOURCES:
                self._install_source(db, source, table, identifier)

    @staticmethod
    def _install_source(db, source, table, identifier):
        # 식별자는 위의 상수만 사용한다. 원문 저장·수정·삭제는 함수 없는 접속에서도 동작한다.
        insert = f"""INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('{source}', new.{identifier}, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL;"""
        # line_id is TEXT even for integer external IDs; matching affinity keeps
        # SQLite on the (source, line_id) index for all three subtitle sources.
        delete = f"DELETE FROM search_subtitle_lines WHERE source='{source}' AND line_id=CAST(old.{identifier} AS TEXT);"
        for event, body in (("INSERT", insert), ("DELETE", delete), ("UPDATE", delete + insert)):
            trigger_event = "UPDATE OF text" if event == "UPDATE" else event
            db.execute(f"""CREATE TRIGGER search_{source}_{event.lower()}
                AFTER {trigger_event} ON {table} BEGIN {body} END""")
    @staticmethod
    def _backfill_source(db, source, table, identifier):
        # 준비 전에 새 줄을 저장해도 기존 줄을 빠뜨리지 않도록 완료 표식은 별도로 둔다.
        if not db.execute("SELECT 1 FROM search_backfill_sources WHERE source=?", (source,)).fetchone():
            db.execute(f"""INSERT OR IGNORE INTO search_subtitle_lines(source, line_id, text)
                SELECT ?, {identifier}, text FROM {table}""", (source,))
            db.execute("INSERT INTO search_backfill_sources VALUES (?)", (source,))

    @staticmethod
    def _normalize_pending(db):
        bulk = db.execute("""SELECT count(*) FROM (SELECT id FROM search_subtitle_lines
            WHERE normalized IS NULL LIMIT ?)""", (BULK_NORMALIZATION_THRESHOLD,)).fetchone()[0] >= BULK_NORMALIZATION_THRESHOLD
        if bulk:
            # 같은 쓰기 트랜잭션 안에서만 트리거를 잠시 빼고 한 번에 재색인한다.
            # 실패 시 DDL과 데이터가 함께 롤백되므로 외부 연결은 중간 상태를 보지 않는다.
            db.execute("DROP TRIGGER search_content_update")
        while rows := db.execute("SELECT id, text FROM search_subtitle_lines WHERE normalized IS NULL LIMIT 1000").fetchall():
            db.executemany("UPDATE search_subtitle_lines SET normalized=? WHERE id=?",
                           [(search_key(row["text"]), row["id"]) for row in rows])
        if bulk:
            db.execute("INSERT INTO subtitle_search_v2(subtitle_search_v2) VALUES('rebuild')")
            db.execute(CONTENT_UPDATE_TRIGGER)

    def find(self, query: str, videos) -> SearchResponse:
        self.prepare()
        key = search_key(query)
        if not key:
            return SearchResponse()
        by_id = {video.id: video for video in videos}
        results = []

        def add(video_id, source, text, start=None, language=None):
            video = by_id.get(video_id)
            if video is not None and key in search_key(text):
                results.append(SearchResult(video_id, video.title, source, text, start, video.missing, language))
            return len(results) > SEARCH_LIMIT

        def response():
            selected = results[:SEARCH_LIMIT]
            subtitles = [result for result in selected if result.source in ("transcript", "translation", "external")]
            other = [result for result in selected if result.source not in ("transcript", "translation", "external")]
            subtitles.sort(key=lambda result: (result.video_id, result.start, result.source, result.text))
            return SearchResponse(tuple(other + subtitles), len(results) > SEARCH_LIMIT)

        for video in videos:
            if add(video.id, "title", video.title):
                return response()
        for video in videos:
            for name in dict.fromkeys(Path(location.path).name for location in video.locations):
                if add(video.id, "filename", name):
                    return response()
        with self._connect() as db:
            # 검색 직전에 미정규화 행을 채운다. 부분 인덱스로 이미 처리한 줄은 다시 읽지 않는다.
            db.execute("BEGIN IMMEDIATE")
            self._normalize_pending(db)
            for row in db.execute("""SELECT a.video_id, t.name FROM video_tags a
                    JOIN tags t ON t.id = a.tag_id
                    UNION SELECT h.video_id, t.name FROM highlight_tags a
                    JOIN tags t ON t.id = a.tag_id JOIN highlights h ON h.id = a.highlight_id"""):
                if add(row["video_id"], "tag", row["name"]):
                    return response()
            for row in db.execute("SELECT video_id, note, start FROM highlights WHERE note IS NOT NULL ORDER BY id"):
                if add(row["video_id"], "note", row["note"], row["start"]):
                    return response()
            # 1~2자는 리터럴 부분 문자열 조회, 3자 이상은 FTS5 후보 조회.
            # 커서는 상한+1개를 찾으면 즉시 닫아 전체 결과를 만들거나 정렬하지 않는다.
            if len(key) < 3:
                candidates, value = "SELECT * FROM search_subtitle_lines WHERE instr(normalized, ?) > 0", key
            else:
                candidates = """SELECT c.* FROM subtitle_search_v2 f
                    JOIN search_subtitle_lines c ON c.id=f.rowid WHERE subtitle_search_v2 MATCH ?"""
                value = '"' + key.replace('"', '""') + '"'
            for row in db.execute(f"""SELECT c.source, c.text, coalesce(l.start, e.start) AS start,
                    coalesce(t.video_id, f.video_id) AS video_id, s.language
                    FROM ({candidates}) c
                    LEFT JOIN transcript_lines l ON c.source IN ('transcript', 'translation') AND l.id=c.line_id
                    LEFT JOIN transcripts t ON t.id=l.transcript_id
                    LEFT JOIN external_subtitle_lines e ON c.source='external' AND e.id=c.line_id
                    LEFT JOIN external_subtitles s ON s.id=e.subtitle_id
                    LEFT JOIN external_subtitle_files f ON f.id=s.file_id""", (value,)):
                if add(row["video_id"], row["source"], row["text"], row["start"], row["language"]):
                    break
        return response()
