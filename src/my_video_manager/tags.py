"""영상과 하이라이트가 공유하는 평평한 태그와 이름 정책."""

from dataclasses import dataclass
import sqlite3
import unicodedata

from .highlights import Highlight, Note


@dataclass(frozen=True)
class Tag:
    id: int
    name: str


def normalize_tag_name(name: str) -> str:
    """표시 이름: Unicode 호환 정규화 후 연속 공백을 한 칸으로 정리한다."""
    return " ".join(unicodedata.normalize("NFKC", name).split())


class Tags:
    def __init__(self, connect):
        self._connect = connect
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS video_tags (
                    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (video_id, tag_id)
                );
                CREATE TABLE IF NOT EXISTS highlight_tags (
                    highlight_id INTEGER NOT NULL REFERENCES highlights(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (highlight_id, tag_id)
                );
                CREATE INDEX IF NOT EXISTS video_tags_tag ON video_tags(tag_id);
                CREATE INDEX IF NOT EXISTS highlight_tags_tag ON highlight_tags(tag_id);
            """)

    @staticmethod
    def _name(name):
        name = normalize_tag_name(name)
        if not name:
            raise ValueError("태그 이름을 입력하세요.")
        return name, name.casefold()

    @staticmethod
    def _require(db, table, identifier):
        # table은 이 모듈 안에서 정한 상수만 전달한다.
        if db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (identifier,)).fetchone() is None:
            label = {"tags": "태그", "videos": "영상", "highlights": "하이라이트"}[table]
            raise ValueError(f"{label}를 찾을 수 없습니다.")

    def list(self, prefix: str = "") -> tuple[Tag, ...]:
        key = normalize_tag_name(prefix).casefold()
        with self._connect() as db:
            # LIKE의 %, _를 검색 문법으로 해석하지 않고 Unicode casefold를 일관되게 쓴다.
            return tuple(Tag(row["id"], row["name"]) for row in db.execute(
                "SELECT * FROM tags ORDER BY name_key, id") if row["name_key"].startswith(key))

    def _create(self, db, name) -> Tag:
        name, key = self._name(name)
        db.execute("INSERT OR IGNORE INTO tags (name, name_key) VALUES (?, ?)", (name, key))
        row = db.execute("SELECT id, name FROM tags WHERE name_key = ?", (key,)).fetchone()
        return Tag(row["id"], row["name"])

    def create(self, name: str) -> Tag:
        with self._connect() as db:
            return self._create(db, name)

    def rename(self, tag_id: int, name: str) -> Tag:
        name, key = self._name(name)
        with self._connect() as db:
            self._require(db, "tags", tag_id)
            try:
                db.execute("UPDATE tags SET name = ?, name_key = ? WHERE id = ?", (name, key, tag_id))
            except sqlite3.IntegrityError as error:
                raise ValueError("같은 이름의 태그가 이미 있습니다. 다른 이름을 입력하세요.") from error
        return Tag(tag_id, name)

    def delete(self, tag_id: int) -> None:
        with self._connect() as db:
            self._require(db, "tags", tag_id)
            db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

    def attached(self, target: str, identifier: int) -> tuple[Tag, ...]:
        with self._connect() as db:
            self._require(db, f"{target}s", identifier)
            return tuple(Tag(row["id"], row["name"]) for row in db.execute(
                f"SELECT t.id, t.name FROM tags t JOIN {target}_tags a ON a.tag_id = t.id "
                f"WHERE a.{target}_id = ? ORDER BY t.name_key, t.id", (identifier,)))

    def attach(self, target: str, identifier: int, name: str) -> Tag:
        with self._connect() as db:
            self._require(db, f"{target}s", identifier)
            tag = self._create(db, name)
            db.execute(f"INSERT OR IGNORE INTO {target}_tags ({target}_id, tag_id) VALUES (?, ?)",
                       (identifier, tag.id))
            return tag

    def detach(self, target: str, identifier: int, tag_id: int) -> None:
        with self._connect() as db:
            self._require(db, f"{target}s", identifier)
            self._require(db, "tags", tag_id)
            db.execute(f"DELETE FROM {target}_tags WHERE {target}_id = ? AND tag_id = ?",
                       (identifier, tag_id))

    def video_ids(self, tag_id: int) -> set[int]:
        with self._connect() as db:
            self._require(db, "tags", tag_id)
            return {row[0] for row in db.execute("SELECT video_id FROM video_tags WHERE tag_id = ?", (tag_id,))}

    def highlights(self, tag_id: int) -> tuple[Highlight, ...]:
        with self._connect() as db:
            self._require(db, "tags", tag_id)
            return tuple(Highlight(row["id"], row["video_id"], row["start"], row["end"],
                                   Note(row["note"]) if row["note"] else None)
                         for row in db.execute(
                             "SELECT h.* FROM highlights h JOIN highlight_tags a ON a.highlight_id = h.id "
                             "WHERE a.tag_id = ? ORDER BY h.video_id, h.start, h.id", (tag_id,)))
