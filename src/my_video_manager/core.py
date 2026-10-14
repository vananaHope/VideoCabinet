"""UI/재생 엔진과 독립된 앱 코어의 공개 경계."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import math
from pathlib import Path
import sqlite3
from typing import Callable, Mapping

from .library import Library, Location, MediaInfo, MediaReader, ScanIssue, ScanResult, Video, WatchedFolder
from .settings import Settings
from .highlights import Highlight, Highlights
from .key_bindings import KeyBinding, KeyBindings
from .hidden_gems import HiddenGem, HiddenGems, select_hidden_gems
from .playback import PlaybackHub
from .reel import HighlightReel, ReelEntry, ReelPlayback, ReelSettings
from .revisit import Revisits
from .series import Series, SeriesStore, adjacent_video
from .search import Search, SearchResponse
from .tags import Tag, Tags
from .viewing import Viewing, ViewingRecorder, ViewingSettings, ViewingStatus, ViewingStore, viewing_status
from .subtitles import Subtitles, Transcriber, Transcript, SubtitleQueueEntry, transcript_srt
from .translation import Translator, Translations, Translation, TranslationQueueEntry, SubtitleSelection
from .subtitle_queue import AutoSubtitleRules, QueueOrder, SubtitleQueue, SubtitleRetryResult, SubtitleRetrySkipped
from .review import Review, ReviewPlayback, SubtitleExport


class CommandType(str, Enum):
    TOGGLE_PAUSE = "toggle_pause"
    SEEK = "seek"
    CHANGE_SPEED = "change_speed"
    POINT_HIGHLIGHT = "point_highlight"
    RANGE_HIGHLIGHT = "range_highlight"
    PREVIOUS_HIGHLIGHT = "previous_highlight"
    NEXT_HIGHLIGHT = "next_highlight"
    TOGGLE_SUBTITLES = "toggle_subtitles"
    PREVIOUS_VIDEO = "previous_video"
    NEXT_VIDEO = "next_video"
    TOGGLE_SUBTITLE_LANGUAGE = "toggle_subtitle_language"
    TOGGLE_REEL_REPEAT = "toggle_reel_repeat"


@dataclass(frozen=True)
class Command:
    kind: CommandType
    amount: float = 0


DEFAULT_KEY_BINDINGS = {
    "Enter": Command(CommandType.TOGGLE_PAUSE),
    "Left": Command(CommandType.SEEK, -5),
    "Right": Command(CommandType.SEEK, 5),
    ",": Command(CommandType.SEEK, -3),
    "Up": Command(CommandType.CHANGE_SPEED, 0.25),
    "Down": Command(CommandType.CHANGE_SPEED, -0.25),
    "Insert": Command(CommandType.POINT_HIGHLIGHT),
    "Delete": Command(CommandType.RANGE_HIGHLIGHT),
    "Home": Command(CommandType.PREVIOUS_HIGHLIGHT),
    "End": Command(CommandType.NEXT_HIGHLIGHT),
    "/": Command(CommandType.TOGGLE_SUBTITLES),
    "PgUp": Command(CommandType.PREVIOUS_VIDEO),
    "PgDn": Command(CommandType.NEXT_VIDEO),
    ".": Command(CommandType.TOGGLE_SUBTITLE_LANGUAGE),
    "\\": Command(CommandType.TOGGLE_REEL_REPEAT),
}

MIN_PLAYBACK_SPEED = 0.25
MAX_PLAYBACK_SPEED = 100


def playback_speed(current: float, change: float) -> float:
    return max(MIN_PLAYBACK_SPEED, min(MAX_PLAYBACK_SPEED, current + change))


def default_data_directory() -> Path:
    return Path.home() / ".my-video-manager"


@dataclass(frozen=True)
class LibrarySnapshot:
    """한 번의 목록 갱신에서 공유하는 영상·시청·태그·시리즈 조회 결과."""
    videos: tuple[Video, ...]
    statuses: dict[int, ViewingStatus]
    tags: dict[int, tuple[Tag, ...]]
    series: tuple[Series, ...]


class AppCore:
    def __init__(
        self,
        *,
        media: MediaReader,
        clock: Callable[[], datetime],
        database: Path | None = None,
        key_bindings: Mapping[str, Command] | None = None,
        viewing_settings: ViewingSettings | None = None,
        transcriber: Transcriber | None = None,
        translator: Translator | None = None,
        translation_batch_size: int = 30,
        reel_settings: ReelSettings | None = None,
    ):
        self.database = (Path(database) if database is not None else default_data_directory() / "library.sqlite3").resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._thumbnails = self.database.parent / "thumbnails"
        self._thumbnails.mkdir(exist_ok=True)
        self._media = media
        self._clock = clock
        self.settings = Settings(self._connect)
        self._keys = KeyBindings(self.settings, DEFAULT_KEY_BINDINGS, tuple(Command(kind) for kind in CommandType))
        if key_bindings is not None:
            self._keys.replace(key_bindings, persist=False)
        # 접속은 호출 단위로 열어 UI 작업자 스레드에서도 코어를 사용할 수 있다.
        self._library = Library(self._connect, media, clock, self._thumbnails, self.settings,
                                on_registered=lambda video_id: self._auto_subtitle_rules.apply(video_id))

        self.playback = PlaybackHub()
        self._series = SeriesStore(self._connect)
        self._highlights = Highlights(self._connect, on_created=lambda db, hid:
                                      self._hidden_gems.record_highlight_created(db, hid))
        self._hidden_gems = HiddenGems(self._connect, clock, self.settings)
        self._tags = Tags(self._connect)
        self.playback.subscribe(self._highlights)
        self._highlight_commands = {
            CommandType.POINT_HIGHLIGHT: self._highlights.add_point,
            CommandType.RANGE_HIGHLIGHT: self._highlights.toggle_range,
            CommandType.PREVIOUS_HIGHLIGHT: lambda: self._highlights.adjacent(forward=False),
            CommandType.NEXT_HIGHLIGHT: lambda: self._highlights.adjacent(forward=True),
        }
        self._viewings = ViewingStore(self._connect, clock, viewing_settings or ViewingSettings())
        self.playback.subscribe(ViewingRecorder(self._start_viewing, self._viewings.report, self._viewings.end))
        self._queue_order = QueueOrder(self._connect)
        self._subtitles = Subtitles(self._connect, clock, transcriber, self.playback_location, self._queue_order)
        self._review = Review(self._connect, clock, self._subtitles, self.playback_location, self._queue_order)
        self._subtitles.review = self._review
        self._translations = Translations(self._connect, clock, self._subtitles, self.settings, translator,
                                          batch_size=translation_batch_size, order=self._queue_order,
                                          protected_lines=self._review.protected_lines)
        self._review.translations = self._translations
        self._auto_subtitle_rules = AutoSubtitleRules(self._connect, self)
        self._subtitle_queue = SubtitleQueue(self, self._queue_order)
        self._subtitle_selection = SubtitleSelection(self._translations)
        self.playback.subscribe(self._subtitle_selection)
        self._revisits = Revisits(self._connect, clock)
        self._reel = HighlightReel(self.playback, self.videos, self.all_highlights,
                                   self._revisits, reel_settings or ReelSettings())
        self.playback.subscribe(self._reel)
        self._search = Search(self._connect)

    @property
    def translation_cli(self) -> str:
        return self._translations.cli

    def review_lines(self, video_id):
        return self._review.lines(video_id)

    def reviewed_line_count(self, video_id):
        return self._review.reviewed_count(video_id)

    def subtitle_regeneration_warning(self, video_id):
        return self._review.regeneration_warning(video_id)

    def edit_transcript_line(self, video_id, line_id, text, *, overwrite_reviewed=False):
        self._review.edit(video_id, line_id, text, overwrite_reviewed=overwrite_reviewed)

    def edit_translation_line(self, video_id, line_id, text):
        self._review.edit(video_id, line_id, text, translated=True)

    def request_subtitle_range(self, video_id, start, end):
        return self._review.request_range(video_id, start, end)

    def subtitle_range_bounds(self, video_id, start, end):
        return self._review.range_bounds(video_id, start, end)

    def subtitle_export(self, video_id, *, translated=False) -> SubtitleExport:
        return self._review.export(video_id, translated=translated)

    def write_subtitle_export(self, export: SubtitleExport, path: Path):
        """확인한 스냅샷을 사용자가 고른 경로에만 쓴다. Windows 인식을 위해 UTF-8 BOM 사용."""
        Path(path).write_text(export.text, encoding="utf-8-sig")

    def review_line_position(self, video_id, line_id):
        line = next((line for line in self.review_lines(video_id) if line.original.id == line_id), None)
        if line is None:
            raise ValueError("자막 줄이 바뀌었습니다. 목록을 새로 확인하세요.")
        self.playback_location(video_id)
        return line.original.start

    def play_review_line(self, video_id, line_id) -> ReviewPlayback:
        start = self.review_line_position(video_id, line_id)
        session = self.playback.session
        if session and session.video_id == video_id and session.record_viewing and self.reel_playback is None:
            return ReviewPlayback(video_id, start, "seek")
        self.playback.start(video_id, start, record_viewing=True)
        return ReviewPlayback(video_id, start, "play")

    def set_translation_cli(self, cli: str) -> None:
        self._translations.set_cli(cli)

    def request_translation(self, video_id: int, line_ids=None) -> TranslationQueueEntry | None:
        """전체 또는 지정한 원어 줄 ID만 번역한다. 실패/보류 재요청은 완료한 묶음을 유지한다."""
        return self._translations.request(video_id, line_ids)

    def translation(self, video_id: int) -> Translation | None:
        return self._translations.translation(video_id)

    def translation_queue(self) -> tuple[TranslationQueueEntry, ...]:
        return self._translations.queue()

    def translation_ready(self) -> bool:
        return self._translations.ready() is not None

    def process_next_translation(self) -> TranslationQueueEntry | None:
        with self._subtitle_queue.processing():
            result = self._translations.process_next()
            self._subtitle_queue.record(result)
            return result

    def stop_translation_processing(self) -> None:
        self._translations.stop_processing()

    def toggle_subtitle_language(self) -> tuple[bool, str]:
        return self._subtitle_selection.toggle()

    def reel_entries(self, tag_id: int | None = None) -> tuple[ReelEntry, ...]:
        return self._reel.list(tag_id)

    def start_reel(self, tag_id: int | None = None,
                      highlight_id: int | None = None) -> ReelPlayback | None:
        return self._reel.start(tag_id, highlight_id)

    @property
    def reel_playback(self) -> ReelPlayback | None:
        return self._reel.current

    @property
    def reel_repeat(self) -> bool:
        return self._reel.repeat

    def advance_reel_if_due(self, *, eof: bool = False) -> None:
        """위치 보고가 모든 리스너에 전달된 뒤 모아보기의 다음 재생 지시를 확정한다."""
        self._execute_reel_transition(lambda: self._reel.advance_if_due(eof=eof))

    def _execute_reel_transition(self, transition) -> None:
        previous = self.reel_playback
        translated = self._subtitle_selection.translated
        transition()
        current = self.reel_playback
        if previous and current and current.action == "seek" and previous.video_id == current.video_id:
            # 항목별 재생 수명주기는 닫되, 같은 영상의 자막 선택은 엔진과 함께 유지한다.
            self._subtitle_selection.translated = translated

    def last_highlight_revisited_at(self, highlight_id: int) -> datetime | None:
        return self._revisits.last_for_highlight(highlight_id)

    def last_video_revisited_at(self, video_id: int) -> datetime | None:
        """해당 영상의 남아 있는 하이라이트 중 가장 최근 복습 시각. 미복습은 None."""
        return self._revisits.last_for_video(video_id)

    def search(self, query: str) -> SearchResponse:
        return self._search.find(query, self.videos())

    def prepare_search(self) -> None:
        self._search.prepare()

    @property
    def search_index_ready(self) -> bool:
        return self._search.ready

    def library_snapshot(self) -> LibrarySnapshot:
        videos = self.videos()
        visible = {v.id for v in videos}
        series = tuple(replace(s, video_ids=tuple(vid for vid in s.video_ids if vid in visible))
                       for s in self._series.list())
        return LibrarySnapshot(videos, self.viewing_status_map(), self.video_tags_map(), series)

    def hidden_gems(self, *, snapshot: LibrarySnapshot | None = None) -> tuple[HiddenGem, ...]:
        snapshot = self.library_snapshot() if snapshot is None else snapshot
        return select_hidden_gems(
            snapshot.videos, snapshot.statuses, snapshot.tags, snapshot.series,
            self._hidden_gems.dismissed_ids(), self._hidden_gems.revisit_times(), now=self._clock(),
            unwatched_days=self._hidden_gems.days("unwatched"), revisit_days=self._hidden_gems.days("revisit"))

    def dismiss_video(self, video_id: int) -> None:
        self._hidden_gems.set_dismissed(video_id, True)

    def restore_dismissed_video(self, video_id: int) -> None:
        self._hidden_gems.set_dismissed(video_id, False)

    def dismissed_videos(self) -> tuple[Video, ...]:
        ids = self._hidden_gems.dismissed_ids()
        return tuple(v for v in self.videos() + self.excluded_videos() if v.id in ids)

    def request_subtitles(self, video_id: int, spoken_language: str | None = None) -> SubtitleQueueEntry:
        self.playback_location(video_id)
        return self._subtitles.request(video_id, spoken_language)

    def request_automatic_subtitles(self, video_id, spoken_language=None):
        return self._subtitles.request(video_id, spoken_language, automatic=True)

    def auto_subtitle_rules(self):
        return self._auto_subtitle_rules.list()

    def auto_subtitle_candidates(self, *, folder=None, tag_id=None):
        return self._auto_subtitle_rules.candidates(folder=folder, tag_id=tag_id)

    def set_auto_subtitle_rule(self, *, folder=None, tag_id=None, spoken_language=None, include_existing=False):
        return self._auto_subtitle_rules.set(folder=folder, tag_id=tag_id, spoken_language=spoken_language,
                                            include_existing=include_existing)

    def remove_auto_subtitle_rule(self, rule_id):
        self._auto_subtitle_rules.remove(rule_id)

    def subtitle_queue_items(self):
        return self._subtitle_queue.items()

    def remove_from_subtitle_queue(self, video_id):
        self._subtitles.remove(video_id)
        self._translations.remove(video_id)
        self._subtitle_queue.hide(video_id)

    def promote_subtitle(self, video_id):
        if not any(e.video_id == video_id for e in (*self.subtitle_queue(), *self.translation_queue())):
            raise ValueError("대기열에 없는 영상입니다.")
        self._queue_order.promote(video_id)

    def retry_failed_subtitles(self):
        failed = [e for e in self.subtitle_queue() if e.state == "failed"]
        translated = [e for e in self.translation_queue() if e.state == "failed"]
        retried, skipped = set(), []
        for entries, request in ((failed, lambda e: self._subtitles.retry_failed(e.id)),
                                 (translated, lambda e: self.request_translation(e.video_id))):
            for entry in entries:
                try:
                    request(entry)
                    retried.add(entry.video_id)
                except (ValueError, OSError, RuntimeError) as error:
                    skipped.append(SubtitleRetrySkipped(entry.video_id, str(error)))
        return SubtitleRetryResult(len(retried), tuple(skipped))

    def resume_subtitle_processing(self):
        self._subtitles.resume_processing()
        self._translations.resume_processing()

    def take_subtitle_queue_completion(self):
        return self._subtitle_queue.take_completion()

    def acknowledge_tray_notice(self) -> bool:
        if self.settings.get("subtitle_queue.tray_notice_shown", False):
            return False
        self.settings.set("subtitle_queue.tray_notice_shown", True)
        return True

    def subtitle_queue(self) -> tuple[SubtitleQueueEntry, ...]:
        return self._subtitles.queue()

    def process_next_subtitle(self) -> SubtitleQueueEntry | None:
        with self._subtitle_queue.processing():
            result = self._subtitles.process_next()
            if result and result.state == "completed":
                self._translations.enqueue_eligible()
            self._subtitle_queue.record(result)
            return result

    def stop_subtitle_processing(self) -> None:
        self._subtitles.stop_processing()

    def transcript(self, video_id: int) -> Transcript | None:
        return self._subtitles.transcript(video_id)

    def has_transcript(self, video_id: int) -> bool:
        return self._subtitles.has_transcript(video_id)

    def playback_subtitle(self, video_id: int) -> Path | None:
        transcript = self.transcript(video_id)
        translated = self._subtitle_selection.video_id == video_id and self._subtitle_selection.translated
        if translated:
            translation = self.translation(video_id)
            if translation is not None:
                transcript = translation
            else:
                self._subtitle_selection.translated = False
                translated = False
        if transcript is None or not transcript.lines:
            return None
        directory = self.database.parent / "playback-subtitles"
        directory.mkdir(exist_ok=True)
        path = directory / f"{video_id}{'-ko' if translated else ''}.srt"
        path.write_text(transcript_srt(transcript), encoding="utf-8")
        return path

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # sqlite3의 context manager는 commit/rollback만 하므로 명시적으로 닫는다.
        return _Connection(connection)

    def set_key_bindings(self, bindings: Mapping[str, Command]) -> None:
        self._keys.replace(bindings)

    def key_bindings(self) -> tuple[KeyBinding, ...]:
        return self._keys.rows()

    def save_key_bindings(self, bindings: Mapping[Command, tuple[str, ...]]) -> None:
        self._keys.save(bindings)

    def reset_key_bindings(self, command: Command | None = None) -> None:
        self._keys.reset(command)

    def command_for_key(self, key: str) -> Command | None:
        return self._keys.command_for_key(key)

    def highlights(self, video_id: int) -> tuple[Highlight, ...]:
        return self._highlights.list(video_id)

    def all_highlights(self, tag_id: int | None = None) -> tuple[Highlight, ...]:
        return self._highlights.list_all() if tag_id is None else self.highlights_for_tag(tag_id)

    def tags(self, prefix: str = "") -> tuple[Tag, ...]:
        """정규화된 이름의 접두어로 자동 완성한다. 빈 접두어는 모든 태그다."""
        return self._tags.list(prefix)

    def create_tag(self, name: str) -> Tag:
        return self._tags.create(name)

    def rename_tag(self, tag_id: int, name: str) -> Tag:
        return self._tags.rename(tag_id, name)

    def delete_tag(self, tag_id: int) -> None:
        self._tags.delete(tag_id)

    def video_tags(self, video_id: int) -> tuple[Tag, ...]:
        return self._tags.attached("video", video_id)

    def video_tags_map(self) -> dict[int, tuple[Tag, ...]]:
        return self._tags.video_tags_map()

    def highlight_tags(self, highlight_id: int) -> tuple[Tag, ...]:
        return self._tags.attached("highlight", highlight_id)

    def add_video_tag(self, video_id: int, name: str) -> Tag:
        attached = {tag.id for tag in self.video_tags(video_id)}
        tag = self._tags.attach("video", video_id, name)
        if tag.id not in attached:
            self._auto_subtitle_rules.apply(video_id, tag_id=tag.id)
        return tag

    def add_highlight_tag(self, highlight_id: int, name: str) -> Tag:
        return self._tags.attach("highlight", highlight_id, name)

    def remove_video_tag(self, video_id: int, tag_id: int) -> None:
        self._tags.detach("video", video_id, tag_id)

    def remove_highlight_tag(self, highlight_id: int, tag_id: int) -> None:
        self._tags.detach("highlight", highlight_id, tag_id)

    def videos_for_tag(self, tag_id: int) -> tuple[Video, ...]:
        """영상 자체에 붙인 태그로 조회한다. 하이라이트 태그는 포함하지 않는다."""
        ids = self._tags.video_ids(tag_id)
        return tuple(video for video in self.videos() if video.id in ids)

    def highlights_for_tag(self, tag_id: int) -> tuple[Highlight, ...]:
        return self._highlights.list_by_ids(self._tags.highlight_ids(tag_id))

    def update_highlight(self, highlight_id: int, *, start: float, end: float | None,
                         note: str) -> Highlight:
        return self._highlights.update(highlight_id, start=start, end=end, note=note)

    def delete_highlight(self, highlight_id: int) -> None:
        self._highlights.delete(highlight_id)

    @property
    def open_highlight_start(self) -> float | None:
        return self._highlights.open_start

    def is_highlight_command(self, command: Command) -> bool:
        return (command.kind in self._highlight_commands
                or command.kind == CommandType.TOGGLE_REEL_REPEAT)

    def execute_highlight_command(self, command: Command) -> float | None:
        """하이라이트 명령을 적용하고, 탐색할 때만 목표 시각을 반환한다."""
        if command.kind == CommandType.TOGGLE_REEL_REPEAT:
            self._reel.toggle_repeat()
            return None
        if self.reel_playback is not None and command.kind in (
                CommandType.PREVIOUS_HIGHLIGHT, CommandType.NEXT_HIGHLIGHT):
            self._execute_reel_transition(
                lambda: self._reel.adjacent(forward=command.kind == CommandType.NEXT_HIGHLIGHT))
            return None
        handler = self._highlight_commands.get(command.kind)
        if handler is None:
            raise ValueError("하이라이트 명령이 아닙니다.")
        result = handler()
        return None if isinstance(result, Highlight) else result

    def add_watched_folder(self, path: Path) -> WatchedFolder:
        return self._library.add_watched_folder(path)

    def watched_folders(self) -> tuple[WatchedFolder, ...]:
        return self._library.watched_folders()

    def remove_watched_folder(self, path: Path) -> None:
        self._library.remove_watched_folder(path)
        self._series.regroup(self.videos() + self.excluded_videos())

    def add_file(self, path: Path) -> ScanResult:
        result = self._library.add_file(path)
        self._series.regroup(self.videos() + self.excluded_videos())
        return result

    def reconnect_video(self, video_id: int, path: Path) -> None:
        self._library.reconnect_video(video_id, path)
        self._series.regroup(self.videos() + self.excluded_videos())

    def rename_video(self, video_id: int, title: str) -> None:
        self._library.rename_video(video_id, title)

    def exclude_video(self, video_id: int) -> None:
        self._library.set_excluded(video_id, True)

    def restore_video(self, video_id: int) -> None:
        self._library.set_excluded(video_id, False)

    def excluded_videos(self) -> tuple[Video, ...]:
        return self._library.videos(excluded=True)

    @property
    def minimum_duration(self) -> float:
        return self._library.minimum_duration

    def set_minimum_duration(self, seconds: float) -> None:
        self._library.set_minimum_duration(seconds)

    def series(self) -> tuple[Series, ...]:
        """제외 영상은 감추고 파일 없음 영상은 포함한 표시·편집용 구성이다."""
        visible = {video.id for video in self.videos()}
        return tuple(replace(series, video_ids=tuple(vid for vid in series.video_ids if vid in visible))
                     for series in self._series.list())

    def series_for_video(self, video_id: int) -> Series | None:
        return next((series for series in self.series() if video_id in series.video_ids), None)

    def create_series(self, name: str, video_ids: tuple[int, ...] = ()) -> Series:
        return self._edit_series(None, name, video_ids)

    def update_series(self, series_id: int, *, name: str, video_ids: tuple[int, ...]) -> Series:
        return self._edit_series(series_id, name, video_ids)

    def _edit_series(self, series_id, name, video_ids):
        excluded = {video.id for video in self.excluded_videos()}
        if excluded.intersection(video_ids):
            raise ValueError("제외된 영상은 되돌린 뒤 시리즈를 편집하세요.")
        edited = self._series.edit(series_id, name, video_ids, preserved_video_ids=excluded)
        return next(series for series in self.series() if series.id == edited.id)

    def adjacent_video(self, video_id: int, visible_video_ids: tuple[int, ...], *, forward: bool) -> int | None:
        """시리즈 순서를 우선하고, 시리즈 밖에서는 재생을 시작한 목록 순서를 쓴다."""
        # 현재 재생 영상이 뒤늦게 제외돼도 원래 시리즈의 경계를 벗어나지 않는다.
        series = self._series.for_video(video_id)
        order = series.video_ids if series else tuple(visible_video_ids)
        playable = {video.id for video in self.videos() if not video.missing}
        order = tuple(vid for vid in order if vid == video_id or vid in playable)
        return adjacent_video(video_id, order, forward=forward)

    def execute_video_command(self, command: Command, visible_video_ids: tuple[int, ...]) -> int | None:
        """모아보기에서는 영상별 첫 하이라이트로, 일반 재생에서는 이전·다음 영상으로."""
        if command.kind not in (CommandType.PREVIOUS_VIDEO, CommandType.NEXT_VIDEO):
            raise ValueError("영상 이동 명령이 아닙니다.")
        forward = command.kind == CommandType.NEXT_VIDEO
        if self.reel_playback is not None:
            self._execute_reel_transition(lambda: self._reel.adjacent_video(forward=forward))
            return None
        if self.playback.session is None:
            return None
        return self.adjacent_video(self.playback.session.video_id, visible_video_ids, forward=forward)

    def scan(self) -> ScanResult:
        rules = self._auto_subtitle_rules.list()
        result = self._library.scan(on_registered=lambda video_id: self._auto_subtitle_rules.apply(video_id, rules=rules))
        self._series.regroup(self.videos() + self.excluded_videos())
        return result


    def videos(self) -> tuple[Video, ...]:
        return self._library.videos()

    def video(self, video_id: int) -> Video:
        return self._library.video(video_id)

    def playback_location(self, video_id: int) -> Location:
        return self._library.playback_location(video_id)

    def _start_viewing(self, video_id: int, position: float) -> Viewing:
        with self._connect() as db:
            row = db.execute("SELECT duration FROM videos WHERE id=?", (video_id,)).fetchone()
        if row is None:
            raise ValueError("영상이 없습니다.")
        return self._viewings.start(video_id, row[0], position)

    def save_viewings(self) -> None:
        self._viewings.save_due()

    def viewings(self, video_id: int) -> tuple[Viewing, ...]:
        return self._viewings.list(video_id)

    def viewing_status(self, video_id: int) -> ViewingStatus:
        return viewing_status(self.viewings(video_id), self._viewings.settings)

    def viewing_status_map(self) -> dict[int, ViewingStatus]:
        return self._viewings.status_map()

    def resume_start(self, video_id: int) -> float:
        point = self.viewing_status(video_id).resume_point
        return max(0, point - self._viewings.settings.resume_rewind) if point is not None else 0

    def switch_to(self, video_id: int, *, start: float | None = None) -> float:
        """시청·열린 구간을 닫고 지정 장면 또는 이어볼 위치에서 시작한다."""
        self.playback_location(video_id)
        if start is not None:
            video = next(v for v in self.videos() if v.id == video_id)
            if not math.isfinite(start) or not 0 <= start <= video.duration:
                raise ValueError("시각은 0초 이상 영상 길이 이하여야 합니다.")
        self.playback.end()
        start = self.resume_start(video_id) if start is None else start
        self.playback.start(video_id, start)
        return start


class _Connection:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection.__enter__()

    def __exit__(self, *args):
        try:
            return self.connection.__exit__(*args)
        finally:
            self.connection.close()
