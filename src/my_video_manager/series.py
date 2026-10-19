"""시리즈 번호·제목 틀의 순수 계산과 자동 묶기, 사용자 편집 저장."""

from collections import Counter, defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from .viewing import ViewingStatus


@dataclass(frozen=True)
class Series:
    id: int
    name: str
    video_ids: tuple[int, ...]
    edited: bool = False


# 해상도/코덱은 번호 후보에서 먼저 빼고, 그 외 숫자를 임의로 추측하지 않는다.
_LABEL = re.compile(r"(?<![a-z0-9])(?:\d{3,4}[pi]|[248]k|[hx][ ._-]?26[45]|hevc|avc|av1|xvid|aac|ac3|dts)(?![a-z0-9])", re.I)
_METADATA = re.compile(r"\[[^\]]*\]|\([^)]*\)|(?<![\w])(?:\d{4}|\d{6}|[a-f0-9]{8})(?![\w])", re.I)
_CRC = re.compile(r"(?<![a-z0-9])[a-f0-9]{8}(?![a-z0-9])", re.I)
_NUMBER = re.compile(
    r"(?<!\d)(?P<week>\d+)\s*주차\s*(?:제\s*)?(?P<lecture>\d+)\s*강(?![가-힣])"
    r"|(?<![a-z0-9])s(?P<season>\d+)\s*e(?P<episode>\d+)(?![a-z0-9])"
    r"|(?<!\d)(?:제\s*)?(?P<korean>\d+)\s*(?:강|화|회)(?![가-힣])"
    r"|(?<![a-z0-9])(?:episode|lecture|part|ep|e)\s*[._-]?\s*(?P<english>\d+)(?![a-z0-9])",
    re.I,
)


def normalize_series_title(title: str) -> str:
    """대소문자·공백·구분자를 통일하고 알려진 기술 꼬리표를 제거한다."""
    title = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(re.sub(r"[\W_]+", " ", _LABEL.sub(" ", _METADATA.sub(" ", title))).split())


def series_filename(filename: str) -> tuple[str, tuple[int, int]] | None:
    """파일 이름 → (번호 앞의 정규화 제목 틀, (시즌/주차, 번호)).

    명시적인 표기를 우선하고, 없으면 꼬리표 제거 후 독립된 번호 하나를 쓴다.
    화별 부제는 키에 넣지 않는다. 다중 화 표기와 모호한 복수 번호는 제외한다.
    """
    parsed = _filename_parts(filename)
    return (normalize_series_title(parsed[0]), parsed[1]) if parsed else None


def _filename_parts(filename: str) -> tuple[str, tuple[int, int], bool] | None:
    # 인덱스가 원문을 가리키도록 꼬리표는 같은 길이의 공백으로 가린다.
    # \d는 전각 숫자도 인식하며 표시 이름은 원문 그대로 남긴다.
    stem = Path(filename).stem
    # E로 시작하는 CRC도 회차 표기로 오인하지 않는다.
    matches = list(_NUMBER.finditer(_CRC.sub(lambda m: " " * len(m[0]), stem)))
    explicit = bool(matches)
    if matches:
        if len(matches) != 1:
            return None
        match = matches[0]
        season = int(match["week"] or match["season"] or 1)
        number = int(match["lecture"] or match["episode"] or match["korean"] or match["english"])
    else:
        masked = _METADATA.sub(lambda m: " " * len(m[0]), stem)
        masked = _LABEL.sub(lambda m: " " * len(m[0]), masked)
        matches = list(re.finditer(r"(?<![^\W_])\d{1,3}(?![^\W_])", masked))
        if len(matches) != 1:
            return None
        match = matches[0]
        season, number = 1, int(match[0])
    prefix = stem[:match.start()].strip(" ._-–—")
    if season < 1 or (number == 0 and (explicit or normalize_series_title(prefix))):
        return None
    return prefix, (season, number), explicit


def consecutive_series_numbers(numbers) -> bool:
    """맨 번호 묶음은 0/1부터 시작하고 중간 누락 번호가 하나 이하여야 한다."""
    numbers = sorted(set(numbers))
    return bool(numbers) and numbers[0] in (0, 1) and numbers[-1] - numbers[0] + 1 - len(numbers) <= 1


def adjacent_video(video_id: int, video_ids: tuple[int, ...], *, forward: bool) -> int | None:
    """목록 경계에서는 이동하지 않는다. 목록에 현재 영상이 없으면 역시 그대로 둔다."""
    try:
        index = video_ids.index(video_id) + (1 if forward else -1)
    except ValueError:
        return None
    return video_ids[index] if 0 <= index < len(video_ids) else None


def next_episode(video_ids: tuple[int, ...],
                 watched: Mapping[int, ViewingStatus] | Collection[int]) -> int | None:
    """시청(틀어보기 제외)이 있는 가장 뒤 화의 바로 다음 화. 없거나 마지막 화면 None.

    `watched`는 영상별 `ViewingStatus`이거나, 틀어보기가 아닌 시청이 있는 영상 ID 모음이다.
    건너뛴 중간 화는 시청이 없으므로 다음 볼 화가 되지 않는다.
    """
    if isinstance(watched, Mapping):
        seen = {video_id for video_id, status in watched.items() if status.finished or status.abandoned}
    else:
        seen = set(watched)
    for index in reversed(range(len(video_ids))):
        if video_ids[index] in seen:
            return video_ids[index + 1] if index + 1 < len(video_ids) else None
    return video_ids[0] if video_ids else None


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
                CREATE TABLE IF NOT EXISTS series_order_changes (
                    series_id INTEGER PRIMARY KEY REFERENCES series(id) ON DELETE CASCADE
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

    def edit(self, series_id: int | None, name: str, video_ids: tuple[int, ...], *,
             preserved_video_ids: set[int] | frozenset[int] = frozenset()) -> Series:
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
            old = [row[0] for row in db.execute("SELECT video_id FROM series_videos WHERE series_id=? ORDER BY position", (series_id,))]
            # 화면에 없는 구성원은 기존 순번에 남긴다. 보이는 구성원의 편집만 반영한다.
            merged = list(video_ids)
            for index, vid in enumerate(old):
                if vid in preserved_video_ids:
                    merged.insert(min(index, len(merged)), vid)
            video_ids = tuple(merged)
            common = set(old) & set(video_ids)
            if [vid for vid in old if vid in common] != [vid for vid in video_ids if vid in common]:
                # 넣기·빼기는 순서 변경이 아니다. 남아 있는 영상의 상대 순서만 비교한다.
                db.execute("INSERT OR IGNORE INTO series_order_changes VALUES (?)", (series_id,))
            db.executemany("INSERT OR IGNORE INTO series_overrides VALUES (?)", ((v,) for v in set(old) | set(video_ids)))
            db.execute("UPDATE series SET name=?, edited=1 WHERE id=?", (name, series_id))
            self._write_members(db, series_id, video_ids)
        return Series(series_id, name, video_ids, True)

    def regroup(self, videos) -> None:
        groups = defaultdict(list)
        missing = {video.id for video in videos if not video.locations or video.excluded}
        for video in videos:
            if video.id in missing:
                continue
            path = min((loc.path for loc in video.locations), key=lambda p: (str(p).casefold(), str(p)))
            parsed = _filename_parts(path.name)
            if parsed is not None:
                prefix, number, explicit = parsed
                title = normalize_series_title(prefix)
                display = " ".join(re.sub(r"\[[^\]]*\]", " ", prefix).split()).strip(" ._-–—")
                groups[(str(path.parent).casefold(), title)].append((number, video.id, display if title else path.parent.name, explicit))
        valid_groups = {}
        for key, candidates in groups.items():
            counts = Counter(number for number, _, _, _ in candidates)
            valid = sorted((number, vid) for number, vid, _, _ in candidates if counts[number] == 1)
            if (not key[1] and not any(explicit for _, _, _, explicit in candidates)
                    and not consecutive_series_numbers(number[1] for number, _ in valid)):
                valid = []
            valid_groups[key] = valid
        with self._connect() as db:
            # 검사 작업자와 편집 화면이 겹쳐도 사용자 결정을 읽고 쓰는 단위를 보장한다.
            db.execute("BEGIN IMMEDIATE")
            rows = list(db.execute("SELECT * FROM series"))
            existing = {(row["folder"], row["title_template"]): row for row in rows}
            protected = {row[0] for row in db.execute("SELECT video_id FROM series_overrides")}
            reordered = {row[0] for row in db.execute("SELECT series_id FROM series_order_changes")}
            # 파일 없음/제외는 영상 기록을 지우는 명령이 아니다. 기존 위치의 순서도 기억한다.
            missing_members = {row["id"]: [(index, vid) for index, vid in enumerate(
                r[0] for r in db.execute("SELECT video_id FROM series_videos WHERE series_id=? ORDER BY position", (row["id"],)))
                if vid in missing] for row in rows}
            db.execute("DELETE FROM series_videos WHERE series_id IN (SELECT id FROM series WHERE edited=0)")
            for row in rows:
                if not row["edited"]:
                    self._write_members(db, row["id"], [vid for _, vid in missing_members[row["id"]]])
            for row in rows:
                if row["edited"]:
                    valid_ids = {vid for _, vid in valid_groups.get((row["folder"], row["title_template"]), ())}
                    ids = [r[0] for r in db.execute("SELECT video_id FROM series_videos WHERE series_id=? ORDER BY position", (row["id"],))]
                    # 편집 후 자동으로 들어온 화에는 아직 사용자 결정이 없다.
                    # 뒤늦게 중복 번호/다른 기준 위치가 생기면 이 화만 재계산한다.
                    self._write_members(db, row["id"], [vid for vid in ids if vid in protected or vid in valid_ids or vid in missing])
            assigned = {row[0] for row in db.execute("SELECT video_id FROM series_videos")}
            retained = {sid for sid, members in missing_members.items() if members}
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
                        if not preceding and row["id"] not in reordered:
                            following = [(numbers[v], v) for v in ids if v in numbers and numbers[v] > number]
                            if following:
                                index = ids.index(min(following)[1])
                        ids.insert(index, vid)
                        assigned.add(vid)
                    self._write_members(db, row["id"], ids)
                    continue
                ids = [vid for _, vid in valid if vid not in protected and vid not in assigned]
                if row:
                    for index, vid in missing_members[row["id"]]:
                        ids.insert(min(index, len(ids)), vid)
                if len(ids) < 2:
                    continue
                named = [c for c in candidates if c[1] in ids]
                display_name = min(named)[2] if named else row["name"]
                series_id = row["id"] if row else db.execute(
                    "INSERT INTO series (name, folder, title_template) VALUES (?, ?, ?)",
                    (display_name, *key)).lastrowid
                db.execute("UPDATE series SET name=? WHERE id=?", (display_name, series_id))
                self._write_members(db, series_id, ids)
                assigned.update(ids)
                retained.add(series_id)
            for row in rows:
                if not row["edited"] and row["id"] not in retained:
                    db.execute("DELETE FROM series WHERE id=?", (row["id"],))
