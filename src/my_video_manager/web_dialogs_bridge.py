"""대화상자 명령은 현재 프레임 ID로 한정하고 예외를 웹 오류로 전달한다."""
import json

from PySide6.QtCore import QObject

from .web_contract import DIALOGS
from .web_dialogs_data import row
from .web_json import encode


class DialogsBridge(QObject):
    dialogsChanged = DIALOGS.signal('dialogsChanged')

    def __init__(self, dialogs):
        super().__init__(dialogs)
        self.dialogs = dialogs

    @DIALOGS.slot('snapshot')
    def snapshot(self):
        return encode(self.dialogs.snapshot())

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
