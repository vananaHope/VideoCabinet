"""대기열 작업과 자동 규칙의 제한된 공개 브리지."""
import sqlite3
from pathlib import Path

from PySide6.QtCore import QObject

from .web_contract import QUEUE
from .web_json import encode


class QueueBridge(QObject):
    queueChanged = QUEUE.signal('queueChanged')
    rulesChanged = QUEUE.signal('rulesChanged')
    queueFocusRequested = QUEUE.signal('queueFocusRequested')
    queueDeactivated = QUEUE.signal('queueDeactivated')

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    @QUEUE.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @QUEUE.slot('snapshot')
    def snapshot(self):
        return encode(self.page.payload())

    @QUEUE.slot('rulesSnapshot')
    def rulesSnapshot(self):
        self.page.refresh_rules()
        return encode(self.page.rules)

    def perform(self, callback):
        try:
            if not self.page.is_active():
                raise ValueError('자막 대기열 페이지에서 실행해 주세요.')
            result = callback()
            self.page.refresh()
            return encode(result or {'ok': True})
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
            return encode({'error': str(error)})

    @QUEUE.slot('action')
    def action(self, name, video_id):
        def execute():
            core = self.page.core
            if name == 'retryFailed':
                result = core.retry_failed_subtitles()
                details = []
                for item in result.skipped:
                    try:
                        title = core.video(item.video_id).title or str(item.video_id)
                    except (ValueError, OSError, sqlite3.Error):
                        title = str(item.video_id)
                    details.append(f'영상 {title}: {item.reason}')
                return {'message': f'재시도 {result.retried}개 · 건너뜀 {result.skipped_count}개' +
                        ('\n' + '\n'.join(details) if details else '')}
            if video_id not in {entry.video_id for entry in core.subtitle_queue_items()}:
                raise ValueError('현재 대기열에 없는 영상입니다.')
            if name == 'promote':
                core.promote_subtitle(video_id)
            elif name == 'remove':
                core.remove_from_subtitle_queue(video_id)
            elif name == 'retryHeld':
                if any(e.video_id == video_id and e.state == 'held' for e in core.translation_queue()):
                    core.request_translation(video_id)
            else:
                raise ValueError('지원하지 않는 작업입니다.')
        return self.perform(execute)

    def target(self, key):
        core = self.page.core
        if key.startswith('folder:'):
            folder = Path(key[7:])
            if folder in {f.path for f in core.watched_folders()}:
                return {'folder': folder}
        elif key.startswith('tag:'):
            tag_id = int(key[4:])
            if tag_id in {t.id for t in core.tags()}:
                return {'tag_id': tag_id}
        raise ValueError('감시 폴더 또는 태그 하나를 고르세요.')

    @QUEUE.slot('candidates')
    def candidates(self, target):
        return self.perform(lambda: {'count': len(self.page.core.auto_subtitle_candidates(**self.target(target)))})

    @QUEUE.slot('saveRule')
    def saveRule(self, target, language, include_existing):
        def save():
            value = language.strip()
            self.page.core.set_auto_subtitle_rule(**self.target(target),
                spoken_language=None if value == '자동 감지' else value, include_existing=include_existing)
            self.page.refresh_rules()
        return self.perform(save)

    @QUEUE.slot('removeRule')
    def removeRule(self, rule_id):
        def remove():
            self.page.core.remove_auto_subtitle_rule(rule_id)
            self.page.refresh_rules()
        return self.perform(remove)
