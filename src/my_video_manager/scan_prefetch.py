"""검사에서 새로 읽을 파일의 미디어 정보·지문·썸네일을 작업자 스레드에서 미리 만든다.

DB 기록과 등록 알림은 검사 스레드가 원래 순서대로 한다. 미리 만든 값은 같은 경로를
같은 서명·같은 지문으로 반영할 때만 쓰고, 아니면 검사 스레드에서 다시 읽거나 캡처한다.
작업자는 썸네일을 임시 파일에 캡처하고, 반영할 때 최종 이름으로 옮긴다. 쓰지 않은
임시 파일은 검사가 끝날 때 지운다.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .library import MediaInfo, _read_media, _signature

# 동시에 처리할 파일 수. 감시 폴더가 HDD일 수 있어 크게 잡지 않는다. 1이면 순차 처리다.
SCAN_WORKERS = 4
# 썸네일 폴더 안 미리 캡처 임시 파일. DB가 가리키는 썸네일 이름과 겹치지 않는다.
TEMPORARY_PREFIX = ".prefetch-"


@dataclass
class _Prepared:
    signature: tuple[int, int] | None  # 서명을 읽지 못했으면 None
    info: MediaInfo | None = None
    fingerprint: str | None = None
    error: Exception | None = None
    capture: Path | None = None  # 캡처에 성공한 임시 파일
    capture_error: Exception | None = None


class ScanPrefetch:
    def __init__(self, media, thumbnail, *, directory=None, known=(), minimum=0.0, workers=None):
        self._media, self._thumbnail, self._directory = media, thumbnail, directory
        self._known, self._minimum = frozenset(known), minimum
        self._futures = {}
        # 지문마다 미리 캡처를 맡은 경로. 같은 내용의 복사본을 여러 번 캡처하지 않는다.
        self._claims = {}
        self._temporaries = []
        self._lock = Lock()
        workers = SCAN_WORKERS if workers is None else workers
        self._executor = (ThreadPoolExecutor(workers, thread_name_prefix="scan-prefetch")
                          if workers > 1 and directory is not None else None)

    def __enter__(self):
        if self._directory is not None:
            # 앱이 검사 중 비정상 종료해 남은 임시 파일을 치운다. 검사는 한 번에 하나다.
            self._remove(self._directory.glob(TEMPORARY_PREFIX + "*"))
        return self

    def __exit__(self, *exc_info):
        # 예외로 끝나도 남은 작업을 취소하고 실행 중인 ffprobe/ffmpeg가 끝날 때까지 기다린다.
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
        # 반영한 캡처는 이미 최종 이름으로 옮겼다. 남은 것은 쓰지 않은 결과다.
        self._remove(self._temporaries)

    @staticmethod
    def _remove(paths) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # 다음 검사 시작 때 다시 치운다.

    def submit(self, path) -> None:
        if self._executor is not None and path not in self._futures:
            self._futures[path] = self._executor.submit(self._prepare, path)

    def _claim(self, fingerprint, path) -> Path | None:
        with self._lock:
            if self._claims.setdefault(fingerprint, path) != path:
                return None
            temporary = self._directory / f"{TEMPORARY_PREFIX}{uuid4().hex}.jpg"
            self._temporaries.append(temporary)
            return temporary

    def _prepare(self, path) -> _Prepared:
        try:
            signature = _signature(path)
        except (OSError, ValueError):
            return _Prepared(None)
        try:
            info, fingerprint = _read_media(self._media, path)
        except Exception as error:
            return self._checked(path, _Prepared(signature, error=error))
        prepared = _Prepared(signature, info, fingerprint)
        # 이미 등록된 영상과 최소 길이 미만은 등록 때도 캡처하지 않는다.
        if info is not None and fingerprint not in self._known and info.duration >= self._minimum:
            temporary = self._claim(fingerprint, path)
            if temporary is not None:
                try:
                    self._media.capture(path, temporary, min(10, info.duration / 10))
                    prepared.capture = temporary
                except Exception as error:
                    prepared.capture_error = error
        return self._checked(path, prepared)

    @staticmethod
    def _checked(path, prepared) -> _Prepared:
        # 작업 중 변경된 결과는 나중에 원래 서명으로 돌아와도 재사용하지 않는다.
        try:
            if _signature(path) == prepared.signature:
                return prepared
        except (OSError, ValueError):
            pass
        return _Prepared(None)

    def _prepared(self, path, signature) -> _Prepared | None:
        future = self._futures.get(path)
        if future is None:
            return None
        prepared = future.result()
        return prepared if prepared.signature == signature else None

    def read(self, path, signature) -> tuple[MediaInfo | None, str | None]:
        prepared = self._prepared(path, signature)
        if prepared is None:
            return _read_media(self._media, path)
        if prepared.error is not None:
            raise prepared.error
        return prepared.info, prepared.fingerprint

    def capture(self, path, signature, fingerprint, seconds) -> None:
        destination = self._thumbnail(fingerprint)
        prepared = self._prepared(path, signature)
        # 다른 경로(복사본)의 캡처는 쓰지 않는다. 이 경로의 실패를 가리면 순차와 결과가 달라진다.
        if prepared is not None and prepared.fingerprint == fingerprint:
            if prepared.capture_error is not None:
                raise prepared.capture_error
            if prepared.capture is not None:
                try:
                    os.replace(prepared.capture, destination)
                    return
                except OSError:
                    # 교체가 막혀도 직접 덮어쓰기는 가능할 수 있다. 순차와 같은 경로로 재시도한다.
                    pass
        self._media.capture(path, destination, seconds)
