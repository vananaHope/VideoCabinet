"""데이터 폴더별 소유권 잠금과 기존 창 활성화용 로컬 IPC 어댑터."""

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QObject, QLockFile, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .app_version import DISPLAY_NAME


def instance_name(data_directory):
    canonical = os.path.normcase(str(Path(data_directory).resolve()))
    return "my-video-manager-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, data_directory, parent=None):
        super().__init__(parent)
        directory = Path(data_directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.name = instance_name(directory)
        self.lock_path = directory / "instance.lock"
        self.lock = QLockFile(str(self.lock_path))
        self.lock.setStaleLockTime(0)  # 살아 있는 장시간 실행 프로세스를 오래됐다고 제거하지 않는다.
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.activate)

    def start(self):
        if self.lock.tryLock(0):
            # 잠금을 가진 프로세스만 이전 비정상 종료의 소켓을 지울 수 있다.
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                self.lock.unlock()
                raise RuntimeError(f"단일 인스턴스 서버를 열 수 없습니다: {self.server.errorString()}")
            return True
        socket = QLocalSocket(self)
        socket.connectToServer(self.name)
        if not socket.waitForConnected(3000):
            raise RuntimeError("같은 데이터 폴더의 앱에 연결할 수 없습니다. 잠시 뒤 다시 실행하세요.\n"
                               f"계속 실패하면 작업 관리자에서 {DISPLAY_NAME} 프로세스가 모두 종료됐는지 확인한 뒤, "
                               f"아래 잠금 파일만 삭제하고 다시 실행하세요.\n잠금 파일: {self.lock_path}")
        socket.disconnectFromServer()
        return False

    def activate(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.close()
            socket.deleteLater()
            self.activated.emit()

    def close(self):
        self.server.close()
        self.lock.unlock()
