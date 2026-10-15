"""준비의 마지막 결과를 데이터 폴더에 원자적으로 보존한다."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import tempfile
from threading import Lock


_log_lock = Lock()


def safe_detail(detail):
    """진단 원문에서 인증 값과 사용자 홈 경로만 가린다."""
    if isinstance(detail, OSError) and detail.strerror is not None:
        # OSError.__str__은 파일명을 repr로 넣어 Windows 경로를 이중 이스케이프한다.
        parts = [f'[Errno {detail.errno}] {detail.strerror}']
        parts.extend(str(name) for name in (detail.filename, detail.filename2) if name is not None)
        detail = ': '.join(parts)
    detail = re.sub(r'https?://[^\s<>\"\']+',
                    lambda match: re.sub(r'(https?://)[^/]*@', r'\1[가림]@',
                                         re.split(r'[?#]', match[0], maxsplit=1)[0]), str(detail))
    detail = re.sub(r'\bhf_[A-Za-z0-9]+\b', '[가림]', detail)
    detail = re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|(?:token|api[_-]?key|password|secret)\s*[:=]\s*)[^\s,;]+',
                    r'\1[가림]', detail)
    for home in (str(Path.home()), Path.home().as_posix()):
        detail = re.sub(re.escape(home), '~', detail, flags=re.IGNORECASE)
    return detail


def log_failure(directory, kind, message, detail):
    """실패는 ERROR, 사용자 취소·중단은 INFO로 기록한다. 로그 오류는 무시한다."""
    try:
        with _log_lock:
            folder = Path(directory) / 'logs'
            folder.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(folder / 'subtitle-preparation.log',
                                          maxBytes=256 * 1024, backupCount=2, encoding='utf-8')
            try:
                handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
                logger = logging.getLogger('my_video_manager.preparation')
                cancelled = kind in ('cancelled', 'interrupted')
                text = f'{kind}: {safe_detail(message)} · {safe_detail(detail)}'.strip(' ·')
                if cancelled:
                    text = ' '.join(text.split())
                record = logger.makeRecord(logger.name, logging.INFO if cancelled else logging.ERROR,
                                           '', 0, text, (), None)
                handler.handle(record)
            finally:
                handler.close()
    except (OSError, ValueError):
        pass


class PreparationHistory:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.path = self.directory / 'subtitle-preparation.json'

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or not all(isinstance(value.get(k), str) for k in ('kind', 'message', 'detail')):
                raise ValueError('준비 기록 형식 오류')
            return value
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            # 손상된 취소 기록을 무시해 큰 다운로드를 시작하지 않는다.
            return dict(kind='storage', message='이전 준비 결과를 읽을 수 없습니다. 다시 시도해 주세요.', detail=safe_detail(error))

    def save(self, kind, detail='', message=''):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.subtitle-preparation-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(dict(kind=kind, message=safe_detail(message), detail=safe_detail(detail)), output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            Path(name).replace(self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def failed(self, kind, message, detail):
        log_failure(self.directory, kind, message, detail)
        try:
            self.save(kind, detail, message)
        except OSError as error:
            # 최초 시작 기록이 있으면 그대로 차단한다. 원래 준비 오류도 보존한다.
            log_failure(self.directory, 'storage', '준비 결과를 저장하지 못했습니다.', error)
