"""앱과 자막 준비가 공유하는 크기 제한·민감 정보 가림 파일 로그."""
import logging
from copy import copy
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re


LOG_MAX_BYTES = 256 * 1024
LOG_BACKUP_COUNT = 2


def safe_detail(detail):
    """예외 객체와 이미 문자열이 된 진단 모두에서 인증 값과 홈 경로를 가린다."""
    if isinstance(detail, OSError) and detail.strerror is not None:
        parts = [f'[Errno {detail.errno}] {detail.strerror}']
        parts.extend(str(name) for name in (detail.filename, detail.filename2) if name is not None)
        detail = ': '.join(parts)
    detail = re.sub(r'https?://[^\s<>\"\']+',
                    lambda match: re.sub(r'(https?://)[^/]*@', r'\1[가림]@',
                                         re.split(r'[?#]', match[0], maxsplit=1)[0]), str(detail))
    detail = re.sub(r'\bhf_[A-Za-z0-9]+\b', '[가림]', detail)
    detail = re.sub(r'''(?i)((?:authorization|token|api[\s_-]*key|password|secret)["']?\s*[:=]\s*["']?(?:bearer\s+)?|\bbearer\s+)[^\s,;"'<>}]+''',
                    r'\1[가림]', detail)
    home = str(Path.home())
    for path in sorted({home, Path.home().as_posix(), home.replace('\\', '\\\\')}, key=len, reverse=True):
        detail = re.sub(re.escape(path), '~', detail, flags=re.IGNORECASE)
    return detail


class _SafeFormatter(logging.Formatter):
    def format(self, record):
        # 예외 체인과 traceback 파일명까지 포맷한 뒤 가린다. 다른 핸들러의 레코드는 보존한다.
        text = safe_detail(super().format(copy(record)))
        data = text.encode('utf-8')
        if len(data) > LOG_MAX_BYTES - 128:
            text = data[:LOG_MAX_BYTES - 128].decode('utf-8', errors='ignore') + ' [생략]'
        return text


class _QuietRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        return open(self.baseFilename, self.mode, encoding=self.encoding,
                    errors=self.errors, newline='')

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        # 한글 진단도 문자 수가 아닌 UTF-8 바이트 수로 제한한다.
        return self.stream.tell() + len((self.format(record) + self.terminator).encode('utf-8')) >= self.maxBytes

    def handleError(self, record):
        # 디스크 부족/읽기 전용/회전 실패가 앱을 중단하거나 stderr에 원문을 노출하지 않는다.
        pass


def file_log_handler(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _QuietRotatingFileHandler(path, maxBytes=LOG_MAX_BYTES,
                                       backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    handler.setFormatter(_SafeFormatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
    return handler


def configure_app_logging(directory):
    """단일 인스턴스 확보 뒤 호출한다. 초기화 실패도 앱 시작을 막지 않는다."""
    logger = logging.getLogger('my_video_manager')
    for handler in tuple(logger.handlers):
        if isinstance(handler, _QuietRotatingFileHandler):
            logger.removeHandler(handler)
            handler.close()
    try:
        handler = file_log_handler(Path(directory) / 'logs/app.log')
    except (OSError, ValueError):
        return None
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler
