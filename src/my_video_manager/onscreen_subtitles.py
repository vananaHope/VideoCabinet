"""화면 자막: 영역 저장, 영상 전체 미리 훑기, 줄 합치기와 세대 저장.

영역 이미지는 영상 읽기 어댑터(RegionFrameReader)가, 글자 읽기는 OCR 엔진(OcrEngine)이 맡는다.
이 모듈은 어느 엔진 구현도 직접 참조하지 않는다(ADR-0006).
"""

from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
import json
import math
from pathlib import Path
import re
from threading import Event, Lock
from typing import Iterable, Iterator, Protocol, Sequence
from uuid import uuid4

from .subtitle_queue_kind import ONSCREEN_SUBTITLE
from .translation_source import ONSCREEN


# 영역마다 초당 4장을 읽는다. 줄의 시작·끝 오차는 한 장 간격(0.25초) 안이다.
SAMPLES_PER_SECOND = 4
# 앞뒤 줄이 같은 글자일 때 그 사이에서 다르게 읽힌 장이 이 수 이하이면 잡음으로 보고 앞뒤 줄을 잇는다.
NOISE_SAMPLES = 2
# 이 장 수보다 짧게 보인 줄(0.75초 미만)은 전환 중 잘못 읽힌 것으로 보고 버린다.
MIN_LINE_SAMPLES = 3
# 이웃한 두 줄의 글자가 이 비율 이상 같고(예: "Goodby for now"와 "Goodbye for now") 한쪽이 JITTER_SAMPLES장
# (1초) 이하로만 보였으면 OCR이 같은 자막을 잠깐 다르게 읽은 것으로 보고 한 줄로 잇는다. 둘 다 그보다 오래
# 보였으면("Player 1 wins"·"Player 2 wins") 서로 다른 자막이다. "Round 1"·"Round 2"처럼 짧은 글자의 한 자 차이도 다른 줄이다.
SIMILAR_TEXT_RATIO = 0.9
JITTER_SAMPLES = 4
# 같은 그림 판정: 밝기가 이 값보다 크게 바뀐 화소가 영역 화소의 1/5000 이하이면 앞 그림과 같다고 본다.
# 압축 잡음은 넘기고, 글자 하나가 바뀌는 정도의 변화는 놓치지 않는 값이다.
CHANGED_PIXEL_DELTA = 24
CHANGED_PIXEL_RATIO = 1 / 5000
# 영역의 가로·세로 최소 비율. 이보다 좁으면 글자를 읽을 수 없다.
MIN_REGION_SIZE = 0.01

# 읽을 언어 후보. 한국어 글자는 번역할 필요가 없어 고를 수 없다.
ONSCREEN_LANGUAGES = (
    ("en", "영어"), ("ja", "일본어"), ("zh-Hans", "중국어(간체)"), ("zh-Hant", "중국어(번체)"),
    ("es", "스페인어"), ("fr", "프랑스어"), ("de", "독일어"), ("it", "이탈리아어"),
    ("pt", "포르투갈어"), ("ru", "러시아어"),
)
_LANGUAGE_NAMES = dict(ONSCREEN_LANGUAGES)
# 원어(받아쓰기 언어 코드)에서 고를 읽을 언어. 중국어 원어는 간체를 기본으로 한다.
_SPOKEN_TO_ONSCREEN = {"zh": "zh-Hans"}

NO_TEXT_NOTICE = "읽은 글자가 없습니다. 영역과 읽을 언어를 확인하세요."
RETRY_GUIDANCE = "대기열의 '실패 항목 모두 재시도'로 다시 시도하세요"
_ERROR_MESSAGES = {
    "language": "읽을 언어의 언어 팩이 없어 화면 글자를 읽지 못했습니다.",
    "other": "화면 자막을 만들지 못했습니다. 자세한 내용을 확인하세요.",
}


def onscreen_language_name(language: str) -> str:
    return _LANGUAGE_NAMES.get(language, language)


def default_onscreen_language(spoken_language: str | None) -> str | None:
    """읽을 언어의 기본값은 원어다. 원어가 한국어이거나 모르거나 후보에 없으면 사용자가 직접 고른다."""
    if spoken_language is None:
        return None
    language = _SPOKEN_TO_ONSCREEN.get(spoken_language, spoken_language)
    return language if language in _LANGUAGE_NAMES else None


@dataclass(frozen=True)
class RegionRect:
    """영상 프레임(회전을 반영한 표시 방향) 기준 비율 사각형. 해상도가 달라도 같은 자리를 가리킨다."""
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self):
        values = (self.x, self.y, self.width, self.height)
        if (not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
                or self.x < 0 or self.y < 0 or self.width < MIN_REGION_SIZE or self.height < MIN_REGION_SIZE
                or self.x + self.width > 1 + 1e-9 or self.y + self.height > 1 + 1e-9):
            raise ValueError("화면 자막 영역은 영상 화면 안에서 가로·세로 1% 이상으로 정하세요.")


@dataclass(frozen=True)
class OnScreenSubtitleRegion:
    id: int
    video_id: int
    rect: RegionRect
    language: str


@dataclass(frozen=True)
class RegionImage:
    """영역 이미지 한 장. 8비트 회색조, 행 우선, 한 행은 width 바이트다."""
    width: int
    height: int
    pixels: bytes

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0 or len(self.pixels) != self.width * self.height:
            raise ValueError("영역 이미지의 크기와 화소 수가 맞지 않습니다.")


class RegionFrameReader(Protocol):
    def region_frames(self, path: Path, region: RegionRect, *, fps: float,
                      cancellation: Event) -> Iterator[tuple[float, RegionImage]]:
        """영상 전체에서 영역만 잘라 (영상 시각 초, 영역 이미지)를 시각 순서로 내보낸다.

        이미지는 디스크에 쓰지 않는다. 취소 신호를 받으면 곧 멈춘다. 읽지 못하면 RuntimeError를 던진다.
        """
        ...


class OcrEngine(Protocol):
    """OCR 엔진 경계: 영역 이미지와 읽을 언어 → 글자, 언어 → 언어 팩 사용 가능 여부."""

    def read_text(self, image: RegionImage, language: str) -> str:
        """읽은 글자. 여러 줄이면 줄바꿈으로 잇고, 글자가 없으면 빈 문자열이다."""
        ...

    def language_available(self, language: str) -> bool:
        ...

    def missing_language_guidance(self, language: str) -> str:
        """언어 팩이 없을 때 설치 방법 안내."""
        ...


class OcrLanguageUnavailable(ValueError):
    def __init__(self, language: str, guidance: str):
        self.language = language
        super().__init__(f"읽을 언어 {onscreen_language_name(language)}({language})의 언어 팩이 없어 "
                         f"화면 글자를 읽을 수 없습니다. {guidance}".strip())


@dataclass(frozen=True)
class OnScreenSubtitleLine:
    id: str
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class OnScreenSubtitle:
    """영역 하나의 현재 세대."""
    region: OnScreenSubtitleRegion
    id: str
    created_at: datetime
    lines: tuple[OnScreenSubtitleLine, ...]

    @property
    def no_text(self) -> bool:
        return not self.lines


@dataclass(frozen=True)
class OnScreenSubtitleQueueEntry:
    id: int
    video_id: int
    requested_at: datetime
    state: str
    error: str | None
    error_detail: str | None = None
    progress: float = 0.0
    retry_guidance: str | None = None
    # 완료한 작업의 줄 수. 0이면 읽은 글자 없음이다.
    line_count: int | None = None
    queue_kind: str = ONSCREEN_SUBTITLE

    @property
    def no_text(self) -> bool:
        return self.state == "completed" and self.line_count == 0

    @property
    def notice(self) -> str:
        return f"화면 자막 {self.line_count}줄" if self.state == "completed" and self.line_count else ""


def normalize_onscreen_text(text: str) -> str:
    """줄마다 앞뒤와 연속 공백을 정리하고 빈 줄을 없앤다. 같은 글자 판정과 저장이 같은 값을 쓴다."""
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


def images_similar(first: RegionImage, second: RegionImage) -> bool:
    """바로 앞에서 읽은 그림과 거의 같으면 OCR을 건너뛰고 앞의 결과를 이어 쓴다."""
    if (first.width, first.height) != (second.width, second.height):
        return False
    import numpy
    a = numpy.frombuffer(first.pixels, dtype=numpy.uint8).astype(numpy.int16)
    b = numpy.frombuffer(second.pixels, dtype=numpy.uint8).astype(numpy.int16)
    changed = int(numpy.count_nonzero(numpy.abs(a - b) > CHANGED_PIXEL_DELTA))
    return changed <= a.size * CHANGED_PIXEL_RATIO


def merge_samples(samples: Sequence[tuple[float, str]],
                  fps: float = SAMPLES_PER_SECOND) -> tuple[tuple[float, float, str], ...]:
    """시각 순서의 (시각, 정규화한 글자)를 (시작, 끝, 글자) 줄로 합친다.

    1. 같은 글자가 이어지는 장을 한 덩어리로 묶는다.
    2. 앞뒤 덩어리가 같은 글자이고 그 사이 NOISE_SAMPLES장 이하만 다르게 읽혔으면 잇는다.
    3. 이웃한 덩어리의 글자가 거의 같고(SIMILAR_TEXT_RATIO 이상) 한쪽이 JITTER_SAMPLES장 이하이면 잇는다.
       OCR이 같은 자막의 글자 한둘을 잠깐 다르게 읽는 경우다. 줄의 글자는 가장 많은 장에서 읽힌 글자다.
       둘 다 오래 보인 덩어리는 글자가 비슷해도 서로 다른 자막으로 둔다. 흡수 뒤 대표 글자가 같아진 이웃은
       길이와 관계없이 잇는다.
    4. 빈 글자와 MIN_LINE_SAMPLES장보다 짧은 줄은 버린다.
    시작은 처음 보인 장의 시각, 끝은 마지막으로 보인 장의 다음 장 시각이다.
    """
    runs = []  # [장별 글자 수, 첫 장, 끝 장]
    for index, (_, text) in enumerate(samples):
        if runs and samples[index - 1][1] == text:
            runs[-1][0][text] += 1
            runs[-1][2] = index
        else:
            runs.append([Counter({text: 1}), index, index])
    index = 1
    while index < len(runs) - 1:
        before, run, after = runs[index - 1], runs[index], runs[index + 1]
        if run[2] - run[1] + 1 <= NOISE_SAMPLES and _run_text(before) == _run_text(after):
            before[0].update(after[0])  # 잡음으로 읽힌 글자는 줄의 글자를 정하는 데 세지 않는다.
            before[2] = after[2]
            del runs[index:index + 2]
            index = max(1, index - 1)
        else:
            index += 1
    index = 1
    while index < len(runs):
        before, run = _run_text(runs[index - 1]), _run_text(runs[index])
        shorter = min(runs[index - 1][2] - runs[index - 1][1], runs[index][2] - runs[index][1]) + 1
        # 흔들림을 흡수해 대표 글자가 같아진 이웃은 길이와 관계없이 같은 줄이다. 길이 제한은 서로 다른 글자에만 둔다.
        if before and run and (before == run or shorter <= JITTER_SAMPLES
                               and SequenceMatcher(None, before, run).ratio() >= SIMILAR_TEXT_RATIO):
            runs[index - 1][0].update(runs[index][0])
            runs[index - 1][2] = runs[index][2]
            del runs[index]
        else:
            index += 1
    interval = 1 / fps
    lines = []
    for run in runs:
        text, (_, first, last) = _run_text(run), run
        if text and last - first + 1 >= MIN_LINE_SAMPLES:
            end = samples[last + 1][0] if last + 1 < len(samples) else samples[last][0] + interval
            lines.append((samples[first][0], end, text))
    return tuple(lines)


def _run_text(run) -> str:
    """덩어리에서 가장 많은 장에서 읽힌 글자. 같은 수면 먼저 읽힌 글자다."""
    return run[0].most_common(1)[0][0]


ONSCREEN_TABLES = (
    """CREATE TABLE IF NOT EXISTS onscreen_subtitle_regions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER NOT NULL REFERENCES videos(id),
        x REAL NOT NULL, y REAL NOT NULL, width REAL NOT NULL, height REAL NOT NULL,
        language TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS onscreen_subtitle_regions_video ON onscreen_subtitle_regions(video_id)",
    """CREATE TABLE IF NOT EXISTS onscreen_subtitles (
        region_id INTEGER PRIMARY KEY REFERENCES onscreen_subtitle_regions(id) ON DELETE CASCADE,
        id TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS onscreen_subtitle_lines (
        id TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL REFERENCES onscreen_subtitles(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        start REAL NOT NULL,
        end REAL NOT NULL,
        text TEXT NOT NULL,
        UNIQUE(generation_id, ordinal))""",
)


def create_onscreen_tables(db) -> None:
    """이전(v8)과 최초 생성이 같은 구조를 쓴다. 트랜잭션 안에서도 부를 수 있게 문장 단위로 실행한다."""
    for statement in ONSCREEN_TABLES:
        db.execute(statement)


class _Cancelled(Exception):
    """취소는 실패가 아니다. 요청은 대기로 돌아간다."""


class OnScreenSubtitles:
    """화면 자막 영역과 세대, 그리고 자막 대기열의 화면 자막 작업."""

    def __init__(self, connect, clock, frames: RegionFrameReader | None, ocr: OcrEngine | None,
                 playback_location, order):
        self._connect = connect
        self._clock = clock
        self._frames = frames
        self._ocr = ocr
        self._playback_location = playback_location
        self._order = order
        self.translations = None
        self._processing = Lock()
        self._cancellation = Event()
        self._activity = Lock()
        self._active_video = None
        self._active_cancellation = None
        self._progress = {}
        with connect() as db:
            create_onscreen_tables(db)
            # 앱이 처리 도중 끝났으면 다음 실행에서 처음부터 다시 읽는다.
            db.execute("UPDATE subtitle_queue SET state = 'queued' WHERE state = 'reading' AND kind = ?",
                       (ONSCREEN_SUBTITLE,))

    # 영역

    def language_available(self, language: str) -> bool:
        return self._ocr is not None and self._ocr.language_available(language)

    def _check_language(self, language):
        if language not in _LANGUAGE_NAMES:
            raise ValueError("읽을 언어를 고르세요. 한국어 글자는 번역할 필요가 없어 고를 수 없습니다.")
        if self._ocr is None:
            raise RuntimeError("화면 글자를 읽을 OCR 엔진이 설정되지 않았습니다.")
        if not self._ocr.language_available(language):
            raise OcrLanguageUnavailable(language, self._ocr.missing_language_guidance(language))

    def regions(self, video_id: int, *, connection=None) -> tuple[OnScreenSubtitleRegion, ...]:
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            return tuple(_region(row) for row in db.execute(
                "SELECT * FROM onscreen_subtitle_regions WHERE video_id = ? ORDER BY id", (video_id,)))

    def set_regions(self, video_id: int, regions: Iterable[tuple[RegionRect, str]]) -> OnScreenSubtitleQueueEntry:
        """영상의 영역 목록을 바꾸고 화면 자막 만들기를 직접 요청으로 대기열에 넣는다.

        이전 영역과 그 화면 자막은 지운다. 읽을 언어의 언어 팩이 없으면 아무것도 바꾸지 않는다.
        """
        regions = tuple(regions)
        if not regions:
            raise ValueError("화면 자막 영역을 하나 이상 정하세요.")
        for rect, language in regions:
            if not isinstance(rect, RegionRect):
                raise ValueError("화면 자막 영역이 올바르지 않습니다.")
            self._check_language(language)
        with self._activity:
            if self._active_video == video_id and self._active_cancellation:
                self._active_cancellation.set()  # 이전 영역으로 읽던 결과는 저장하지 않는다.
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone():
                raise ValueError("영상을 찾을 수 없습니다.")
            now = self._clock().isoformat()
            db.execute("DELETE FROM onscreen_subtitle_regions WHERE video_id = ?", (video_id,))
            db.executemany("INSERT INTO onscreen_subtitle_regions(video_id, x, y, width, height, language, created_at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)",
                           [(video_id, round(rect.x, 6), round(rect.y, 6), round(rect.width, 6),
                             round(rect.height, 6), language, now) for rect, language in regions])
            self._order.request(db, video_id, kind=ONSCREEN_SUBTITLE, renew=True)
            db.execute("DELETE FROM subtitle_queue WHERE video_id = ? AND kind = ?", (video_id, ONSCREEN_SUBTITLE))
            cursor = db.execute("INSERT INTO subtitle_queue(video_id, spoken_language, requested_at, kind) "
                                "VALUES (?, NULL, ?, ?)", (video_id, now, ONSCREEN_SUBTITLE))
            return self._entry(db.execute("SELECT * FROM subtitle_queue WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def subtitles(self, video_id: int) -> tuple[OnScreenSubtitle, ...]:
        """영역마다 현재 세대. 아직 읽지 않은 영역은 없다."""
        with self._connect() as db:
            db.execute("BEGIN")  # 세대와 줄을 같은 읽기 스냅샷에서 읽는다.
            result = []
            for region in self.regions(video_id, connection=db):
                row = db.execute("SELECT * FROM onscreen_subtitles WHERE region_id = ?", (region.id,)).fetchone()
                if row is None:
                    continue
                lines = tuple(OnScreenSubtitleLine(line["id"], line["start"], line["end"], line["text"])
                              for line in db.execute("SELECT * FROM onscreen_subtitle_lines WHERE generation_id = ? "
                                                     "ORDER BY ordinal", (row["id"],)))
                result.append(OnScreenSubtitle(region, row["id"], datetime.fromisoformat(row["created_at"]), lines))
            return tuple(result)

    # 대기열

    def _entry(self, row, **updates) -> OnScreenSubtitleQueueEntry:
        message, detail = row["error"], None
        if message:
            try:
                error = json.loads(message)
                message = _ERROR_MESSAGES.get(error["kind"], _ERROR_MESSAGES["other"])
                detail = error["detail"]
            except (ValueError, TypeError, KeyError):
                pass
        values = dict(id=row["id"], video_id=row["video_id"], requested_at=datetime.fromisoformat(row["requested_at"]),
                      state=row["state"], error=message, error_detail=detail,
                      progress=self._progress.get(row["id"], 0.0), retry_guidance=RETRY_GUIDANCE if message else None)
        values.update(updates)
        return OnScreenSubtitleQueueEntry(**values)

    def queue(self) -> tuple[OnScreenSubtitleQueueEntry, ...]:
        with self._connect() as db:
            entries = tuple(self._entry(row) for row in db.execute(
                "SELECT * FROM subtitle_queue WHERE kind = ? ORDER BY id", (ONSCREEN_SUBTITLE,)))
        return self._order.sort(entries)

    def remove(self, video_id: int) -> None:
        with self._activity:
            with self._connect() as db:
                db.execute("DELETE FROM subtitle_queue WHERE video_id = ? AND kind = ?", (video_id, ONSCREEN_SUBTITLE))
            if self._active_video == video_id and self._active_cancellation:
                self._active_cancellation.set()

    def retry_failed(self, queue_id: int) -> None:
        with self._connect() as db:
            row = db.execute("SELECT video_id FROM subtitle_queue WHERE id = ? AND kind = ? AND state = 'failed'",
                             (queue_id, ONSCREEN_SUBTITLE)).fetchone()
        if row is None:
            raise ValueError("실패한 화면 자막 요청이 바뀌었습니다.")
        # 위치 확인은 사라진 파일을 정리할 수 있으므로 쓰기 트랜잭션 밖에서 한다.
        self._playback_location(row["video_id"])
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM subtitle_queue WHERE id = ? AND kind = ? AND state = 'failed'",
                             (queue_id, ONSCREEN_SUBTITLE)).fetchone()
            if row is None:
                raise ValueError("실패한 화면 자막 요청이 바뀌었습니다.")
            self._order.request(db, row["video_id"], kind=ONSCREEN_SUBTITLE, renew=True)
            db.execute("UPDATE subtitle_queue SET state = 'queued', error = NULL, requested_at = ? WHERE id = ?",
                       (self._clock().isoformat(), queue_id))

    def resume_processing(self) -> None:
        self._cancellation.clear()

    def stop_processing(self) -> None:
        """현재 처리를 멈춘다. 멈춘 작업은 대기로 돌아가 다음 실행에서 처음부터 읽는다."""
        self._cancellation.set()
        with self._activity:
            if self._active_cancellation:
                self._active_cancellation.set()

    def process_next(self) -> OnScreenSubtitleQueueEntry | None:
        # 작업자는 하나다. 재진입 호출은 기다리거나 중복 실행하지 않는다.
        if self._cancellation.is_set() or not self._processing.acquire(blocking=False):
            return None
        pending = None
        try:
            pending = next((entry for entry in self.queue() if entry.state == "queued"), None)
            if pending is None:
                return None
            with self._activity:
                with self._connect() as db:
                    changed = db.execute("UPDATE subtitle_queue SET state = 'reading' WHERE id = ? AND state = 'queued'",
                                         (pending.id,)).rowcount
                    duration = db.execute("SELECT duration FROM videos WHERE id = ?", (pending.video_id,)).fetchone()[0]
                self._active_video = pending.video_id
                cancellation = self._active_cancellation = Event()
                if self._cancellation.is_set():
                    cancellation.set()
            if not changed:
                return None
            try:
                lines = self._read(pending, duration, cancellation)
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if self._cancellation.is_set() or cancellation.is_set():
                        raise _Cancelled
                    # 처리 중 영역을 바꿨거나 대기열에서 뺐으면 이전 영역의 결과로 덮어쓰지 않는다.
                    if not db.execute("SELECT 1 FROM subtitle_queue WHERE id = ?", (pending.id,)).fetchone():
                        return pending
                    now = self._clock().isoformat()
                    for region_id, region_lines in lines.items():
                        generation = uuid4().hex
                        db.execute("DELETE FROM onscreen_subtitles WHERE region_id = ?", (region_id,))
                        db.execute("INSERT INTO onscreen_subtitles(region_id, id, created_at) VALUES (?, ?, ?)",
                                   (region_id, generation, now))
                        db.executemany("INSERT INTO onscreen_subtitle_lines VALUES (?, ?, ?, ?, ?, ?)",
                                       [(uuid4().hex, generation, ordinal, start, end, text)
                                        for ordinal, (start, end, text) in enumerate(region_lines)])
                    db.execute("DELETE FROM subtitle_queue WHERE id = ?", (pending.id,))
                    if self.translations is not None:
                        self.translations.request(pending.video_id, automatic=True, connection=db, source=ONSCREEN)
                return OnScreenSubtitleQueueEntry(pending.id, pending.video_id, pending.requested_at, "completed", None,
                                                  progress=1.0, line_count=sum(map(len, lines.values())))
            except _Cancelled:
                with self._connect() as db:
                    db.execute("UPDATE subtitle_queue SET state = 'queued' WHERE id = ? AND state = 'reading'",
                               (pending.id,))
                return pending
            except Exception as error:
                kind = "language" if isinstance(error, OcrLanguageUnavailable) else "other"
                detail = str(error) or type(error).__name__
                with self._connect() as db:
                    db.execute("UPDATE subtitle_queue SET state = 'failed', error = ? WHERE id = ?",
                               (json.dumps({"kind": kind, "detail": detail}, ensure_ascii=False), pending.id))
                return OnScreenSubtitleQueueEntry(pending.id, pending.video_id, pending.requested_at, "failed",
                                                  _ERROR_MESSAGES[kind], detail, retry_guidance=RETRY_GUIDANCE)
        finally:
            with self._activity:
                self._active_video = self._active_cancellation = None
            if pending is not None:
                self._progress.pop(pending.id, None)
            self._processing.release()

    def _read(self, pending, duration, cancellation) -> dict[int, tuple[tuple[float, float, str], ...]]:
        """아직 세대가 없는 영역을 차례로 훑어 영역별 줄을 만든다. DB는 잠그지 않는다."""
        if self._frames is None or self._ocr is None:
            raise RuntimeError("화면 자막 어댑터가 설정되지 않았습니다.")
        with self._connect() as db:
            regions = tuple(region for region in self.regions(pending.video_id, connection=db)
                            if not db.execute("SELECT 1 FROM onscreen_subtitles WHERE region_id = ?",
                                              (region.id,)).fetchone())
        path = self._playback_location(pending.video_id).path
        result = {}
        for index, region in enumerate(regions):
            if not self._ocr.language_available(region.language):
                raise OcrLanguageUnavailable(region.language, self._ocr.missing_language_guidance(region.language))
            samples, anchor, text = [], None, ""
            for seconds, image in self._frames.region_frames(path, region.rect, fps=SAMPLES_PER_SECOND,
                                                             cancellation=cancellation):
                if cancellation.is_set():
                    break
                if anchor is None or not images_similar(anchor, image):
                    text = normalize_onscreen_text(self._ocr.read_text(image, region.language))
                    anchor = image
                samples.append((seconds, text))
                done = (index + min(1.0, seconds / max(duration, 0.001))) / len(regions)
                self._progress[pending.id] = min(0.99, max(0.0, done))
            if cancellation.is_set():
                raise _Cancelled
            result[region.id] = merge_samples(samples)
        return result


def _region(row) -> OnScreenSubtitleRegion:
    return OnScreenSubtitleRegion(row["id"], row["video_id"], RegionRect(row["x"], row["y"], row["width"], row["height"]),
                                  row["language"])
