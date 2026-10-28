"""폴더 관리 웹 페이지. 검사 작업자와 대화상자는 기존 라이브러리 진입점을 쓴다."""
import math
import sqlite3

from PySide6.QtCore import QObject, QTimer

from .library_operations import ScanReport
from .web_folders_contract import FOLDERS
from .web_folders_data import SCAN_NOTICE_GROUPS, scan_report_data
from .web_json import encode
from .web_page import WebPageController


class FoldersBridge(QObject):
    foldersChanged = FOLDERS.signal('foldersChanged')
    foldersFocusRequested = FOLDERS.signal('foldersFocusRequested')
    foldersError = FOLDERS.signal('foldersError')
    scan_locked = {'addFolder', 'removeFolder', 'scan', 'addFile', 'restoreExcluded'}

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.busy = False

    @FOLDERS.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @FOLDERS.slot('snapshot')
    def snapshot(self):
        return self.page.stamp(self.page.payload())

    @FOLDERS.slot('dismissReport')
    def dismissReport(self, revision, group):
        if group not in SCAN_NOTICE_GROUPS:
            return encode({'error': '없는 검사 안내입니다.'})
        self.page.dismiss_report(revision, group)
        # 바뀐 상태는 foldersChanged로만 보낸다. 늦게 도착한 응답이 그사이 온 새 결과를 덮지 않게 데이터를 싣지 않는다.
        return encode({'ok': True})

    @FOLDERS.slot('setMinimum')
    def setMinimum(self, seconds):
        try:
            if self.page.library.worker is not None:
                raise ValueError('검사가 끝난 뒤 최소 길이를 바꿔 주세요.')
            if not math.isfinite(seconds) or not 0 <= seconds <= 86400 * 365:
                raise ValueError('최소 길이는 0~31536000초 사이로 입력하세요.')
            self.page.core.set_minimum_duration(seconds)
            self.page.library.refresh()
            return self.snapshot()
        except (ValueError, OSError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @FOLDERS.slot('action')
    def action(self, name, target):
        if name not in self.scan_locked | {'restoreDismissed', 'manageTags'}:
            return encode({'error': '지원하지 않는 작업입니다.'})
        if self.busy or (name in self.scan_locked and self.page.library.worker is not None):
            return encode({'error': '진행 중인 검사가 끝난 뒤 다시 시도하세요.'})
        self.busy = True
        QTimer.singleShot(0, lambda: self.perform(name, target))
        return encode({'ok': True})

    def perform(self, name, target):
        library, core = self.page.library, self.page.core
        try:
            # 응답 이후 검사 시작과 경합해도 코어 잠금을 기다리며 UI를 멈추지 않는다.
            if name in self.scan_locked and library.worker is not None:
                raise ValueError('진행 중인 검사가 끝난 뒤 다시 시도하세요.')
            if name == 'addFolder':
                library.add_folder()
            elif name == 'addFile':
                library.library_controls.add_file()
            elif name == 'scan':
                library.scan()
            elif name == 'manageTags':
                library.manage_tags()
            elif name == 'removeFolder':
                if target not in {str(folder.path) for folder in core.watched_folders()}:
                    raise ValueError('현재 감시 목록에 없는 폴더입니다.')
                core.remove_watched_folder(target)
                library.refresh()
            else:
                videos = core.excluded_videos() if name == 'restoreExcluded' else core.dismissed_videos()
                video_id = int(target)
                if video_id not in {video.id for video in videos}:
                    raise ValueError('현재 되돌리기 목록에 없는 영상입니다.')
                if name == 'restoreExcluded':
                    core.restore_video(video_id)
                else:
                    core.restore_dismissed_video(video_id)
                library.refresh()
        except Exception as error:
            self.foldersError.emit(str(error))
        finally:
            self.busy = False
            self.page.refresh()


class WebFoldersPage(WebPageController):
    tab = 'folders'
    default_focus = 'folders-add'

    def __init__(self, host):
        super().__init__(host)
        self.library = host.controllers['library']
        self.report = ScanReport('폴더를 추가하면 자동으로 검사합니다.')
        self.report_revision = 0
        self.bridge = FoldersBridge(self)
        self.unwatched = ()
        # 감시 실패는 신호 없이 바뀌므로 보이는 동안만 가볍게 확인한다.
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll_unwatched)
        self.focus_requested = self.bridge.foldersFocusRequested
        self.library.scan_state_changed.connect(lambda _: self.refresh())
        self.library.scan_message.connect(self.report_scan)
        self.library.refreshed.connect(self.refresh)
        host.register_page(self)

    def activated(self):
        self.timer.start()

    def reshown(self):
        # 감시 실패는 알림 없이 바뀌므로 숨어 있던 동안 바뀌었는지 함께 본다.
        if self.outdated or tuple(map(str, self.window.folder_watch.unwatched_folders())) != self.unwatched:
            self.refresh()

    def deactivated(self):
        self.timer.stop()

    def poll_unwatched(self):
        if tuple(map(str, self.window.folder_watch.unwatched_folders())) != self.unwatched:
            self.refresh()

    def open_section(self, section):
        if section not in ('folders', 'excluded', 'dismissed'):
            raise ValueError('없는 폴더 관리 구역입니다.')
        self.window.navigate_web_tab('folders')
        self.host.request_focus('folders-' + section)

    def report_scan(self, report):
        self.report = report
        self.report_revision += 1
        self.refresh()

    def dismiss_report(self, revision, group):
        # 응답 전에 새 결과가 왔으면 사용자가 보지 못한 새 결과를 닫지 않는다.
        if revision == self.report_revision and self.report.finished:
            self.report = self.report.dismiss(group)
            self.refresh()

    def payload(self):
        def rows(videos):
            return [dict(id=video.id, title=video.title, missing=video.missing,
                         excluded=video.excluded) for video in videos]
        watch = self.window.folder_watch
        self.unwatched = tuple(map(str, watch.unwatched_folders()))
        return dict(folders=[str(folder.path) for folder in self.core.watched_folders()],
                    excluded=rows(self.core.excluded_videos()), dismissed=rows(self.core.dismissed_videos()),
                    minimum=self.core.minimum_duration, scanning=self.library.worker is not None,
                    report=scan_report_data(self.report, self.report_revision), automaticDetection=watch.enabled,
                    unwatched=list(self.unwatched), watchStartFailed=watch.enabled and watch.start_failed)

    def refresh(self):
        if self.is_active():
            self.publish(self.bridge.foldersChanged, self.payload())
        else:
            self.synced_change = None
