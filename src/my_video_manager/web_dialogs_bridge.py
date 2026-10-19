"""대화상자 명령은 현재 프레임 ID로 한정하고 예외를 웹 오류로 전달한다."""
import json

from PySide6.QtCore import QObject

from .web_dialogs_contract import DIALOGS
from .web_dialogs_data import row
from .web_json import encode


class DialogsBridge(QObject):
    dialogsChanged = DIALOGS.signal('dialogsChanged')
    popupRestore = DIALOGS.signal('popupRestore')

    def __init__(self, dialogs):
        super().__init__(dialogs)
        self.dialogs = dialogs

    @DIALOGS.slot('snapshot')
    def snapshot(self):
        return encode(self.dialogs.snapshot())

    @DIALOGS.slot('modalState')
    def modalState(self, opened):
        self.dialogs.web_modal = bool(opened) and self.dialogs.host.isVisible()
        self.dialogs.sync_shortcut()
        return encode({'ok': True})

    @DIALOGS.slot('popupState')
    def popupState(self, identifier):
        # 긴급 탈출 때 다시 열 목록. 빈 문자열은 열린 목록 없음.
        self.dialogs.open_popup = identifier
        return encode({'ok': True})

    @DIALOGS.slot('contentSize')
    def contentSize(self, identifier, width, height):
        if self.dialogs.active and self.dialogs.stack[-1].identifier == identifier and width > 0 and height > 0:
            self.dialogs.resize_container(width, height)
        return encode({'ok': True})

    @DIALOGS.slot('candidates')
    def candidates(self, prefix):
        try:
            return encode({'rows': [row(tag.id, tag.name) for tag in self.dialogs.core.tags(prefix)]})
        except Exception as error:
            return encode({'error': str(error)})

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
