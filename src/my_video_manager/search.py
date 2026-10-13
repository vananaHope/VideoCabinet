"""검색 결과와 자막 FTS5 색인. 트리거는 앱 전용 SQL 함수에 의존하지 않는다."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import unicodedata


SearchSource = Literal["title", "filename", "tag", "note", "transcript", "translation"]
SEARCH_LIMIT = 500


@dataclass(frozen=True)
class SearchResult:
    video_id: int
    title: str
    source: SearchSource
    text: str
    start: float | None = None
    missing: bool = False


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
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # 이전 검색 빌드의 함수 의존 트리거를 반드시 교체한다.
            for source in ("transcript", "translation"):
                for event in ("insert", "delete", "update"):
                    db.execute(f"DROP TRIGGER IF EXISTS search_{source}_{event}")
            db.execute("DROP TABLE IF EXISTS subtitle_search")
            db.execute("""CREATE TABLE IF NOT EXISTS search_subtitle_lines (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, line_id TEXT NOT NULL,
                text TEXT NOT NULL, normalized TEXT, UNIQUE(source, line_id)
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS search_pending_normalization
                ON search_subtitle_lines(id) WHERE normalized IS NULL""")
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
            db.execute("""CREATE TRIGGER IF NOT EXISTS search_content_update
                AFTER UPDATE ON search_subtitle_lines BEGIN
                INSERT INTO subtitle_search_v2(subtitle_search_v2, rowid, normalized)
                    SELECT 'delete', old.id, old.normalized WHERE old.normalized IS NOT NULL;
                INSERT INTO subtitle_search_v2(rowid, normalized)
                    SELECT new.id, new.normalized WHERE new.normalized IS NOT NULL; END""")
            for source, table, identifier in (("transcript", "transcript_lines", "id"),
                                               ("translation", "translation_lines", "line_id")):
                self._install_source(db, source, table, identifier)
            self._normalize_pending(db)

    @staticmethod
    def _install_source(db, source, table, identifier):
        # 식별자는 위의 상수만 사용한다. 원문 저장·수정·삭제는 함수 없는 접속에서도 동작한다.
        insert = f"""INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('{source}', new.{identifier}, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL;"""
        delete = f"DELETE FROM search_subtitle_lines WHERE source='{source}' AND line_id=old.{identifier};"
        for event, body in (("INSERT", insert), ("DELETE", delete), ("UPDATE", delete + insert)):
            db.execute(f"""CREATE TRIGGER search_{source}_{event.lower()}
                AFTER {event} ON {table} BEGIN {body} END""")
        # 원어 색인이 이미 있어도 기존 번역은 독립적으로 백필한다.
        if not db.execute("SELECT 1 FROM search_subtitle_lines WHERE source=? LIMIT 1", (source,)).fetchone():
            db.execute(f"""INSERT INTO search_subtitle_lines(source, line_id, text)
                SELECT ?, {identifier}, text FROM {table}""", (source,))

    @staticmethod
    def _normalize_pending(db):
        while rows := db.execute("SELECT id, text FROM search_subtitle_lines WHERE normalized IS NULL LIMIT 1000").fetchall():
            db.executemany("UPDATE search_subtitle_lines SET normalized=? WHERE id=?",
                           [(search_key(row["text"]), row["id"]) for row in rows])

    def find(self, query: str, videos) -> SearchResponse:
        key = search_key(query)
        if not key:
            return SearchResponse()
        by_id = {video.id: video for video in videos}
        results = []

        def add(video_id, source, text, start=None):
            video = by_id.get(video_id)
            if video is not None and key in search_key(text):
                results.append(SearchResult(video_id, video.title, source, text, start, not video.locations))
            return len(results) > SEARCH_LIMIT

        def response():
            # 범위 순서로 수집하며 각 범위 안에서는 DB의 안정적인 식별자 순서를 쓴다.
            return SearchResponse(tuple(results[:SEARCH_LIMIT]), len(results) > SEARCH_LIMIT)

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
            for row in db.execute(f"""SELECT c.source, c.text, l.start, t.video_id
                    FROM ({candidates}) c JOIN transcript_lines l ON l.id=c.line_id
                    JOIN transcripts t ON t.id=l.transcript_id""", (value,)):
                if add(row["video_id"], row["source"], row["text"], row["start"]):
                    break
        return response()
