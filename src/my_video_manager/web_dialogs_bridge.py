"""대화상자 명령은 현재 프레임 ID로 한정하고 예외를 웹 오류로 전달한다."""
import json

from PySide6.QtCore import QObject

from .web_dialogs_contract import DIALOGS
from .web_json import encode


class DialogsBridge(QObject):
    dialogsChanged = DIALOGS.signal('dialogsChanged')

    def __init__(self, dialogs):
        super().__init__(dialogs)
        self.dialogs = dialogs

    @DIALOGS.slot('snapshot')
    def snapshot(self):
        return encode(self.dialogs.snapshot())

    @DIALOGS.slot('modalState')
    def modalState(self, opened):
        # 주 창의 숨김·최소화와 재생 화면에 가려진 셸을 구분한다. 숨김 중에도
        # 열림/닫힘을 수신 순서대로 기록해야 트레이 복귀의 동기 판단에 쓸 수 있다.
        # 재생으로 셸 자체가 숨겨졌다면 늦은 열림 알림은 차단을 되살리지 않는다.
        self.dialogs.web_modal = bool(opened) and self.dialogs.host.isVisibleTo(self.dialogs.window)
        self.dialogs.sync_shortcut()
        return encode({'ok': True})

    @DIALOGS.slot('contentSize')
    def contentSize(self, identifier, width, height):
        if self.dialogs.active and self.dialogs.stack[-1].identifier == identifier and width > 0 and height > 0:
            self.dialogs.resize_container(width, height)
        return encode({'ok': True})

    @DIALOGS.slot('act')
    def act(self, identifier, action, payload):
        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError('잘못된 대화상자 입력입니다.')
            self.dialogs.act(identifier, action, data)
            return encode(self.dialogs.snapshot())
        except Exception as error:
            return encode({'error': str(error)})
