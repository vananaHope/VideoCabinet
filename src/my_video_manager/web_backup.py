"""설정 안의 백업 작업 수명. ZIP 작업은 UI 스레드 밖에서 직렬 실행한다."""
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from .backup import backup_error_message
from .web_json import encode


class BackupWorker(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation, self.result, self.error = operation, None, ""

    def run(self):
        try:
            self.result = self.operation()
        except Exception as error:
            self.error = backup_error_message(error)


class BackupControls(QObject):
    def __init__(self, page):
        super().__init__(page)
        self.page, self.core = page, page.core
        self.worker = None
        self.busy = False
        self.preview_path = None
        self.preview_stamp = None
        startup = self.core.backup_restore_status()
        self.state = dict(busy=False, operation="", message="", failure="", preview=None, previewPath="",
                          startup=(dict(status=startup.status, error=startup.error_message or "",
                                        guidance=startup.guidance, safety_backup=str(startup.safety_backup or ""),
                                        rejected_path=str(startup.rejected_path or "")) if startup else None))
        # 첫 화면에는 ZIP을 읽지 않는다. 백업 분류 진입의 refresh가 작업자에서 목록을 읽는다.
        self.inventory(self.core.backup_inventory(include_automatic=False))

    def inventory(self, inventory):
        current = self.core.backup_restore_status()
        self.state.update(automatic=[asdict(row) for row in inventory.automatic], folder=inventory.folder,
                          pending=inventory.pending, pendingPath=inventory.pending_path,
                          pendingDeferred=bool(inventory.pending and current and current.status == 'deferred'),
                          dbVersion=inventory.db_version, keep=inventory.keep, guidance=inventory.guidance)

    def emit(self):
        self.state['busy'] = self.busy
        self.page.bridge.backupChanged.emit(encode(self.state))

    def action(self, name, target, thumbnails):
        if name not in {'refresh', 'create', 'choose', 'preview', 'schedule', 'discard', 'cancel', 'restart', 'openFolder'}:
            return encode({'error': '지원하지 않는 백업 작업입니다.'})
        if self.busy:
            if name == 'refresh':
                self.emit()
                return encode({'ok': True})
            return encode({'error': '진행 중인 백업 작업이 끝난 뒤 다시 시도하세요.'})
        self.busy = True
        self.state['operation'] = name
        if name != 'refresh':
            self.state.update(failure='', message='')
        self.emit()
        # 네이티브 대화상자보다 WebChannel 응답과 진행 표시를 먼저 보낸다.
        QTimer.singleShot(0, lambda: self.perform(name, target, thumbnails))
        return encode({'ok': True})

    @staticmethod
    def stamp(path):
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns

    def clear_preview(self):
        self.preview_path = self.preview_stamp = None
        self.state.update(preview=None, previewPath='')

    def perform(self, name, target, thumbnails):
        try:
            if name == 'create':
                path, _ = QFileDialog.getSaveFileName(self.page.window, '백업 만들기',
                    str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or Path.home()) /
                        f'library-backup-{datetime.now():%Y%m%d-%H%M%S}.zip'), '라이브러리 백업 (*.zip)')
                if not path:
                    self.finish()
                    return
                if not Path(path).suffix:
                    path += '.zip'
                operation = lambda: self.core.create_backup(Path(path), include_thumbnails=thumbnails)
            elif name in ('choose', 'preview'):
                self.clear_preview()
                if name == 'choose':
                    path, _ = QFileDialog.getOpenFileName(self.page.window, '백업 복원 파일 선택', '', '라이브러리 백업 (*.zip)')
                    if not path:
                        self.finish()
                        return
                else:
                    if target not in {row['path'] for row in self.state['automatic']}:
                        raise ValueError('자동 백업 목록을 새로고침한 뒤 다시 선택하세요.')
                    path = target
                self.preview_path = Path(path)
                self.preview_stamp = self.stamp(self.preview_path)
                operation = lambda: self.core.inspect_backup(self.preview_path)
            elif name == 'schedule':
                if not self.preview_path or not self.state['preview']:
                    raise ValueError('먼저 백업을 선택해 검사와 미리보기를 확인하세요.')
                if self.stamp(self.preview_path) != self.preview_stamp:
                    self.clear_preview()
                    raise ValueError('미리보기 후 백업 파일이 바뀌었습니다. 파일을 다시 선택하세요.')
                operation = lambda: self.core.request_backup_restore(self.preview_path)
            elif name == 'cancel':
                operation = self.core.cancel_backup_restore
            elif name == 'refresh':
                operation = self.core.backup_inventory
            else:
                if name == 'discard':
                    self.clear_preview()
                elif name == 'openFolder':
                    folder = Path(self.state['folder'])
                    folder.mkdir(exist_ok=True)
                    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                        raise OSError('자동 백업 폴더를 열지 못했습니다. 표시된 경로를 탐색기에서 열어 주세요.')
                elif name == 'restart':
                    if not self.state['pending']:
                        raise ValueError('예약된 백업 복원이 없습니다.')
                    # 정상 종료 경로가 검사·자막·번역·시청을 먼저 정리한다.
                    self.finish()
                    self.page.window.tray.restart()
                    return
                self.finish()
                return
            def run():
                result = operation()
                inventory, warning = None, ''
                if name == 'refresh':
                    inventory = result
                elif name in ('schedule', 'cancel', 'create'):
                    try:
                        inventory = self.core.backup_inventory()
                    except Exception as error:
                        warning = '작업은 완료했지만 자동 백업 목록을 읽지 못했습니다. 새로고침하세요. ' + backup_error_message(error)
                return result, inventory, warning
            self.worker = BackupWorker(run, self)
            self.worker.finished.connect(self.completed)
            self.worker.start()
        except Exception as error:
            self.finish(backup_error_message(error))

    def completed(self):
        worker, self.worker = self.worker, None
        try:
            if worker.error:
                if self.state['operation'] in ('choose', 'preview'):
                    self.clear_preview()
                self.finish(worker.error)
                return
            name = self.state['operation']
            result, inventory, warning = worker.result
            if name in ('choose', 'preview'):
                current_version = self.state['dbVersion']
                # inspect_backup가 더 최신 버전은 거부하므로 검증된 미리보기만 안내한다.
                if result.db_version < current_version:
                    version_message = (f'이 백업은 DB 버전 {result.db_version}입니다. 다시 시작하면 '
                                       f'현재 버전 {current_version}에 맞춰 바꾼 뒤 복원합니다. '
                                       '복원 전 지금 라이브러리는 자동 백업으로 남습니다.')
                else:
                    version_message = f'현재 DB 버전 {current_version}과 같은 버전의 백업입니다.'
                self.state.update(preview=dict(asdict(result), version_message=version_message),
                                  previewPath=str(self.preview_path))
            elif name == 'create':
                self.state['message'] = '백업을 만들었습니다: ' + str(result.path)
            elif name == 'schedule':
                self.clear_preview()
                self.state.update(pending=True, pendingDeferred=False)
                self.state['message'] = '백업 복원을 예약했습니다. 다시 시작하면 적용됩니다.'
            elif name == 'cancel':
                self.state.update(pending=False, pendingDeferred=False)
                self.state['message'] = '백업 복원 예약을 취소했습니다. 현재 라이브러리는 그대로 유지됩니다.'
            if inventory is not None:
                self.inventory(inventory)
            self.finish(warning or None)
        except Exception as error:
            self.finish(backup_error_message(error))
        finally:
            worker.deleteLater()

    def finish(self, error=None):
        self.busy = False
        self.state['operation'] = ''
        if error is not None:
            self.state['failure'] = error
        self.emit()
