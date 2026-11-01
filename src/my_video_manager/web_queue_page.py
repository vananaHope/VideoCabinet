"""활성 대기열만 조회하고 바뀌었을 때 전체 항목 목록을 웹에 보낸다."""
from PySide6.QtCore import QTimer, Slot

from .web_page import WebPageController
from .web_queue_bridge import QueueBridge
from .web_queue_data import counts_data, row_data, rules_data
from .web_json import encode


class WebQueuePage(WebPageController):
    tab = 'queue'
    default_focus = 'queue-list'

    def __init__(self, host):
        super().__init__(host)
        self.entries = {}
        self.order = []
        self.rules = dict(targets=[], rules=[])
        self.bridge = QueueBridge(self)
        self.focus_requested = self.bridge.queueFocusRequested
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        host.register_page(self)

    @Slot(object)
    def bulk_completed(self, result):
        self.bridge.bulk_running = False
        try:
            self.refresh()
        finally:
            self.bridge.bulkFinished.emit(encode(result))

    def activated(self):
        # 호스트의 refresh() 경로와 달리 규칙 대상은 활성화 때 한 번만 조회한다.
        self.refresh_rules()
        self.timer.start()

    def deactivated(self):
        self.timer.stop()
        self.bridge.queueDeactivated.emit('')

    def payload(self):
        # 늦게 도착한 앞 메시지를 버려도 잃는 것이 없게 매번 전체 항목을 보낸다(#265). 웹은 바뀐 행만 다시 그린다.
        entries = [self.entries[id] for id in self.order]
        return dict(rows=[row_data(entry) for entry in entries], counts=counts_data(entries),
                    canRetryFailed=any(entry.state == 'failed' for entry in entries))

    def refresh(self):
        if not self.is_active() or self.bridge.bulk_running:
            return
        entries = {(item.video_id, item.queue_kind): item for item in self.core.subtitle_queue_items()}
        order = list(entries)
        if entries == self.entries and order == self.order:
            return
        self.entries, self.order = entries, order
        self.bridge.queueChanged.emit(self.stamp(self.payload()))

    def reshown(self):
        # 대기열은 알림 없이 바뀌므로 다시 보일 때 비교해 바뀌었을 때만 보낸다. 같으면 아무것도 보내지 않는다.
        self.refresh()

    def refresh_rules(self):
        if self.is_active():
            data = rules_data(self.core)
            if data != self.rules:
                self.rules = data
                self.bridge.rulesChanged.emit(encode(data))
