import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


def main():
    # Qt, 단일 인스턴스, 데이터 복원보다 먼저 격리된 자식 명령을 분기한다.
    if sys.argv[1:2] == ["transcription"]:
        from .transcription import main as transcription_main
        return transcription_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description="개인 영상 라이브러리")
    from .app_version import current_version
    parser.add_argument('--version', action='version', version=current_version())
    parser.add_argument("--data-dir", type=Path, help="데이터를 저장할 폴더 (기본: 사용자 프로필/.my-video-manager)")
    args = parser.parse_args()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .adapters import FFmpegMediaReader
    from .core import AppCore, default_data_directory
    from .transcription import FasterWhisperTranscriber
    from .translation_cli import SubscriptionCLITranslator
    from .ui import MainWindow
    from .single_instance import SingleInstance

    from .web_thumbnail import register_thumbnail_scheme
    register_thumbnail_scheme()
    app = QApplication(sys.argv[:1])
    from PySide6.QtGui import QIcon
    icon = Path(__file__).with_name('app.ico')
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    from .theme import apply_theme
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    instance = None
    try:
        data_directory = args.data_dir or default_data_directory()
        instance = SingleInstance(data_directory, app)
        if not instance.start():
            return 0
        from .app_logging import configure_app_logging
        configure_app_logging(data_directory)
        from .backup_recovery import open_with_backup_recovery
        core = open_with_backup_recovery(data_directory / "library.sqlite3", instance,
            lambda: AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc),
                       transcriber=FasterWhisperTranscriber(data_directory / "models"),
                       translator=SubscriptionCLITranslator(data_directory),
                       database=args.data_dir / "library.sqlite3" if args.data_dir else None))
        if core is None:
            instance.close()
            return 1
        window = MainWindow(core)
        instance.activated.connect(window.tray.open)
        app.aboutToQuit.connect(instance.close)
    except Exception as error:
        import logging
        logging.getLogger(__name__).exception('앱 시작 실패')
        message = str(error)
        QMessageBox.critical(None, "시작 실패", message)
        if instance is not None:
            instance.close()
        return 1
    window.show()
    status = app.exec()
    if app.property('backupRestartRequested'):
        from PySide6.QtCore import QProcess
        from .backup_recovery import restart_command
        instance.close()
        program, arguments = restart_command(data_directory)
        if not QProcess.startDetached(program, arguments)[0]:
            QMessageBox.critical(None, '재시작 실패',
                                 '앱을 다시 실행해 주세요. 백업 복원 예약은 그대로 남아 있습니다.')
            return 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
