"""대기열 작업과 자동 규칙의 제한된 공개 브리지."""
import sqlite3
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .subtitle_queue_kind import ONSCREEN_SUBTITLE, TRANSCRIPTION
from .web_queue_contract import QUEUE
from .web_json import encode


class _BulkResult(QObject):
    completed = Signal(object)


class _BulkRefinement(QRunnable):
    def __init__(self, core, signals):
        super().__init__()
        self.core, self.signals = core, signals

    def run(self):
        try:
            count, skipped = self.core.request_existing_refinements()
            result = {'message': f'다듬기 {count}개를 요청했습니다. 사용자가 뺀 영상 {skipped}개는 건너뛰었습니다.'}
        except Exception as error:
            result = {'error': str(error)}
        try:
            self.signals.completed.emit(result)
        except RuntimeError:
            pass  # 종료된 화면에는 결과를 보내지 않는다. 등록 트랜잭션은 끝까지 보존한다.


class QueueBridge(QObject):
    queueChanged = QUEUE.signal('queueChanged')
    rulesChanged = QUEUE.signal('rulesChanged')
    queueFocusRequested = QUEUE.signal('queueFocusRequested')
    queueDeactivated = QUEUE.signal('queueDeactivated')
    preparationChanged = QUEUE.signal('preparationChanged')
    bulkFinished = QUEUE.signal('bulkFinished')

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.bulk_running = False
        self._bulk_signals = _BulkResult()
        self._bulk_signals.completed.connect(page.bulk_completed)
        page.window.subtitles.preparation_changed.connect(lambda value: self.preparationChanged.emit(encode(value)))

    @QUEUE.slot('preparationSnapshot')
    def preparationSnapshot(self):
        return encode(self.page.window.subtitles.preparation)

    @QUEUE.slot('preparationAction')
    def preparationAction(self, action):
        controls = self.page.window.subtitles
        if action == 'cancel':
            controls.cancel_preparation()
        elif action == 'retry':
            controls.prepare()
        else:
            return encode({'error': '지원하지 않는 준비 작업입니다.'})
        return encode({'ok': True})

    @QUEUE.slot('ready')
    def ready(self):
        self.page.frontend_ready()
        return encode({'ok': True})

    @QUEUE.slot('snapshot')
    def snapshot(self):
        return self.page.stamp(self.page.payload())

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
    def action(self, name, video_id, queue_kind):
        def execute():
            core = self.page.core
            if name == 'previewRefineExisting':
                count, skipped = core.existing_refinement_candidates()
                return {'confirmation': f'아직 다듬지 않은 한국어 영상 {count}개를 자동 대상 우선순위로 추가할까요? '
                        f'사용자가 뺀 영상 {skipped}개는 건너뜁니다.'}
            if name == 'refineExisting':
                if self.bulk_running:
                    raise ValueError('기존 한국어 자막을 대기열에 추가하고 있습니다.')
                self.bulk_running = True
                QThreadPool.globalInstance().start(_BulkRefinement(core, self._bulk_signals))
                return {'pending': True}
            if name == 'retryFailed':
                # 받아쓰기와 화면 자막의 실패 항목을 함께 다시 시도한다.
                results = [core.retry_failed_subtitles(kind=kind) for kind in (TRANSCRIPTION, ONSCREEN_SUBTITLE)]
                details = []
                for item in (skipped for result in results for skipped in result.skipped):
                    try:
                        title = core.video(item.video_id).title or str(item.video_id)
                    except (ValueError, OSError, sqlite3.Error):
                        title = str(item.video_id)
                    details.append(f'영상 {title}: {item.reason}')
                return {'message': f'재시도 {sum(r.retried for r in results)}개 · '
                                   f'건너뜀 {sum(r.skipped_count for r in results)}개' +
                        ('\n' + '\n'.join(details) if details else '')}
            if (video_id, queue_kind) not in {(entry.video_id, entry.queue_kind) for entry in core.subtitle_queue_items()}:
                raise ValueError('현재 대기열에 없는 항목입니다.')
            if name == 'promote':
                core.promote_subtitle(video_id, kind=queue_kind)
            elif name == 'remove':
                core.remove_from_subtitle_queue(video_id, kind=queue_kind)
            elif name == 'retryHeld':
                if queue_kind == TRANSCRIPTION and any(e.video_id == video_id and e.state == 'held'
                                                       for e in core.translation_queue()):
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
