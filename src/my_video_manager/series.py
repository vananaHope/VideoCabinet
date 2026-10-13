"""시리즈 번호·제목 틀의 순수 계산과 자동 묶기, 사용자 편집 저장."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


@dataclass(frozen=True)
class Series:
    id: int
    name: str
    video_ids: tuple[int, ...]
    edited: bool = False


# 해상도/코덱은 번호 후보에서 먼저 빼고, 그 외 숫자를 임의로 추측하지 않는다.
_LABEL = re.compile(r"(?<![a-z0-9])(?:\d{3,4}[pi]|[248]k|[hx][ ._-]?26[45]|hevc|avc|av1|xvid|aac|ac3|dts)(?![a-z0-9])", re.I)
_NUMBER = re.compile(
    r"(?<![a-z0-9])s(?P<season>\d+)\s*e(?P<episode>\d+)(?!\d)"
    r"|(?<!\d)(?P<korean>\d+)\s*(?:강|화|회)(?![가-힣])"
    r"|(?<![a-z0-9])(?:e|ep|episode|part)\s*[._-]?\s*(?P<english>\d+)(?![a-z0-9])",
    re.I,
)


def normalize_series_title(title: str) -> str:
    """대소문자·공백·구분자를 통일하고 알려진 기술 꼬리표를 제거한다."""
    title = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(re.sub(r"[\W_]+", " ", _LABEL.sub(" ", title)).split())


def series_filename(filename: str) -> tuple[str, tuple[int, int]] | None:
    """파일 이름 → (정규화 제목 틀, (시즌, 번호)). 애매한 복수 번호는 제외한다.

    명시적인 표기가 없을 때는 구분자로 분리된 1~3자리 숫자 하나만 인정한다.
    따라서 연도·해상도·제목 중간의 숫자를 화 번호로 추측하지 않는다.
    """
    stem = unicodedata.normalize("NFKC", Path(filename).stem)
    stem = _LABEL.sub(" ", stem)
    matches = list(_NUMBER.finditer(stem))
    if matches:
        if len(matches) != 1:
            return None
        match = matches[0]
        season = int(match["season"] or 1)
        number = int(match["episode"] or match["korean"] or match["english"])
    else:
        matches = list(re.finditer(r"(?<![^\W_])\d{1,3}(?![^\W_])", stem))
        if len(matches) != 1:
            return None
        match = matches[0]
        season, number = 1, int(match[0])
    if number < 1 or season < 1:
        return None
    title = normalize_series_title(stem[:match.start()] + " " + stem[match.end():])
    return title, (season, number)


def adjacent_video(video_id: int, video_ids: tuple[int, ...], *, forward: bool) -> int | None:
    """목록 경계에서는 이동하지 않는다. 목록에 현재 영상이 없으면 역시 그대로 둔다."""
    try:
        index = video_ids.index(video_id) + (1 if forward else -1)
    except ValueError:
        return None
    return video_ids[index] if 0 <= index < len(video_ids) else None


class SeriesStore:
    def __init__(self, connect):
        self._connect = connect
        with connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    folder TEXT,
                    title_template TEXT,
                    edited INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(folder, title_template)
                );
                CREATE TABLE IF NOT EXISTS series_videos (
                    series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
                    video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
                    position INTEGER NOT NULL,
                    PRIMARY KEY(series_id, position)
                );
                CREATE TABLE IF NOT EXISTS series_overrides (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id)
                );
            """)

    def list(self) -> tuple[Series, ...]:
        with self._connect() as db:
            db.execute("BEGIN")  # 검사와 겹쳐도 시리즈·영상 순서는 같은 스냅샷으로 읽는다.
            members = defaultdict(list)
            for row in db.execute("SELECT * FROM series_videos ORDER BY position"):
                members[row["series_id"]].append(row["video_id"])
            return tuple(Series(row["id"], row["name"], tuple(members[row["id"]]), bool(row["edited"]))
                         for row in db.execute("SELECT * FROM series ORDER BY name, id"))

    def for_video(self, video_id: int) -> Series | None:
        return next((series for series in self.list() if video_id in series.video_ids), None)

    @staticmethod
    def _write_members(db, series_id, video_ids):
        db.execute("DELETE FROM series_videos WHERE series_id=?", (series_id,))
        db.executemany("INSERT INTO series_videos VALUES (?, ?, ?)",
                       ((series_id, video_id, position) for position, video_id in enumerate(video_ids)))

    def edit(self, series_id: int | None, name: str, video_ids: tuple[int, ...]) -> Series:
        video_ids = tuple(video_ids)
        name = name.strip()
        if not name:
            raise ValueError("시리즈 이름을 입력하세요.")
        if len(set(video_ids)) != len(video_ids):
            raise ValueError("같은 영상을 시리즈에 두 번 넣을 수 없습니다.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if series_id is not None and not db.execute("SELECT 1 FROM series WHERE id=?", (series_id,)).fetchone():
                raise ValueError("시리즈를 찾을 수 없습니다.")
            for video_id in video_ids:
                if not db.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone():
                    raise ValueError("영상을 찾을 수 없습니다.")
                other = db.execute("SELECT series_id FROM series_videos WHERE video_id=?", (video_id,)).fetchone()
                if other and other[0] != series_id:
                    raise ValueError("다른 시리즈에서 먼저 영상을 빼 주세요.")
            if series_id is None:
                series_id = db.execute("INSERT INTO series (name, edited) VALUES (?, 1)", (name,)).lastrowid
            old = [row[0] for row in db.execute("SELECT video_id FROM series_videos WHERE series_id=?", (series_id,))]
            db.executemany("INSERT OR IGNORE INTO series_overrides VALUES (?)", ((v,) for v in set(old) | set(video_ids)))
            db.execute("UPDATE series SET name=?, edited=1 WHERE id=?", (name, series_id))
            self._write_members(db, series_id, video_ids)
        return Series(series_id, name, video_ids, True)

    def regroup(self, videos) -> None:
        groups = defaultdict(list)
        for video in videos:
            if not video.locations:
                continue
            path = min((loc.path for loc in video.locations), key=lambda p: (str(p).casefold(), str(p)))
            parsed = series_filename(path.name)
            if parsed is not None:
                title, number = parsed
                groups[(str(path.parent).casefold(), title)].append((number, video.id, path.parent.name))
        valid_groups = {}
        for key, candidates in groups.items():
            counts = Counter(number for number, _, _ in candidates)
            valid_groups[key] = sorted((number, vid) for number, vid, _ in candidates if counts[number] == 1)
        with self._connect() as db:
            # 검사 작업자와 편집 화면이 겹쳐도 사용자 결정을 읽고 쓰는 단위를 보장한다.
            db.execute("BEGIN IMMEDIATE")
            rows = list(db.execute("SELECT * FROM series"))
            existing = {(row["folder"], row["title_template"]): row for row in rows}
            protected = {row[0] for row in db.execute("SELECT video_id FROM series_overrides")}
            db.execute("DELETE FROM series_videos WHERE series_id IN (SELECT id FROM series WHERE edited=0)")
            for row in rows:
                if row["edited"]:
                    valid_ids = {vid for _, vid in valid_groups.get((row["folder"], row["title_template"]), ())}
                    ids = [r[0] for r in db.execute("SELECT video_id FROM series_videos WHERE series_id=? ORDER BY position", (row["id"],))]
                    # 편집 후 자동으로 들어온 화에는 아직 사용자 결정이 없다.
                    # 뒤늦게 중복 번호/다른 기준 위치가 생기면 이 화만 재계산한다.
                    self._write_members(db, row["id"], [vid for vid in ids if vid in protected or vid in valid_ids])
            assigned = {row[0] for row in db.execute("SELECT video_id FROM series_videos")}
            retained = set()
            for key, candidates in sorted(groups.items()):
                valid = valid_groups[key]
                row = existing.get(key)
                if row and row["edited"]:
                    ids = [r[0] for r in db.execute("SELECT video_id FROM series_videos WHERE series_id=? ORDER BY position", (row["id"],))]
                    numbers = {vid: number for number, vid in valid}
                    for number, vid in valid:
                        if vid in protected or vid in assigned:
                            continue
                        preceding = [(numbers[v], v) for v in ids if v in numbers and numbers[v] < number]
                        index = ids.index(max(preceding)[1]) + 1 if preceding else len(ids)
                        ids.insert(index, vid)
                        assigned.add(vid)
                    self._write_members(db, row["id"], ids)
                    continue
                ids = [vid for _, vid in valid if vid not in protected and vid not in assigned]
                if len(ids) < 2:
                    continue
                series_id = row["id"] if row else db.execute(
                    "INSERT INTO series (name, folder, title_template) VALUES (?, ?, ?)",
                    (key[1] or candidates[0][2], *key)).lastrowid
                self._write_members(db, series_id, ids)
                assigned.update(ids)
                retained.add(series_id)
            for row in rows:
                if not row["edited"] and row["id"] not in retained:
                    db.execute("DELETE FROM series WHERE id=?", (row["id"],))
