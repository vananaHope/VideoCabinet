"""코어가 소유하는 영상 썸네일만 제공하는 WebEngine 스킴."""

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler

from .web_library_data import thumbnail_video_id


def register_thumbnail_scheme():
    if QWebEngineUrlScheme.schemeByName(b'mvm-thumb').name():
        return
    scheme = QWebEngineUrlScheme(b'mvm-thumb')
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.CorsEnabled)
    QWebEngineUrlScheme.registerScheme(scheme)


class ThumbnailHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core

    def requestStarted(self, job):
        video_id = thumbnail_video_id(job.requestUrl().toString())
        if video_id is None or job.requestMethod() != b'GET':
            job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
            return
        try:
            video = self.core.video(video_id)
            if video.excluded or not video.thumbnail:
                raise ValueError('없는 썸네일')
            file = QFile(str(video.thumbnail), job)
            if not file.open(QIODevice.OpenModeFlag.ReadOnly):
                raise ValueError('읽을 수 없는 썸네일')
        except (ValueError, OSError):
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        job.reply(b'image/jpeg', file)
