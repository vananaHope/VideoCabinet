"""DB와 웹 셸을 열 수 없어도 접근할 수 있는 시작 복구 화면."""
from pathlib import Path
import sys

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .backup import backup_error_message, apply_pending_backup_restore, cancel_backup_restore, pending_backup_restore_path


class BackupRecoveryDialog(QDialog):
    def __init__(self, database, result, error):
        super().__init__()
        self.database = Path(database)
        self.setWindowTitle('라이브러리 백업 복구')
        self.resize(640, 360)
        layout = QVBoxLayout(self)
        title = QLabel('현재 라이브러리를 열 수 없습니다')
        title.setWordWrap(True)
        layout.addWidget(title)
        guidance = ((result.error_message or '') + '\n' + result.guidance if result is not None else
                    '예약된 백업 복원이 없습니다. 현재 라이브러리를 열 수 없는 원인을 해결한 뒤 다시 시도하세요.')
        startup_error = error.strerror if isinstance(error, OSError) and error.strerror else str(error)
        self.message = QLabel(guidance + '\n\n시작 오류: 라이브러리를 열지 못했습니다. ' + startup_error)
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.message)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.retry = QPushButton('다시 시도')
        self.retry.setDefault(True)
        self.retry.clicked.connect(self.accept)
        buttons.addWidget(self.retry)
        self.cancel = QPushButton('예약 취소')
        self.cancel.setEnabled(pending_backup_restore_path(self.database).exists())
        self.cancel.clicked.connect(self.cancel_pending)
        buttons.addWidget(self.cancel)
        self.open_folder = QPushButton('데이터 폴더 열기')
        self.open_folder.clicked.connect(self.open_data_folder)
        buttons.addWidget(self.open_folder)
        close = QPushButton('닫기')
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.retry.setFocus()

    def cancel_pending(self):
        try:
            cancel_backup_restore(self.database)
        except OSError as error:
            QMessageBox.warning(self, '예약 취소 실패', backup_error_message(error))
            return
        self.cancel.setEnabled(False)
        self.message.setText('백업 복원 예약을 취소했습니다. 현재 데이터와 보존 사본은 그대로 남아 있습니다.\n'
                             '현재 라이브러리를 열 수 없는 원인을 해결한 뒤 다시 시도하거나 앱을 닫으세요.\n\n'
                             '예약 파일 위치(취소됨): ' + str(pending_backup_restore_path(self.database)))
        self.retry.setFocus()

    def open_data_folder(self):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.database.parent))):
            QMessageBox.warning(self, '폴더 열기 실패', '탐색기에서 이 경로를 열어 주세요.\n' + str(self.database.parent))


def open_with_backup_recovery(database, instance, create_core):
    """단일 인스턴스 잠금을 유지하며 재시도한다. DB 연결 전 적용 순서는 동일하다."""
    previous_failure = None
    while True:
        result = apply_pending_backup_restore(database, instance=instance)
        try:
            core = create_core()
        except Exception as error:
            if result is not None and result.status == 'deferred':
                previous_failure = result
            if previous_failure is None:
                raise
            dialog = BackupRecoveryDialog(database, result, error)
            retry = dialog.exec() == QDialog.DialogCode.Accepted
            dialog.deleteLater()
            if retry:
                continue
            return None
        core.set_backup_restore_startup_result(result)
        return core


def restart_command(data_directory):
    """설치판과 소스 실행 모두 같은 데이터 폴더로 다시 연다."""
    arguments = [] if getattr(sys, 'frozen', False) else ['-m', 'my_video_manager']
    return sys.executable, [*arguments, '--data-dir', str(Path(data_directory).resolve())]
