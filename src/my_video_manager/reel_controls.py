"""모아보기 엔진 전환과 재생 화면의 상태 연결."""
from .core import CommandType
from .key_display import display_keys


class ReelControls:
    def __init__(self, window):
        self.window, self.core = window, window.core
        self.shown = None

    def sync(self):
        current = self.core.reel_playback
        if current == self.shown:
            self.update_label()
            return
        if current is not None and current.action == "seek" and self.window.player:
            # 같은 영상은 파일을 다시 열지 않는다. 명령의 판단은 코어가 담당한다.
            self.window.player.seek_to(current.start, resume=True)
            self.shown = current
            self.window.refresh_highlights()
            self.update_label()
            return
        options = None
        if self.window.player:
            options = self.window.player.playback_options()
            if current is None:
                # 완료 복귀도 일반 목록 복귀와 같은 준비·종료 경계를 쓴다.
                self.shown = current
                self.open()
                return
            # 코어는 이미 새 항목으로 전환했다. 이전 엔진에 남은 보고는 새 항목에 보내지 않는다.
            self.window.stop_player(report=False)
        self.shown = current
        if current is None:
            self.open()
            return
        try:
            location = self.core.playback_location(current.video_id)
            self.window.pages.setCurrentIndex(1)
            self.window.player = self.window.create_player()
            if options is not None:
                self.window.player.apply_playback_options(options)
            self.window.player.play(location.path, current.start,
                                    subtitle=self.core.playback_subtitle(current.video_id))
            self.window.progress.duration = current.entry.duration
            self.window.refresh_highlights()
            self.window.position_timer.start()
            self.window.surface.setFocus()
            self.update_label()
        except Exception:
            self.open()
            raise

    def update_label(self):
        keys = {row.command.kind: display_keys(row.keys) for row in self.core.key_bindings()}
        self.window.playback_page.show_reel(self.core.reel_playback, self.core.reel_repeat, keys)
