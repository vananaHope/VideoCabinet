"""활성 대기열만 조회하고 변경된 행만 웹에 보낸다."""
from PySide6.QtCore import QTimer, Slot

from .subtitle_queue_kind import TRANSCRIPTION
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
        self.counts = counts_data(())
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
        return dict(rows=[row_data(self.entries[id]) for id in self.order], removed=[],
                    order=self.order, counts=self.counts,
                    canRetryFailed=any(item.state == 'failed' for item in self.entries.values()))

    def refresh(self):
        if not self.is_active() or self.bridge.bulk_running:
            return
        items = tuple(item for item in self.core.subtitle_queue_items() if item.queue_kind == TRANSCRIPTION)
        entries = {item.video_id: item for item in items}
        order = list(entries)
        changed = [row_data(item) for item in items if self.entries.get(item.video_id) != item]
        removed = list(self.entries.keys() - entries.keys())
        if not changed and not removed and order == self.order:
            return
        counts = counts_data(items)
        delta = dict(rows=changed, removed=removed,
                     canRetryFailed=any(item.state == 'failed' for item in items),
                     order=order if order != self.order else None,
                     counts=counts if counts != self.counts else None)
        self.entries, self.order, self.counts = entries, order, counts
        self.bridge.queueChanged.emit(self.stamp(delta))

    def reshown(self):
        # 대기열은 알림 없이 바뀌므로 다시 보일 때 비교해 바뀐 행만 보낸다. 같으면 아무것도 보내지 않는다.
        self.refresh()

    def refresh_rules(self):
        if self.is_active():
            data = rules_data(self.core)
            if data != self.rules:
                self.rules = data
                self.bridge.rulesChanged.emit(encode(data))
