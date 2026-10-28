"""UI/재생 엔진과 독립된 앱 코어의 공개 경계."""

from dataclasses import dataclass, field, replace
from datetime import datetime, tzinfo
from enum import Enum
import math
import logging
from pathlib import Path
import sqlite3
from threading import Lock, RLock
from typing import Callable, Iterable, Mapping

from .library import (Library, Location, MediaInfo, MediaReader, ScanIssue, ScanIssueKind, ScanResult, Video,
                      WatchedFolder)
from .settings import Settings
from .highlights import Highlight, Highlights
from .key_bindings import KeyBinding, KeyBindings
from .recommendation import (
    RECOMMENDATION_PERIODS, RecommendationRow, RecommendationStore, select_recommendations)
from .playback import PlaybackHub
from .reel import HighlightReel, ReelEntry, ReelPlayback, ReelSettings
from .revisit import Revisits
from .series import Series, SeriesStore, adjacent_video
from .search import Search, SearchResponse
from .tags import Tag, TagUsage, Tags
from .viewing import Viewing, ViewingRecord, ViewingRecorder, ViewingSettings, ViewingStatus, ViewingStore, viewing_status
from .subtitles import Subtitles, Transcriber, Transcript, SubtitleQueueEntry, transcript_srt
from .translation import (Translator, Translations, Translation, TranslationQueueEntry, SubtitleSelection,
                          translation_skip_reason)
from .subtitle_queue_kind import TRANSCRIPTION, queue_task_key
from .subtitle_queue import AutoSubtitleRules, QueueOrder, SubtitleQueue, SubtitleRetryResult, SubtitleRetrySkipped
from .review import Review, ReviewPlayback, SubtitleExport
from .library_details import LibraryDetails
from .statistics import StatisticsReader, VideoViewingStatistics, ViewingStatistics
from .statistics import StatisticsDashboard
from .external_subtitles import ExternalSubtitleFile, ExternalSubtitleFileSummary
from .resolution import ResolutionBackfill, ResolutionResult
from .library_views import build_index, default_options, normalize_options
from .thumbnails import ThumbnailBackfill
from .random_continuous_play import RandomContinuousPlay, RandomPlayScope, ScopeLabel


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
    TOGGLE_FULLSCREEN = "toggle_fullscreen"
    TOGGLE_HIGHLIGHT_LIST = "toggle_highlight_list"
    EMERGENCY_HIDE = "emergency_hide"
    RANDOM_PLAY = "random_play"
    # 재생 화면 🔀 단추와 같은 명령. 기본 키는 없고 키 배치에서 지정할 수 있다.
    TOGGLE_RANDOM_CONTINUOUS = "toggle_random_continuous"


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
    ";": Command(CommandType.TOGGLE_HIGHLIGHT_LIST),
    "'": Command(CommandType.TOGGLE_FULLSCREEN),
    "Ctrl+Shift+H": Command(CommandType.EMERGENCY_HIDE),
    "Ctrl+Shift+R": Command(CommandType.RANDOM_PLAY),
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
    video_statistics: dict[int, VideoViewingStatistics] = field(default_factory=dict)
    viewing_records: tuple[ViewingRecord, ...] = ()


# 무작위 재생의 직전 선택만 감싸는 잠금. 검사(scan)가 쥐는 AppCore._lock과 공유하지 않는다.
_RANDOM_HISTORY_LOCK = Lock()


class AppCore:
    # 직전에 무작위로 고른 영상 ID. 앱을 다시 켜면 잊는다.
    _last_random_video_id: int | None = None

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
        translation_batch_size: int | None = None,
        translation_secret_store=None,
        translation_transport=None,
        reel_settings: ReelSettings | None = None,
        update_installation=None,
        random_choice: Callable[[tuple[int, ...]], int] | None = None,
    ):
        self.database = (Path(database) if database is not None else default_data_directory() / "library.sqlite3").resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._thumbnails = self.database.parent / "thumbnails"
        self._thumbnails.mkdir(exist_ok=True)
        self._media = media
        self._clock = clock
        self._random_choice = random_choice
        self._random_continuous = RandomContinuousPlay()
        # 업데이트 확인의 설치 정보 어댑터. None이면 실행 중인 앱 버전과 런타임 지문을 읽는다.
        self.update_installation = update_installation
        self._installed_update = None
        self._lock = RLock()
        self.settings = Settings(self._connect)
        self._folder_watch = None
        self._keys = KeyBindings(self.settings, DEFAULT_KEY_BINDINGS, tuple(Command(kind) for kind in CommandType))
        if key_bindings is not None:
            self._keys.replace(key_bindings, persist=False)
        # 접속은 호출 단위로 열어 UI 작업자 스레드에서도 코어를 사용할 수 있다.
        self._library = Library(self._connect, media, clock, self._thumbnails, self.settings,
                                on_registered=lambda video_id: self._auto_subtitle_rules.apply(video_id))

        self.playback = PlaybackHub()
        self._series = SeriesStore(self._connect)
        self._highlights = Highlights(self._connect, on_created=lambda db, hid:
                                      self._recommendations.record_highlight_created(db, hid))
        self._recommendations = RecommendationStore(self._connect, clock, self.settings)
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
        from .translation_options import TranslationOptions
        self._translation_options = TranslationOptions(self.settings, self._connect, self.database.parent, clock,
                                                       secret_store=translation_secret_store, transport=translation_transport)
        self._translations = Translations(self._connect, clock, self._subtitles, self.settings, translator,
                                          batch_size=translation_batch_size, order=self._queue_order,
                                          protected_lines=self._review.protected_lines, options=self._translation_options)
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
        self._resolution = ResolutionBackfill(self._connect, media)
        self._thumbnail_backfill = ThumbnailBackfill(self._connect, media, self._thumbnails, self.settings)

    def fill_next_thumbnail(self, *, cancellation):
        return self._thumbnail_backfill.step(cancellation)

    def _update_checker(self, http=None):
        from .update_check import UpdateChecker
        return UpdateChecker(self.settings, clock=self._clock, http=http, installation=self.installed_update_info)

    def check_for_update(self, *, http=None):
        """Blocking update check for a worker; optional http adapter supports offline tests."""
        return self._update_checker(http).check()

    def should_check_for_update(self) -> bool:
        """Startup decision only; does not start a thread or access the network."""
        return self._update_checker().should_check_on_startup()

    def last_update_check(self):
        return self._update_checker().last_result()

    def automatic_update_check_enabled(self) -> bool:
        return self._update_checker().automatic_enabled()

    def set_automatic_update_check_enabled(self, enabled: bool) -> None:
        self._update_checker().set_automatic_enabled(enabled)

    def update_to_announce(self):
        """알릴 업데이트 확인 결과. 이전 버전의 이력이거나 건너뛴 버전이면 None이다."""
        return self._update_checker().update_to_announce()

    def skipped_update_version(self) -> str | None:
        return self._update_checker().skipped_version()

    def skip_update_version(self, version: str) -> None:
        self._update_checker().skip_version(version)

    def clear_skipped_update_version(self) -> None:
        self._update_checker().clear_skipped_version()

    def installed_update_info(self):
        """주입한 어댑터는 매번 부른다. 기본 설치 정보는 실행 중에 바뀌지 않으므로 처음 읽은 값을 쓴다."""
        if self.update_installation is not None:
            return self.update_installation()
        if self._installed_update is None:
            from .update_check import installed_update_info
            self._installed_update = installed_update_info()
        return self._installed_update

    def download_update(self, result, *, full=False, progress=None, cancellation=None, http=None):
        """작업자 스레드용 업데이트 내려받기. result(확인 이력)의 버전만 쓰고 서명된 매니페스트를 다시 받는다.

        full=True면 패치 대신 전체 설치 파일을 받는다(패치 실패 뒤 다시 시도). 실패·취소는 결과 값으로 돌려준다.
        """
        from .update_install import download_update
        if http is None:
            from .update_http import UrllibUpdateHttp
            http = UrllibUpdateHttp()
        return download_update(self.database.parent, result, self.installed_update_info, http=http, full=full,
                               progress=progress, cancellation=cancellation)

    def busy_reasons_for_update(self):
        """설치를 위한 재시작이 지금 끊을 작업과, 재시작 뒤 이어질 대기 항목 수."""
        from .update_install import update_busy_state
        return update_busy_state(playing=self.playback.session is not None,
                                 transcriptions=self.subtitle_queue(), translations=self.translation_queue())

    def prepare_update_install(self, update, *, launcher=None, relaunch=None, pid=None, ready_timeout=None):
        """검증된 설치 파일을 앱 종료 뒤 실행할 보조 프로세스에 넘긴다. 돌아오면 호출자가 앱을 종료해야 한다.

        보조 프로세스가 준비될 때까지 최대 수십 초 막으므로 작업자 스레드에서 부른다.
        실패하면 UpdateInstallError를 던지고 아무것도 설치되지 않는다. relaunch는 (프로그램, 인자) 시험용 주입이다.
        """
        import os
        import sys
        from .update_install import READY_TIMEOUT, SubprocessHelperLauncher, UpdateInstallError, start_install
        if relaunch is None:
            if not getattr(sys, 'frozen', False):
                raise UpdateInstallError('source_run')  # 소스 실행은 설치본을 고치지 않는다.
            from .backup_recovery import restart_command
            relaunch = restart_command(self.database.parent)
        start_install(self.database.parent, update, pid=os.getpid() if pid is None else pid, relaunch=relaunch,
                      started_at=self._clock(), launcher=launcher or SubprocessHelperLauncher(),
                      ready_timeout=READY_TIMEOUT if ready_timeout is None else ready_timeout)

    def last_update_install(self):
        """지난 설치 시도의 결과. 패치 실패면 retry_full로 전체 설치 파일 다시 시도를 안내한다."""
        from .update_install import last_install
        return last_install(self.database.parent, self.installed_update_info)

    def clear_update_install(self, *, keep_log=False):
        """결과를 안내한 뒤 설치 기록과 받은 설치 파일을 지운다. keep_log면 실패 진단용 installer.log를 남긴다."""
        from .update_install import clear_install
        clear_install(self.database.parent, keep_log=keep_log)

    def update_installer_log(self):
        """설치 프로그램 기록(installer.log) 위치. 파일이 없을 수 있다."""
        from .update_install import installer_log
        return installer_log(self.database.parent)

    def fill_next_resolution(self, *, cancellation) -> ResolutionResult:
        """작업자용 API. 한 영상 처리 후 반환하며 취소 시 다음 호출에서 이어진다."""
        return self._resolution.step(cancellation)

    def library_view_options(self):
        try:
            return normalize_options(self.settings.get('library.view', {}))
        except (ValueError, TypeError):
            return default_options()

    def save_library_view_options(self, options):
        options = normalize_options(options)
        self.settings.set('library.view', options)
        return options

    def library_view_index(self, snapshot=None):
        return build_index(snapshot if snapshot is not None else self.library_snapshot(),
                           self.watched_folders(), self._connect)

    def library_view_ids(self, options, *, index=None):
        return (index if index is not None else self.library_view_index()).select(options, self._clock())

    def prepare_subtitle_support(self, *, cancellation=None, progress=None, preparation=None):
        """작업자 스레드용 자막 준비 API. progress 콜백은 예외를 던지지 않아야 한다."""
        from .cuda_runtime import SubtitlePreparation
        service = preparation if preparation is not None else SubtitlePreparation(self.database.parent)
        return service.prepare(cancellation=cancellation, progress=progress)

    @property
    def translation_cli(self) -> str:
        return self._translations.cli

    def subtitle_support_status(self):
        """준비의 영속 결과와 완료 파일만 읽으며 탐지나 다운로드는 하지 않는다."""
        from .cuda_runtime import SubtitlePreparation
        return SubtitlePreparation(self.database.parent).status()

    def subtitle_preparation_notice(self):
        """첫 요청에 표시할 준비 다운로드 안내. 소스 실행과 완료된 준비는 생략한다."""
        import sys
        from .runtime_assets import preparation_download_label
        if not getattr(sys, 'frozen', False) or self.subtitle_support_status()['kind'] == 'ready':
            return ''
        return f'자막 기능 준비에 CUDA와 Whisper 모델 {preparation_download_label()}를 내려받습니다. 준비 중 취소할 수 있습니다.'

    def create_backup(self, destination: Path, *, include_thumbnails=False):
        from .backup import create_backup
        session = self.playback.session
        active = tuple(viewing for viewing in self.viewings(session.video_id) if viewing.ended_at is None) if session else ()
        return create_backup(self.database, destination, include_thumbnails=include_thumbnails,
                             active_viewings=active)

    def inspect_backup(self, archive: Path):
        from .backup import inspect_backup
        return inspect_backup(archive)

    def request_backup_restore(self, archive: Path):
        from .backup import request_backup_restore
        result = request_backup_restore(self.database, archive)
        self.set_backup_restore_startup_result(result)
        return result

    def pending_backup_restore(self):
        from .backup import inspect_backup, pending_backup_restore_path
        pending = pending_backup_restore_path(self.database)
        return inspect_backup(pending) if pending.exists() else None

    def cancel_backup_restore(self):
        from .backup import cancel_backup_restore
        cancel_backup_restore(self.database)
        self.set_backup_restore_startup_result(None)

    def set_backup_restore_startup_result(self, result):
        """시작 경로가 받은 복원 결과를 화면에서 조회할 수 있게 보관한다."""
        self._backup_restore_startup_result = result

    def backup_restore_status(self):
        """큰 ZIP을 다시 풀지 않고 이번 시작/예약의 결과와 실패 안내를 조회한다."""
        return getattr(self, "_backup_restore_startup_result", None)

    def automatic_backups(self):
        from .backup import automatic_backups
        return automatic_backups(self.database)

    def translation_settings(self):
        return self._translation_options.snapshot()

    def save_translation_settings(self, provider, selections, fallback, *, key_action='keep', key=''):
        return self._translation_options.save(provider, selections, fallback, key_action=key_action, key=key)

    def check_translation_key(self, key='', *, delete=False, cancellation=None):
        return self._translation_options.check_key(key, delete=delete, cancellation=cancellation)

    def translation_models(self, key='', *, cancellation=None):
        return self._translation_options.models(key, cancellation=cancellation)

    def translation_line_providers(self, video_id):
        return self._translations.line_providers(video_id)

    def backup_inventory(self, *, include_automatic=True):
        """목록·예약 존재 여부만 조회한다. 실제 복원은 inspect/request에서 검증한다."""
        from .backup_catalog import backup_inventory
        return backup_inventory(self.database, include_automatic=include_automatic)

    def review_lines(self, video_id):
        return self._review.lines(video_id)

    def reviewed_line_count(self, video_id):
        return self._review.reviewed_count(video_id)

    def subtitle_regeneration_warning(self, video_id):
        return self._review.regeneration_warning(video_id)

    def edit_transcript_line(self, video_id, line_id, text, *, overwrite_reviewed=False, keep_reviewed=False):
        self._review.edit(video_id, line_id, text, overwrite_reviewed=overwrite_reviewed, keep_reviewed=keep_reviewed)

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

    def play_review_line(self, video_id, line_id, *,
                         playback_video_ids: Iterable[int] | None = None,
                         playback_source_name: str | None = None) -> ReviewPlayback:
        """같은 일반 영상이면 탐색하고, 새 재생이면 전달받은 목록(과 그 출처 이름)으로 시청을 시작한다."""
        start = min(self.review_line_position(video_id, line_id), self.video(video_id).duration)
        session = self.playback.session
        if session and session.video_id == video_id and session.record_viewing and self.reel_playback is None:
            return ReviewPlayback(video_id, start, "seek")
        self.switch_to(video_id, start=start,
                       playback_video_ids=(video_id,) if playback_video_ids is None else playback_video_ids,
                       playback_source_name=playback_source_name if playback_video_ids is not None else None)
        return ReviewPlayback(video_id, start, "play")

    def set_translation_cli(self, cli: str) -> None:
        self._translations.set_cli(cli)

    def request_translation(self, video_id: int, line_ids=None) -> TranslationQueueEntry | None:
        """전체 또는 지정한 원어 줄 ID만 번역한다. 실패/보류 재요청은 완료한 묶음을 유지한다."""
        return self._translations.request(video_id, line_ids)

    def subtitle_task(self, video_id):
        return self._translations.task(video_id)

    def request_refinement(self, video_id):
        return self._translations.request_refinement(video_id)

    def existing_refinement_candidates(self):
        return self._translations.existing_refinement_candidates()

    def request_existing_refinements(self):
        return self._translations.request_existing_refinements()

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

    @property
    def playback_subtitle_language(self) -> str:
        """현재 재생에서 선택한 자막 종류. 표시 켜짐 여부는 플레이어가 소유한다."""
        return "translated" if self._subtitle_selection.translated else "original"

    def reel_entries(self, tag_id: int | None = None) -> tuple[ReelEntry, ...]:
        return self._reel.list(tag_id)

    def start_reel(self, tag_id: int | None = None,
                      highlight_id: int | None = None) -> ReelPlayback | None:
        current = self._reel.start(tag_id, highlight_id)
        self._random_continuous = RandomContinuousPlay()
        return current

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
        chosen = self._subtitle_selection.chosen
        transition()
        current = self.reel_playback
        if previous and current and current.action == "seek" and previous.video_id == current.video_id:
            # 항목별 재생 수명주기는 닫되, 같은 영상의 자막 선택은 엔진과 함께 유지한다.
            self._subtitle_selection.translated = translated
            self._subtitle_selection.chosen = chosen

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
        viewing_summary = self._viewings.summary()
        return LibrarySnapshot(videos, viewing_summary.statuses, self.video_tags_map(), series,
                               viewing_summary.statistics, viewing_summary.records)

    def library_details(self, video_id: int) -> LibraryDetails:
        """선택한 영상 하나의 상세 요약. 파일 없음·제외 여부와 무관하게 기록을 읽는다."""
        self.video(video_id)
        with self._connect() as db:
            db.execute("BEGIN")
            original = self._subtitles.summary(video_id, connection=db)
            translated = self._translations.summary(video_id, connection=db)
            return LibraryDetails(original.has_transcript, original.spoken_language, original.line_count,
                                  translated.translated_lines, original.queue_state, translated.queue_state,
                                  self._highlights.count(video_id, connection=db), original.no_speech,
                                  translation_skip_reason(original))

    def subtitled_video_ids(self) -> frozenset[int]:
        return self._subtitles.subtitled_video_ids()

    def highlight_tags_map(self, video_id: int) -> dict[int, tuple[Tag, ...]]:
        return self._tags.highlight_tags_map(video_id)

    def recommendations(self, *, snapshot: LibrarySnapshot | None = None) -> tuple[RecommendationRow, ...]:
        """추천 줄 목록. 빈 줄은 없고 영상 하나는 한 줄에만 나온다."""
        snapshot = self.library_snapshot() if snapshot is None else snapshot
        return select_recommendations(
            snapshot.videos, snapshot.statuses, snapshot.tags, snapshot.series,
            self._recommendations.dismissed_ids(), self._recommendations.revisit_times(), now=self._clock(),
            viewing_records=snapshot.viewing_records, viewing_settings=self._viewings.settings,
            unwatched_days=self._recommendations.days("unwatched"), revisit_days=self._recommendations.days("revisit"),
            continue_watching_days=self._recommendations.days("continue_watching"),
            new_arrivals_days=self._recommendations.days("new_arrivals"),
            rewatch_days=self._recommendations.days("rewatch"))

    def recommendation_period_definitions(self):
        """설정 화면이 기간 이름·기본값·허용 범위를 그릴 수 있게 정의를 내보낸다."""
        return RECOMMENDATION_PERIODS

    def recommendation_period_days(self) -> dict[str, float]:
        """다섯 기간의 현재 일수. 저장값이 없으면 정의된 기본값이다."""
        return {period.criterion: self._recommendations.days(period.criterion)
                for period in RECOMMENDATION_PERIODS}

    def recommendation_period(self, criterion: str) -> float:
        """기간 하나의 현재 일수. 저장값이 잘못됐으면 그 기간만 예외로 알린다."""
        return self._recommendations.days(criterion)

    def set_recommendation_period_days(self, criterion: str, days: float) -> None:
        """기간 하나를 검증해 저장한다. 잘못된 값은 예외로 거부하고 저장하지 않는다."""
        self._recommendations.set_days(criterion, days)

    def reset_recommendation_period_days(self, criterion: str) -> None:
        """기간 하나를 기본값으로 되돌린다."""
        self._recommendations.reset_days(criterion)

    def dismiss_video(self, video_id: int) -> None:
        self._recommendations.set_dismissed(video_id, True)

    def restore_dismissed_video(self, video_id: int) -> None:
        self._recommendations.set_dismissed(video_id, False)

    def dismissed_videos(self) -> tuple[Video, ...]:
        ids = self._recommendations.dismissed_ids()
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

    def remove_from_subtitle_queue(self, video_id, *, kind=TRANSCRIPTION):
        self._subtitles.remove(video_id, kind=kind)
        if kind == TRANSCRIPTION:
            self._translations.remove(video_id)
        self._subtitle_queue.hide(video_id, kind=kind)

    def promote_subtitle(self, video_id, *, kind=TRANSCRIPTION):
        if not any(queue_task_key(e) == (video_id, kind)
                   for e in (*self.subtitle_queue(kind=kind), *self.translation_queue())):
            raise ValueError("대기열에 없는 영상입니다.")
        self._queue_order.promote(video_id, kind=kind)

    def retry_failed_subtitles(self, *, kind=TRANSCRIPTION):
        failed = [e for e in self.subtitle_queue(kind=kind) if e.state == "failed"]
        translated = [e for e in self.translation_queue() if e.state == "failed"] if kind == TRANSCRIPTION else []
        retried, skipped = set(), []
        for entries, request in ((failed, lambda e: self._subtitles.retry_failed(e.id, kind=e.queue_kind)),
                                 (translated, lambda e: self.request_translation(e.video_id))):
            for entry in entries:
                try:
                    request(entry)
                    retried.add(queue_task_key(entry))
                except (ValueError, OSError, RuntimeError) as error:
                    skipped.append(SubtitleRetrySkipped(entry.video_id, str(error), queue_task_key(entry)[1]))
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

    def subtitle_queue(self, *, kind=TRANSCRIPTION) -> tuple[SubtitleQueueEntry, ...]:
        return self._subtitles.queue(kind=kind)

    def process_next_subtitle(self) -> SubtitleQueueEntry | None:
        with self._subtitle_queue.processing():
            result = self._subtitles.process_next()
            if result and result.state == "completed":
                self._translations.enqueue_eligible()
                # 후속 번역 등록 뒤에 정리해야 받아쓰기에서 받은 순서가 이어진다.
                with self._connect() as db:
                    self._queue_order.finish(db, result.video_id)
            self._subtitle_queue.record(result)
            return result

    def stop_subtitle_processing(self) -> None:
        self._subtitles.stop_processing()

    def transcript(self, video_id: int) -> Transcript | None:
        return self._subtitles.transcript(video_id)

    def has_transcript(self, video_id: int) -> bool:
        return self._subtitles.has_transcript(video_id)

    def playback_subtitle(self, video_id: int) -> Path | None:
        self._subtitle_selection.select_default()
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

    def tag_usage(self) -> tuple[TagUsage, ...]:
        """태그 고르기용 목록. 붙은 영상 수가 많은 순이며 제외 영상과 하이라이트는 세지 않는다."""
        return self._tags.usage()

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
        folder = self._library.add_watched_folder(path)
        self._update_folder_watch()
        return folder

    def watched_folders(self) -> tuple[WatchedFolder, ...]:
        return self._library.watched_folders()

    def remove_watched_folder(self, path: Path) -> None:
        self._library.remove_watched_folder(path)
        self._update_folder_watch()
        self._series.regroup(self.videos() + self.excluded_videos())

    def create_folder_watch(self, on_batch_ready, *, watcher=None, **options):
        """감시 컨트롤러를 한 번 만든다. start/stop과 콜백 스레드 연결은 호출자 소유.

        콜백은 tuple[Path, ...]를 기존 검사 실행기에 enqueue해야 한다.
        실행기는 AppCore.scan(folders=folders)를 한 번 호출한다.
        clock/scheduler/snapshot 등은 FolderWatch에 주입할 수 있다.
        """
        from .folder_watch import FolderWatch
        if self._folder_watch is not None:
            raise RuntimeError("폴더 감시 컨트롤러가 이미 있습니다.")
        if watcher is None:
            from .folder_watch_adapter import WatchdogFolderWatcher
            watcher = WatchdogFolderWatcher()
        self._folder_watch = FolderWatch(
            self.settings, (folder.path for folder in self.watched_folders()),
            on_batch_ready, watcher=watcher, **options)
        return self._folder_watch

    def _update_folder_watch(self):
        if self._folder_watch is not None:
            try:
                self._folder_watch.set_folders(folder.path for folder in self.watched_folders())
            except Exception as error:
                # 영속 폴더 변경은 이미 성공했다. 감시 실패가 regroup/UI 응답을 막지 않는다.
                logging.getLogger(__name__).warning("감시 대상 갱신 실패: %s", error)

    def automatic_detection_enabled(self) -> bool:
        from .folder_watch import automatic_detection_enabled
        return automatic_detection_enabled(self.settings)

    def set_automatic_detection_enabled(self, enabled: bool) -> None:
        from .folder_watch import AUTOMATIC_DETECTION_KEY
        if not isinstance(enabled, bool):
            raise TypeError("자동 감지 설정은 bool이어야 합니다.")
        if self._folder_watch is None:
            self.settings.set(AUTOMATIC_DETECTION_KEY, enabled)
        else:
            self._folder_watch.set_enabled(enabled)

    def add_file(self, path: Path) -> ScanResult:
        result = self._library.add_file(path)
        self._thumbnail_backfill.retry_unavailable()
        self._series.regroup(self.videos() + self.excluded_videos())
        return result

    def external_subtitles(self, video_id: int) -> tuple[ExternalSubtitleFile, ...]:
        """영상 옆에서 가져온 파일의 언어별 줄과 읽기 경고를 반환한다."""
        return self._library.external_subtitles.files(video_id)

    def external_subtitle_summaries(self, video_id: int) -> tuple[ExternalSubtitleFileSummary, ...]:
        """상세 화면에서 쓸 파일 이름·언어·줄 수·경고를 반환한다."""
        return self._library.external_subtitles.summaries(video_id)

    def reconnect_video(self, video_id: int, path: Path) -> None:
        self._library.reconnect_video(video_id, path)
        self._thumbnail_backfill.retry_unavailable()
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
        state = self._random_continuous
        if state.enabled:
            from .random_play import is_candidate
            scope = state.scope
            videos = self.videos()
            candidates = self._random_video_candidates(
                video_ids=scope.video_ids if scope.kind == "list" else None,
                tag_ids=scope.tag_ids if scope.kind == "tags" else None, videos=videos)
            target, picked = state.move(forward=forward, candidates=candidates,
                                        playable={v.id for v in videos if is_candidate(v)},
                                        choice=self._random_choice)
            if picked:
                with _RANDOM_HISTORY_LOCK:
                    self._last_random_video_id = target
            return target
        order = state.source_ids if state.source_ids is not None else visible_video_ids
        return self.adjacent_video(self.playback.session.video_id, order, forward=forward)

    @property
    def random_continuous_enabled(self) -> bool:
        return self._random_continuous.enabled

    @property
    def random_continuous_scope(self) -> RandomPlayScope | None:
        """현재 범위의 불변 값. 꺼져 있으면 None이다."""
        return self._random_continuous.scope

    @property
    def playback_video_ids(self) -> tuple[int, ...]:
        """재생을 시작한 목록의 스냅숏. 범위 선택 화면에서도 이 목록을 쓴다."""
        return self._random_continuous.source_ids or ()

    @property
    def playback_source_name(self) -> str | None:
        """재생을 시작한 목록의 출처 이름(예: 현재 결과, 검색 결과). 진입점이 넘기지 않았으면 None."""
        return self._random_continuous.source_name

    def random_continuous_scope_label(self) -> ScopeLabel | None:
        """조작 줄에 보일 범위 이름(짧은 이름·툴팁 설명 포함). 꺼져 있으면 None이다. 지워진 태그는 이름에서 뺀다."""
        scope = self.random_continuous_scope
        if scope is None:
            return None
        from .random_continuous_play import scope_label
        names = {tag.id: tag.name for tag in self.tags()} if scope.kind == "tags" else {}
        return scope_label(scope, source_name=self.playback_source_name,
                           tag_names=tuple(names[tag_id] for tag_id in scope.tag_ids if tag_id in names))

    def random_scope_video_count(self, scope: RandomPlayScope) -> int:
        """범위의 무작위 재생 후보 수. 범위 고르기 화면이 후보 0인 범위를 막는 데 쓴다."""
        if not isinstance(scope, RandomPlayScope):
            raise ValueError("무작위 재생 범위가 올바르지 않습니다.")
        return self.random_video_count(video_ids=scope.video_ids if scope.kind == "list" else None,
                                       tag_ids=scope.tag_ids if scope.kind == "tags" else None)

    def set_random_continuous_enabled(self, enabled: bool) -> None:
        state = self._random_continuous
        if not enabled:
            state.disable()
        elif not state.enabled:
            session = self.playback.session
            if session is None or not session.record_viewing or self.reel_playback is not None:
                raise ValueError("일반 영상을 재생하는 동안에만 무작위 이어 재생을 켤 수 있습니다.")
            source = state.source_ids if state.source_ids is not None else (session.video_id,)
            state.enable(session.video_id, RandomPlayScope("list", source))

    def set_random_continuous_scope(self, scope: RandomPlayScope) -> None:
        """지금 영상·이동 기록·나온 영상은 유지하고 다음 선택 범위만 바꾼다."""
        if not self.random_continuous_enabled:
            raise ValueError("무작위 이어 재생을 먼저 켜세요.")
        if not isinstance(scope, RandomPlayScope):
            raise ValueError("무작위 재생 범위가 올바르지 않습니다.")
        self._random_continuous.scope = scope

    def take_random_continuous_notice(self) -> str | None:
        notice, self._random_continuous.notice = self._random_continuous.notice, None
        return notice

    def advance_random_if_due(self, session, *, eof: bool = False) -> int | None:
        """위치 보고 뒤 호출한다. 지난 영상의 EOF는 새 세션에 적용하지 않는다."""
        if eof and self.random_continuous_enabled and self.playback.session is session:
            return self.execute_video_command(Command(CommandType.NEXT_VIDEO), self.playback_video_ids)
        return None

    def end_playback(self) -> None:
        """목록 복귀·종료: 시청을 마감하고 일시적인 이어 재생 상태를 버린다."""
        self.playback.end()
        self._random_continuous = RandomContinuousPlay()

    def scan(self, *, folders: Iterable[Path] | None = None) -> ScanResult:
        """감시 폴더 전체 또는 지정한 하위 폴더를 검사한다. 범위 밖 입력은 건너뛴다.

        `folders`에는 `watched_folders()`가 돌려준 경로 아래 폴더의 `Path` 목록을
        넘긴다. 밖이거나 감시 해제된 경로는 건너뛰고 로그만 남긴다. 단일 `str`이나
        `PathLike`를 그대로 넘기면 `TypeError`다.
        인자가 없으면 직접 추가한 위치도 확인한다. 빈 목록은 아무것도 검사하지 않는다.
        전체/지정 폴더 검사는 자동 자막 규칙 적용과 후처리까지 순서대로 실행한다.
        """
        with self._lock:
            rules = self._auto_subtitle_rules.list()
            result = self._library.scan(
                folders=folders, on_registered=lambda video_id: self._auto_subtitle_rules.apply(video_id, rules=rules))
            if folders is None or result.reconnected:
                self._thumbnail_backfill.retry_unavailable()
            self._series.regroup(self.videos() + self.excluded_videos())
            return result


    def videos(self) -> tuple[Video, ...]:
        return self._library.videos()

    def _random_video_candidates(
        self, *, video_ids: Iterable[int] | None = None, tag_ids: Iterable[int] | None = None,
        videos: tuple[Video, ...] | None = None,
    ) -> tuple[int, ...]:
        if video_ids is not None and tag_ids is not None:
            raise ValueError("영상 범위와 태그 범위 중 하나만 지정하세요.")
        selected_ids = None if video_ids is None else set(video_ids)
        if tag_ids is not None:
            selected_tags = set(tag_ids)
            selected_ids = {
                video_id for video_id, tags in self.video_tags_map().items()
                if any(tag.id in selected_tags for tag in tags)
            }
        from .random_play import is_candidate

        return tuple(
            video.id for video in (self.videos() if videos is None else videos)
            if is_candidate(video) and (selected_ids is None or video.id in selected_ids)
        )

    def random_video_count(
        self, *, video_ids: Iterable[int] | None = None, tag_ids: Iterable[int] | None = None,
    ) -> int:
        """무작위 선택 범위의 후보 수. 직전 선택은 빼지 않으며 선택 이력도 바꾸지 않는다.

        인자를 생략하면 전체, 빈 ID 목록이면 빈 범위다. 두 범위의 동시 지정은 거절한다.
        태그는 영상에 붙은 것만 OR로 센다. 없는 ID와 중복 ID는 무시한다.
        상태를 바꾸지 않으므로 검사(scan)가 쥔 잠금을 잡지 않는다.
        """
        return len(self._random_video_candidates(video_ids=video_ids, tag_ids=tag_ids))

    def random_tag_candidates(self, snapshot: LibrarySnapshot | None = None) -> dict[int, frozenset[int]]:
        """태그 ID별 무작위 재생 후보 영상 ID. 후보가 없는 태그는 싣지 않는다.

        고른 태그들의 random_video_count(tag_ids=...)는 이 집합들의 합집합 크기와 같다.
        snapshot(library_snapshot 결과)을 주면 DB를 다시 읽지 않고 그 조회 결과로 계산한다.
        태그를 바꿀 때마다 후보 수를 다시 묻지 않도록 태그 고르기 창이 한 번 받아 쓴다.
        """
        from .random_play import tag_candidates

        if snapshot is None:
            return tag_candidates(self.videos(), self.video_tags_map())
        return tag_candidates(snapshot.videos, snapshot.tags)

    def pick_random_video(
        self, *, video_ids: Iterable[int] | None = None, tag_ids: Iterable[int] | None = None,
        choice: Callable[[tuple[int, ...]], int] | None = None,
    ) -> int | None:
        """재생 없이 영상 ID만 고른다. 범위는 random_video_count와 같다.

        choice는 후보 ID 튜플에서 하나를 반환하는 난수 어댑터(random.Random.choice 등)다.
        기본은 random.choice이며 직전 선택은 이 AppCore에서 범위와 관계없이 기억한다.
        빈 범위는 None을 반환하고 직전 선택을 유지한다. 후보 하나는 반복할 수 있다.
        후보 계산은 검사(scan)가 쥔 잠금 밖에서 하고, 직전 선택만 별도 잠금으로 감싼다.
        """
        from .random_play import choose_video_id

        candidates = self._random_video_candidates(video_ids=video_ids, tag_ids=tag_ids)
        with _RANDOM_HISTORY_LOCK:
            selected = choose_video_id(
                candidates, previous_video_id=self._last_random_video_id,
                choice=self._random_choice if choice is None else choice,
            )
            if selected is not None:
                self._last_random_video_id = selected
            return selected

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

    def viewing_statistics(self, days: int, *, tz: tzinfo | None = None) -> ViewingStatistics:
        """ViewingStatistics 반환. 오늘 포함 7·30·90·365일, 기본은 시스템 로컬 시간대.

        테스트에서는 datetime.tzinfo를 tz로 주입한다. 날짜/시각은 ISO 문자열,
        시청 시간은 초이며 dataclasses.asdict 결과를 JSON으로 직렬화할 수 있다.
        """
        return StatisticsReader(self._connect, self._clock, self._viewings).period(days, tz=tz)

    def video_viewing_statistics(self) -> dict[int, VideoViewingStatistics]:
        """영상 ID → VideoViewingStatistics. 제외·파일 없음·시청 없는 영상도 포함한다.

        전체 기간을 일괄 조회하며 마지막 시청 시각에는 틀어보기도 포함한다.
        """
        return StatisticsReader(self._connect, self._clock, self._viewings).video_map()

    def statistics_dashboard(self, days: int, *, tz: tzinfo | None = None) -> StatisticsDashboard:
        """기간 통계·요일/시간대 활동과 현재 라이브러리 총량을 한 스냅샷으로 조회한다."""
        return StatisticsReader(self._connect, self._clock, self._viewings).dashboard(days, tz=tz)

    def resume_start(self, video_id: int) -> float:
        point = self.viewing_status(video_id).resume_point
        return max(0, point - self._viewings.settings.resume_rewind) if point is not None else 0

    def switch_to(self, video_id: int, *, start: float | None = None,
                  playback_video_ids: Iterable[int] | None = None,
                  random_scope: RandomPlayScope | None = None,
                  playback_source_name: str | None = None) -> float:
        """시청·열린 구간을 닫고 지정 장면 또는 이어볼 위치에서 시작한다.

        새 목록에서 시작할 때 playback_video_ids를 넘긴다. random_scope도 넘기면
        해당 범위의 무작위 이어 재생으로 시작한다. 둘 다 생략한 영상 이동은 현재 상태를 유지한다.
        playback_source_name은 새 목록의 출처 이름이며 범위 이름에 쓴다.
        """
        if random_scope is not None and not isinstance(random_scope, RandomPlayScope):
            raise ValueError("무작위 재생 범위가 올바르지 않습니다.")
        source = None if playback_video_ids is None else tuple(dict.fromkeys(playback_video_ids))
        self.playback_location(video_id)
        if start is not None:
            video = next(v for v in self.videos() if v.id == video_id)
            if not math.isfinite(start) or not 0 <= start <= video.duration:
                raise ValueError("시각은 0초 이상 영상 길이 이하여야 합니다.")
        self.playback.end()
        start = self.resume_start(video_id) if start is None else start
        self.playback.start(video_id, start)
        if playback_video_ids is not None or random_scope is not None:
            self._random_continuous = RandomContinuousPlay(source_ids=source if source is not None else (video_id,),
                                                           source_name=playback_source_name)
        if random_scope is not None:
            self._random_continuous.enable(video_id, random_scope)
        else:
            self._random_continuous.record(video_id)
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
