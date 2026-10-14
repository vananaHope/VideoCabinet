import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="개인 영상 라이브러리")
    parser.add_argument("--data-dir", type=Path, help="데이터를 저장할 폴더 (기본: 사용자 프로필/.my-video-manager)")
    args = parser.parse_args()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .adapters import FFmpegMediaReader
    from .core import AppCore, default_data_directory
    from .transcription import FasterWhisperTranscriber
    from .translation_cli import SubscriptionCLITranslator
    from .ui import MainWindow
    from .single_instance import SingleInstance

    app = QApplication(sys.argv[:1])
    from .theme import apply_theme
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    try:
        data_directory = args.data_dir or default_data_directory()
        instance = SingleInstance(data_directory, app)
        if not instance.start():
            return 0
        core = AppCore(media=FFmpegMediaReader(), clock=lambda: datetime.now(timezone.utc),
                       transcriber=FasterWhisperTranscriber(data_directory / "models"),
                       translator=SubscriptionCLITranslator(data_directory),
                       database=args.data_dir / "library.sqlite3" if args.data_dir else None)
        window = MainWindow(core)
        instance.activated.connect(window.tray.open)
        app.aboutToQuit.connect(instance.close)
    except Exception as error:
        QMessageBox.critical(None, "시작 실패", str(error))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
