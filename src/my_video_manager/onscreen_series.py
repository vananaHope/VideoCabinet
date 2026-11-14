"""시리즈 영역: 시리즈의 화에 같은 화면 자막 영역을 복사하고, 시리즈 영역을 고치거나 지우면 시리즈에서 온 화만 따른다.

화(영상)의 영역 묶음은 직접 정함 또는 시리즈에서 옴(RegionOrigin) 하나다. 시리즈에서 온 화의 영역은 시리즈 영역의
복사본이고, 복사본은 시리즈 영역 ID로 그 시리즈 영역을 가리킨다. 여러 화의 영역과 줄을 바꾸는 일은 한 트랜잭션에서 한다.
영역은 화면 비율이라 해상도가 다른 화에도 그대로 복사한다.
"""

from contextlib import contextmanager
from dataclasses import dataclass

from .onscreen_subtitles import (OnScreenRegionChanged, OnScreenSubtitleQueueEntry, RegionRect, insert_region,
                                 reread_region)


def migrate_onscreen_series(db) -> None:
    """v11: 시리즈 영역과 화면 자막 영역의 시리즈 영역 ID(없으면 직접 정함). 이전과 최초 생성이 공유한다.

    시리즈 표는 SeriesStore가 이전 단계 밖에서 만든다. 외래 키는 쓸 때 검사하므로 시리즈 표가 아직 없는 최초 생성에서도
    만들 수 있다. 시리즈가 지워지면 시리즈 영역도 지워지고, 시리즈 영역이 지워지면 복사본은 직접 정함으로 남는다.
    기존 영역은 모두 직접 정함이다.
    """
    db.execute("""CREATE TABLE series_onscreen_regions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
        x REAL NOT NULL, y REAL NOT NULL, width REAL NOT NULL, height REAL NOT NULL,
        language TEXT NOT NULL,
        created_at TEXT NOT NULL)""")
    db.execute("CREATE INDEX series_onscreen_regions_series ON series_onscreen_regions(series_id)")
    db.execute("ALTER TABLE onscreen_subtitle_regions ADD COLUMN series_region_id INTEGER "
               "REFERENCES series_onscreen_regions(id) ON DELETE SET NULL")
    db.execute("CREATE INDEX onscreen_subtitle_regions_series ON onscreen_subtitle_regions(series_region_id)")


@dataclass(frozen=True)
class OnScreenSeriesImpact:
    """시리즈 영역을 더하거나 고치거나 지우면 바뀌는 범위. 확인 창이 보이고, 바꾸는 순간 그대로인지 대조한다.

    other_videos는 지금 화를 뺀, 영역이 바뀌는 다른 화 수다. reviewed_line_count는 지금 화를 포함해 그 변경으로
    사라질 검수로 고친 줄 수의 합이다. replaces_existing은 이미 있는 시리즈 영역을 고치거나 지우거나 통째로 바꾸는지
    (그래서 시리즈에서 온 화가 줄을 잃을 수 있어 확인 창을 거치는지)다.
    """
    other_videos: int
    reviewed_line_count: int
    replaces_existing: bool


class OnScreenSeriesChanged(OnScreenRegionChanged):
    """확인 창이 보인 뒤 시리즈 영역 변경의 범위(다른 화 수, 사라질 검수 줄 수)가 달라졌다. 아무것도 바꾸지 않았다.
    impact는 지금 상태다."""

    def __init__(self, impact: OnScreenSeriesImpact):
        self.impact = impact
        super().__init__(impact.reviewed_line_count)
        self.args = ("그 사이 시리즈의 화면 자막 영역이 바뀌었습니다. 바뀐 안내를 다시 확인하세요.",)


NOT_IN_SERIES = "시리즈에 속한 영상에서만 시리즈 전체에 적용할 수 있습니다."


@dataclass(frozen=True)
class _SeriesState:
    """한 시리즈의 시리즈 영역과 화마다의 출처. 영향 범위 계산과 적용이 같은 판정을 쓴다."""
    series_id: int
    regions: tuple  # 시리즈 영역 행(ID 순서)
    linked: dict  # 시리즈에서 온 화 → {시리즈 영역 ID: 그 화의 영역 ID}
    empty: tuple  # 영역이 없는 화(제외 영상 빼고, 시리즈 순서)


def _state(db, video_id) -> _SeriesState:
    row = db.execute("SELECT series_id FROM series_videos WHERE video_id = ?", (video_id,)).fetchone()
    if row is None:
        raise ValueError(NOT_IN_SERIES)
    series_id = row[0]
    linked = {}
    for region in db.execute("SELECT r.video_id, r.series_region_id, r.id FROM onscreen_subtitle_regions r "
                             "JOIN series_onscreen_regions sr ON sr.id = r.series_region_id "
                             "WHERE sr.series_id = ? ORDER BY r.id", (series_id,)):
        linked.setdefault(region[0], {})[region[1]] = region[2]
    empty = tuple(row[0] for row in db.execute(
        "SELECT sv.video_id FROM series_videos sv JOIN videos v ON v.id = sv.video_id "
        "WHERE sv.series_id = ? AND v.excluded = 0 AND NOT EXISTS "
        "(SELECT 1 FROM onscreen_subtitle_regions r WHERE r.video_id = sv.video_id) ORDER BY sv.position", (series_id,)))
    regions = tuple(db.execute("SELECT * FROM series_onscreen_regions WHERE series_id = ? ORDER BY id", (series_id,)))
    return _SeriesState(series_id, regions, linked, empty)


def _rect(row) -> RegionRect:
    return RegionRect(row["x"], row["y"], row["width"], row["height"])


class OnScreenSeriesRegions:
    """시리즈 영역의 적용·고치기·지우기와 시리즈 소속이 바뀐 뒤의 맞추기."""

    def __init__(self, connect, clock, store, reviewed_line_count):
        self._connect = connect
        self._clock = clock
        self._store = store  # 화면 자막 저장소(OnScreenSubtitles): 영상 하나의 읽기 요청과 진행 중 읽기 취소
        self._reviewed = reviewed_line_count  # (영역 ID, connection=db) → 검수로 고친 줄 수 또는 None

    def _lost(self, db, region_ids) -> int:
        return sum(self._reviewed(region_id, connection=db) or 0 for region_id in region_ids)

    def _video_region_ids(self, db, video_id) -> list[int]:
        return [row[0] for row in db.execute("SELECT id FROM onscreen_subtitle_regions WHERE video_id = ? ORDER BY id",
                                             (video_id,))]

    # 영향 범위

    def _plan(self, db, video_id, region_id=None, *, delete=False):
        """(시리즈 상태, 이 변경으로 영역이 바뀌는 다른 화, 사라질 영역 ID들, 지금 화가 시리즈에서 왔는지, 기존 시리즈 영역을
        바꾸는지). 영향 범위와 적용이 이 판정 하나를 쓴다."""
        state = _state(db, video_id)
        current = state.linked.get(video_id)
        if region_id is not None:
            row = db.execute("SELECT video_id, series_region_id FROM onscreen_subtitle_regions WHERE id = ?",
                             (region_id,)).fetchone()
            if row is None or row["video_id"] != video_id:
                raise ValueError("화면 자막 영역이 바뀌었습니다. 영역 정하기를 다시 여세요.")
            linked_region = row["series_region_id"] if current and row["series_region_id"] in current else None
        if delete or (region_id is not None and linked_region is not None):
            # 시리즈 영역 하나를 고치거나 지운다: 시리즈에서 온 화마다 그 영역의 복사본만 바뀐다.
            if region_id is None or linked_region is None:
                raise ValueError("시리즈에서 온 영역이 아닙니다.")
            others = [w for w in state.linked if w != video_id]
            lost = [regions[linked_region] for regions in state.linked.values() if linked_region in regions]
            return state, others, lost, True, True
        if current:
            # 시리즈에서 온 화에 새 영역: 시리즈 영역에 하나를 더한다. 잃는 것이 없다.
            others = [w for w in (*state.linked, *state.empty) if w != video_id]
            return state, others, [], True, False
        # 직접 정한 화(또는 영역 없는 화)의 묶음을 시리즈 영역으로 삼는다. 이미 있던 시리즈 영역은 통째로 바뀐다.
        others = [w for w in (*state.linked, *state.empty) if w != video_id]
        lost = [rid for w in state.linked if w != video_id for rid in state.linked[w].values()]
        if region_id is not None:
            lost.append(region_id)  # 고친 영역은 지금 화에서도 다시 읽는다.
        return state, others, lost, False, bool(state.regions)

    def impact(self, video_id, region_id=None, *, delete=False, connection=None) -> OnScreenSeriesImpact:
        """지금 화(video_id)에서 시리즈 전체에 적용하면 바뀌는 범위. region_id가 없으면 새 영역, 있으면 그 영역 고치기
        (delete면 지우기)다."""
        def read(db):
            _, others, lost, _, replaces = self._plan(db, video_id, region_id, delete=delete)
            return OnScreenSeriesImpact(len(others), self._lost(db, lost), replaces)
        if connection is not None:
            return read(connection)
        with self._connect() as db:
            db.execute("BEGIN")  # 화마다의 출처와 검수 수를 같은 스냅샷에서 센다.
            return read(db)

    @contextmanager
    def _writing(self, video_id, region_id=None, *, delete=False, expected=None):
        """영향받는 화의 진행 중 읽기를 멈추고 쓰기 트랜잭션 하나를 연다. 중간에 실패하면 아무것도 바뀌지 않는다.
        확인 창이 본 범위(expected)와 지금 범위가 다르면 아무것도 바꾸지 않고 OnScreenSeriesChanged를 던진다."""
        with self._connect() as db:
            _, others, *_ = self._plan(db, video_id, region_id, delete=delete)
        for touched in (video_id, *others):
            self._store.cancel_reading(touched)  # 쓰기 트랜잭션 전에 부른다(처리 쪽은 _activity 안에서 DB를 쓴다).
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if expected is not None:
                current = self.impact(video_id, region_id, delete=delete, connection=db)
                if current != expected:
                    raise OnScreenSeriesChanged(current)
            yield db

    # 적용·고치기·지우기

    def add(self, video_id, rect: RegionRect, language: str, *, expected=None) -> OnScreenSubtitleQueueEntry:
        """지금 화에 영역 하나를 더하고 시리즈 전체에 적용한다. 지금 화는 직접 요청, 다른 화는 자동 대상이다."""
        self._store.check_region(rect, language)
        with self._writing(video_id, expected=expected) as connection:
            state, others, _, from_series, _ = self._plan(connection, video_id)
            now = self._clock().isoformat()
            if from_series:
                added = self._new_series_region(connection, state.series_id, rect, language, now)
                insert_region(connection, video_id, rect, language, now, added)
                for other in others:
                    if other in state.linked:
                        insert_region(connection, other, rect, language, now, added)
                    else:
                        self._copy_all(connection, state.series_id, other, now)
                    self._store.request_reading(connection, other, now, automatic=True)
            else:
                insert_region(connection, video_id, rect, language, now)
                self._adopt(connection, state, video_id, others, now)
            return self._store.request_reading(connection, video_id, now)

    def update(self, region_id, rect: RegionRect, language: str, *, video_id,
               expected=None) -> OnScreenSubtitleQueueEntry:
        """영역 하나를 고치고 시리즈 전체에 적용한다. 시리즈 영역이면 시리즈에서 온 화마다 그 영역만 다시 읽고, 직접 정한
        화의 영역이면 그 화의 묶음이 시리즈 영역이 된다."""
        self._store.check_region(rect, language)
        with self._writing(video_id, region_id, expected=expected) as connection:
            state, others, _, from_series, _ = self._plan(connection, video_id, region_id)
            now = self._clock().isoformat()
            reread_region(connection, region_id, rect, language)
            if from_series:
                series_region = connection.execute("SELECT series_region_id FROM onscreen_subtitle_regions "
                                                   "WHERE id = ?", (region_id,)).fetchone()[0]
                connection.execute("UPDATE series_onscreen_regions SET x = ?, y = ?, width = ?, height = ?, "
                                   "language = ? WHERE id = ?", (*_values(rect), language, series_region))
                for other in others:
                    copy = state.linked[other].get(series_region)
                    if copy is None:
                        insert_region(connection, other, rect, language, now, series_region)
                    else:
                        reread_region(connection, copy, rect, language)
                    self._store.request_reading(connection, other, now, automatic=True)
            else:
                self._adopt(connection, state, video_id, others, now)
            return self._store.request_reading(connection, video_id, now)

    def delete(self, region_id, *, video_id, expected=None) -> None:
        """시리즈 영역 하나를 지운다. 시리즈에서 온 모든 화에서 그 영역과 화면 자막·화면 번역 자막·검수 기록을 지운다."""
        with self._writing(video_id, region_id, delete=True, expected=expected) as connection:
            state, others, _, _, _ = self._plan(connection, video_id, region_id, delete=True)
            now = self._clock().isoformat()
            series_region = connection.execute("SELECT series_region_id FROM onscreen_subtitle_regions WHERE id = ?",
                                               (region_id,)).fetchone()[0]
            for video in (video_id, *others):
                copy = state.linked[video].get(series_region)
                if copy is not None:
                    connection.execute("DELETE FROM onscreen_subtitle_regions WHERE id = ?", (copy,))
                self._store.settle_reading(connection, video, now, automatic=video != video_id)
            connection.execute("DELETE FROM series_onscreen_regions WHERE id = ?", (series_region,))

    def _new_series_region(self, db, series_id, rect, language, now) -> int:
        return db.execute("INSERT INTO series_onscreen_regions(series_id, x, y, width, height, language, created_at) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?)", (series_id, *_values(rect), language, now)).lastrowid

    def _copy_all(self, db, series_id, video_id, now) -> None:
        for row in db.execute("SELECT * FROM series_onscreen_regions WHERE series_id = ? ORDER BY id",
                              (series_id,)).fetchall():
            insert_region(db, video_id, _rect(row), row["language"], now, row["id"])

    def _adopt(self, db, state, video_id, others, now) -> None:
        """지금 화의 영역 묶음을 시리즈 영역으로 삼는다. 시리즈에서 온 다른 화는 이전 시리즈 영역(과 그 줄·검수)을 잃고,
        영역이 없는 화와 함께 새 묶음을 받아 자동 대상으로 들어간다. 지금 화의 영역은 줄·검수를 그대로 둔 채 시리즈에서 옴이
        된다."""
        for other in state.linked:
            if other != video_id:
                db.execute("DELETE FROM onscreen_subtitle_regions WHERE video_id = ?", (other,))
        db.execute("DELETE FROM series_onscreen_regions WHERE series_id = ?", (state.series_id,))
        for row in db.execute("SELECT * FROM onscreen_subtitle_regions WHERE video_id = ? ORDER BY id",
                              (video_id,)).fetchall():
            added = self._new_series_region(db, state.series_id, _rect(row), row["language"], now)
            db.execute("UPDATE onscreen_subtitle_regions SET series_region_id = ? WHERE id = ?", (added, row["id"]))
        for other in others:
            self._copy_all(db, state.series_id, other, now)
            self._store.request_reading(db, other, now, automatic=True)


def _values(rect: RegionRect) -> tuple[float, float, float, float]:
    return round(rect.x, 6), round(rect.y, 6), round(rect.width, 6), round(rect.height, 6)
