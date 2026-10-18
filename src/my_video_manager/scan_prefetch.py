"""검사에서 새로 읽을 파일의 미디어 정보·지문·썸네일을 작업자 스레드에서 미리 만든다.

DB 기록과 등록 알림은 검사 스레드가 원래 순서대로 한다. 미리 만든 값은 작업 전후와
반영 때의 서명이 같을 때만 쓰고, 다르면 검사 스레드에서 다시 읽는다.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from .library import MediaInfo, _read_media, _signature

# 동시에 처리할 파일 수. 감시 폴더가 HDD일 수 있어 크게 잡지 않는다. 1이면 순차 처리다.
SCAN_WORKERS = 4


@dataclass
class _Prepared:
    signature: tuple[int, int] | None  # 작업 중 파일이 바뀌었으면 None
    info: MediaInfo | None = None
    fingerprint: str | None = None
    error: Exception | None = None
    captured: bool = False
    capture_error: Exception | None = None


class ScanPrefetch:
    def __init__(self, media, thumbnail, *, known=(), minimum=0.0, workers=None):
        self._media, self._thumbnail = media, thumbnail
        self._known, self._minimum = frozenset(known), minimum
        self._futures = {}
        # 지문마다 썸네일 캡처를 맡은 경로. 같은 썸네일 파일에 ffmpeg 두 개가 쓰지 않게 한다.
        self._captures = {}
        self._lock = Lock()
        workers = SCAN_WORKERS if workers is None else workers
        self._executor = ThreadPoolExecutor(workers, thread_name_prefix="scan-prefetch") if workers > 1 else None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        # 예외로 끝나도 남은 작업을 취소하고 실행 중인 ffprobe/ffmpeg가 끝날 때까지 기다린다.
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)

    def submit(self, path) -> None:
        if self._executor is not None and path not in self._futures:
            self._futures[path] = self._executor.submit(self._prepare, path)

    def _claim(self, fingerprint, path) -> bool:
        with self._lock:
            return self._captures.setdefault(fingerprint, path) == path

    def _prepare(self, path) -> _Prepared:
        try:
            signature = _signature(path)
        except (OSError, ValueError):
            return _Prepared(None)
        try:
            info, fingerprint = _read_media(self._media, path)
        except Exception as error:
            prepared = _Prepared(signature, error=error)
        else:
            prepared = _Prepared(signature, info, fingerprint)
            # 이미 등록된 영상과 최소 길이 미만은 등록 때도 캡처하지 않는다.
            if (info is not None and fingerprint not in self._known and info.duration >= self._minimum
                    and self._claim(fingerprint, path)):
                try:
                    self._media.capture(path, self._thumbnail(fingerprint), min(10, info.duration / 10))
                    prepared.captured = True
                except Exception as error:
                    prepared.capture_error = error
        try:
            unchanged = _signature(path) == signature
        except (OSError, ValueError):
            unchanged = False
        if not unchanged:
            prepared.signature = None
        return prepared

    def _prepared(self, path) -> _Prepared | None:
        future = self._futures.get(path)
        return None if future is None else future.result()

    def read(self, path, signature) -> tuple[MediaInfo | None, str | None]:
        prepared = self._prepared(path)
        if prepared is None or prepared.signature != signature:
            return _read_media(self._media, path)
        if prepared.error is not None:
            raise prepared.error
        return prepared.info, prepared.fingerprint

    def capture(self, path, signature, fingerprint, seconds) -> None:
        with self._lock:
            owner = self._captures.setdefault(fingerprint, path)
        prepared = self._prepared(owner)
        if prepared is not None and prepared.signature is not None:
            if prepared.captured:
                return
            if owner == path and prepared.signature == signature and prepared.capture_error is not None:
                raise prepared.capture_error
        # 맡은 작업자가 없거나 그 결과를 쓸 수 없으면 여기서 캡처한다. 이 지문은 이미
        # 누군가 맡았으므로 다른 작업자가 같은 썸네일에 쓰지 않는다.
        self._media.capture(path, self._thumbnail(fingerprint), seconds)
