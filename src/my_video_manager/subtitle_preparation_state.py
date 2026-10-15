"""준비의 마지막 결과를 데이터 폴더에 원자적으로 보존한다."""
import json
import logging
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .app_logging import safe_detail, file_log_handler


_log_lock = Lock()


def log_failure(directory, kind, message, detail):
    """실패는 ERROR, 사용자 취소·중단은 INFO로 기록한다. 로그 오류는 무시한다."""
    try:
        with _log_lock:
            handler = file_log_handler(Path(directory) / 'logs/subtitle-preparation.log')
            try:
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
        temporary = self.directory / f'.subtitle-preparation-{uuid4().hex}.tmp'
        # 권한 오류나 이름 충돌을 재시도하지 않고 한 번만 생성한다.
        output = temporary.open('x', encoding='utf-8')
        try:
            with output:
                json.dump(dict(kind=kind, message=safe_detail(message), detail=safe_detail(detail)), output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def failed(self, kind, message, detail):
        log_failure(self.directory, kind, message, detail)
        try:
            self.save(kind, detail, message)
        except OSError as error:
            # 최초 시작 기록이 있으면 그대로 차단한다. 원래 준비 오류도 보존한다.
            log_failure(self.directory, 'storage', '준비 결과를 저장하지 못했습니다.', error)
