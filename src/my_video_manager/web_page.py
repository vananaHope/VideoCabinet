"""셸에 등록하는 페이지 컨트롤러의 작은 공통 인터페이스."""

from PySide6.QtWidgets import QWidget

from .web_json import encode


class WebPageController(QWidget):
    # QWidget은 부모 소유권과 이벤트 수명주기를 위한 것이다. 화면은 호스트 하나에만 있다.
    default_focus = 'shell'
    # 재생 중 창을 닫았다가 트레이로 열 때 라이브러리 대신 이 탭으로 돌아온다.
    keeps_tab_after_close = False
    bridge = None
    focus_requested = None

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.window, self.core = host.window, host.core
        # 이 페이지가 내보낸 상태 메시지의 세대(#265). 메시지마다 하나씩 올라간다.
        self.generation = 0
        # 웹이 마지막으로 전체 상태를 받은 때의 호스트 변경 번호. None이면 받은 뒤 바뀐 것이 있다.
        self.synced_change = None
        self.hide()

    def is_active(self):
        return self.host.isVisible() and self.host.active_tab == self.tab

    def stamp(self, data):
        """상태 메시지에 새 세대를 붙인 JSON. 밀어 보내는 changed와 요청 응답이 함께 쓴다."""
        self.generation += 1
        return encode({**data, 'generation': self.generation})

    def publish(self, signal, data):
        """보이는 동안만 전체 상태를 보낸다. 숨어 있으면 다시 보일 때 한 번 보내도록 표시만 한다."""
        if not self.is_active():
            self.synced_change = None
            return False
        signal.emit(self.stamp(data))
        self.synced_change = self.host.change
        return True

    @property
    def outdated(self):
        return self.synced_change != self.host.change

    def reshown(self):
        """탭이 다시 보일 때. 숨어 있던 동안 바뀐 것이 있을 때만 다시 만들어 보낸다."""
        if self.outdated:
            self.refresh()

    def activated(self):
        pass

    def deactivated(self):
        pass

    def return_from_playback(self):
        self.refresh()
        self.focus_content()

    def focus_content(self):
        self.request_focus(self.default_focus)

    def request_focus(self, target):
        self.host.request_focus(target)

    def frontend_ready(self):
        self.host.page_ready(self.tab)

    def entry_data(self):
        """웹이 처음 그리기 전에 받을 이 페이지의 상태(#267). 없으면 None이다."""
        return None

    def refresh(self):
        pass

    def refresh_details(self):
        pass
