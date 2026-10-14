"""스킴은 URL 파일 경로가 아니라 코어 공개 영상 ID로만 썸네일을 연다."""
from PySide6.QtCore import QObject, QUrl
from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob

from test_web_library_data import core
from my_video_manager.web_thumbnail import ThumbnailHandler


class Job(QObject):
    def __init__(self, url):
        super().__init__()
        self.url, self.failed, self.content = QUrl(url), None, None

    def requestUrl(self):
        return self.url

    def requestMethod(self):
        return b'GET'

    def fail(self, reason):
        self.failed = reason

    def reply(self, mime, file):
        self.content = mime, bytes(file.readAll())


def test_known_thumbnail_is_read_and_excluded_or_unknown_id_is_denied(core):
    handler = ThumbnailHandler(core)
    video = core.videos()[0]
    job = Job(f'mvm-thumb://video/{video.id}')
    handler.requestStarted(job)
    assert job.content == (b'image/jpeg', b'thumbnail')
    core.exclude_video(video.id)
    excluded = Job(f'mvm-thumb://video/{video.id}')
    handler.requestStarted(excluded)
    assert excluded.failed == QWebEngineUrlRequestJob.Error.UrlNotFound
    unknown = Job('mvm-thumb://video/999999')
    handler.requestStarted(unknown)
    assert unknown.failed == QWebEngineUrlRequestJob.Error.UrlNotFound


def test_arbitrary_local_path_is_never_read(core):
    handler = ThumbnailHandler(core)
    for url in ('file:///C:/secret', 'mvm-thumb://video/1/secret', 'mvm-thumb://video/1?file=C:/secret'):
        job = Job(url)
        handler.requestStarted(job)
        assert job.failed == QWebEngineUrlRequestJob.Error.RequestDenied
        assert job.content is None
