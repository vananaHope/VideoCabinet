"""검색 결과와 자막 FTS5 색인. 나머지 범위는 현재 원본을 조회한다."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import unicodedata


SearchSource = Literal["title", "filename", "tag", "note", "transcript", "translation"]


@dataclass(frozen=True)
class SearchResult:
    video_id: int
    title: str
    source: SearchSource
    text: str
    start: float | None = None


def search_key(text: str) -> str:
    """띄어쓰기·대소문자·Unicode 표현 차이를 무시한 리터럴 부분 검색."""
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def configure_search_connection(connection):
    # 자막 작업자도 AppCore의 접속을 쓰므로 트리거가 같은 정규화를 사용한다.
    connection.create_function("search_key", 1, search_key, deterministic=True)


class Search:
    def __init__(self, connect):
        self._connect = connect
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS subtitle_search USING fts5(
                normalized, text UNINDEXED, video_id UNINDEXED,
                source UNINDEXED, line_id UNINDEXED, start UNINDEXED,
                tokenize='trigram'
            )""")
            self._install_transcript_index(db)

    @staticmethod
    def _install_transcript_index(db):
        # source와 line_id를 함께 식별자로 사용한다. 번역은 같은 줄 ID를 써도
        # source='translation'으로 별도 색인할 수 있다.
        insert = """INSERT INTO subtitle_search
            (normalized, text, video_id, source, line_id, start)
            SELECT search_key(new.text), new.text, t.video_id, 'transcript', new.id, new.start
            FROM transcripts t WHERE t.id = new.transcript_id;"""
        delete = "DELETE FROM subtitle_search WHERE source = 'transcript' AND line_id = old.id;"
        for event, body in (("INSERT", insert), ("DELETE", delete), ("UPDATE", delete + insert)):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS search_transcript_{event.lower()}
                AFTER {event} ON transcript_lines BEGIN {body} END""")
        # 기존 DB를 처음 열었을 때도 색인한다. 버전 번호와 원본 구조는 바꾸지 않는다.
        if not db.execute("SELECT 1 FROM subtitle_search WHERE source = 'transcript' LIMIT 1").fetchone():
            db.execute("""INSERT INTO subtitle_search
                (normalized, text, video_id, source, line_id, start)
                SELECT search_key(l.text), l.text, t.video_id, 'transcript', l.id, l.start
                FROM transcript_lines l JOIN transcripts t ON t.id = l.transcript_id""")

    def find(self, query: str, videos) -> tuple[SearchResult, ...]:
        key = search_key(query)
        if not key:
            return ()
        titles = {video.id: video.title for video in videos}
        results = []

        def add(video_id, source, text, start=None):
            if video_id in titles and key in search_key(text):
                results.append(SearchResult(video_id, titles[video_id], source, text, start))

        for video in videos:
            add(video.id, "title", video.title)
            for name in dict.fromkeys(Path(location.path).name for location in video.locations):
                add(video.id, "filename", name)
        with self._connect() as db:
            db.execute("BEGIN")
            for row in db.execute("""SELECT a.video_id, t.name FROM video_tags a
                    JOIN tags t ON t.id = a.tag_id
                    UNION SELECT h.video_id, t.name FROM highlight_tags a
                    JOIN tags t ON t.id = a.tag_id JOIN highlights h ON h.id = a.highlight_id"""):
                add(row["video_id"], "tag", row["name"])
            for row in db.execute("SELECT video_id, note, start FROM highlights WHERE note IS NOT NULL"):
                add(row["video_id"], "note", row["note"], row["start"])
            # trigram MATCH는 3자 미만을 찾지 못하므로 1~2자는 색인 내용에서
            # 리터럴 부분 문자열로 찾는다. 따옴표·%·_ 등도 검색 문법이 아니다.
            if len(key) < 3:
                condition, value = "instr(normalized, ?) > 0", key
            else:
                condition, value = "subtitle_search MATCH ?", '"' + key.replace('"', '""') + '"'
            for row in db.execute(f"SELECT * FROM subtitle_search WHERE {condition}", (value,)):
                add(row["video_id"], row["source"], row["text"], row["start"])
        order = {name: index for index, name in enumerate(
            ("title", "filename", "tag", "note", "transcript", "translation"))}
        return tuple(sorted(results, key=lambda result: (
            search_key(result.title), result.video_id, order[result.source],
            result.start if result.start is not None else -1, result.text)))
