"""영상과 하이라이트가 공유하는 평평한 태그와 이름 정책."""

from dataclasses import dataclass
import sqlite3
import unicodedata


@dataclass(frozen=True)
class Tag:
    id: int
    name: str


@dataclass(frozen=True)
class TagUsage:
    """태그와 그 태그가 붙은 영상 수. key는 검색용 정규화 이름이다."""
    tag: Tag
    key: str
    video_count: int


REMOVED_CATEGORIES = frozenset({"Cc", "Cf"})


def normalize_tag_name(name: str) -> str:
    """표시 이름은 NFC로 보존하고 제어·서식 문자를 제거한 뒤 공백을 정리한다."""
    name = "".join(char for char in name if unicodedata.category(char) not in REMOVED_CATEGORIES)
    return " ".join(unicodedata.normalize("NFC", name).split())


def tag_name_key(name: str) -> str:
    return unicodedata.normalize("NFKC", normalize_tag_name(name)).casefold()


def tag_name_key_tables() -> dict:
    """웹 태그 검색이 tag_name_key와 같은 key를 동기로 만들 표. 이 Python의 Unicode 데이터에서 만든다.

    assigned: 이 Unicode 버전이 아는 코드 포인트 범위. 웹은 이 범위만 NFC·NFKC 정규화하고 나머지는 그대로 둔다.
    removed: 지우는 범위(REMOVED_CATEGORIES). spaces: str.split()의 공백. casefold: casefold()가 바꾸는 글자.
    """
    def ranges(predicate):
        found, start = [], None
        for code in range(0x110000 + 1):
            if code <= 0x10FFFF and predicate(chr(code)):
                start = code if start is None else start
            elif start is not None:
                found.extend((start, code - 1))
                start = None
        return found
    return dict(
        unicodeVersion=unicodedata.unidata_version,
        assigned=ranges(lambda char: unicodedata.category(char) != "Cn"),
        removed=ranges(lambda char: unicodedata.category(char) in REMOVED_CATEGORIES),
        spaces=[code for code in range(0x110000) if chr(code).isspace()],
        casefold=[(code, chr(code).casefold()) for code in range(0x110000) if chr(code).casefold() != chr(code)],
    )


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
        if len(name) > 50:
            raise ValueError("태그 이름은 공백 정리 후 50자 이하여야 합니다.")
        return name, tag_name_key(name)

    @staticmethod
    def _require(db, table, identifier):
        # table은 이 모듈 안에서 정한 상수만 전달한다.
        if db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (identifier,)).fetchone() is None:
            message = {"tags": "태그를 찾을 수 없습니다.", "videos": "영상을 찾을 수 없습니다.",
                       "highlights": "하이라이트를 찾을 수 없습니다."}[table]
            raise ValueError(message)

    def list(self, prefix: str = "") -> tuple[Tag, ...]:
        key = tag_name_key(prefix)
        with self._connect() as db:
            # LIKE의 %, _를 검색 문법으로 해석하지 않고 Unicode casefold를 일관되게 쓴다.
            return tuple(Tag(row["id"], row["name"]) for row in db.execute(
                "SELECT * FROM tags ORDER BY name_key, id") if row["name_key"].startswith(key))

    def usage(self) -> tuple[TagUsage, ...]:
        """붙은 영상 수가 많은 순, 같으면 이름순. 제외 영상과 하이라이트 연결은 세지 않는다."""
        with self._connect() as db:
            return tuple(TagUsage(Tag(row["id"], row["name"]), row["name_key"], row["video_count"]) for row in db.execute(
                """SELECT t.id, t.name, t.name_key, COUNT(v.id) AS video_count FROM tags t
                   LEFT JOIN video_tags a ON a.tag_id = t.id
                   LEFT JOIN videos v ON v.id = a.video_id AND v.excluded = 0
                   GROUP BY t.id ORDER BY video_count DESC, t.name_key, t.id"""))

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

    def video_tags_map(self) -> dict[int, tuple[Tag, ...]]:
        """태그 없는 영상도 빈 튜플로 포함하는 일괄 조회."""
        grouped = {}
        with self._connect() as db:
            for row in db.execute("""SELECT v.id AS video_id, t.id, t.name FROM videos v
                    LEFT JOIN video_tags a ON a.video_id = v.id
                    LEFT JOIN tags t ON t.id = a.tag_id ORDER BY t.name_key, t.id"""):
                tags = grouped.setdefault(row["video_id"], [])
                if row["id"] is not None:
                    tags.append(Tag(row["id"], row["name"]))
        return {vid: tuple(tags) for vid, tags in grouped.items()}

    def highlight_tags_map(self, video_id: int) -> dict[int, tuple[Tag, ...]]:
        """선택 영상의 하이라이트 태그를 한 번에 읽는다. 태그 없는 항목도 포함한다."""
        grouped = {}
        with self._connect() as db:
            for row in db.execute("""SELECT h.id AS highlight_id, t.id, t.name FROM highlights h
                    LEFT JOIN highlight_tags a ON a.highlight_id = h.id
                    LEFT JOIN tags t ON t.id = a.tag_id WHERE h.video_id = ?
                    ORDER BY t.name_key, t.id""", (video_id,)):
                tags = grouped.setdefault(row['highlight_id'], [])
                if row['id'] is not None:
                    tags.append(Tag(row['id'], row['name']))
        return {hid: tuple(tags) for hid, tags in grouped.items()}

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

    def highlight_ids(self, tag_id: int) -> set[int]:
        with self._connect() as db:
            self._require(db, "tags", tag_id)
            return {row[0] for row in db.execute(
                "SELECT highlight_id FROM highlight_tags WHERE tag_id = ?", (tag_id,))}
