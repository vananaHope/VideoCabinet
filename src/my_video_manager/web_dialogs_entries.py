"""업무 대화상자의 Python 진입점. 화면은 단일 웹 셸이 소유한다."""
from .web_dialogs_host import web_dialogs


class _Entry:
    def __init__(self, parent, kind, **context):
        self.parent = parent
        self.kind, self.context = kind, context

    def exec(self):
        return web_dialogs(self.parent).run(self.kind, **self.context)


class TagEditor(_Entry):
    def __init__(self, core, *, video_id=None, highlight_id=None, parent=None):
        super().__init__(parent, 'tags', video_id=video_id, highlight_id=highlight_id)


class TagManager(_Entry):
    def __init__(self, core, parent):
        super().__init__(parent, 'tag-manager')


class SeriesEditor(_Entry):
    def __init__(self, core, parent=None):
        super().__init__(parent, 'series')


class HighlightEditor(_Entry):
    def __init__(self, core, highlight, duration, parent):
        self.core, self.highlight = core, highlight
        super().__init__(parent, 'highlight', highlight=highlight, duration=duration)


class HighlightList(_Entry):
    def __init__(self, core, video_id, duration, parent):
        super().__init__(parent, 'highlights', video_id=video_id, duration=duration)


class RandomScopeChooser(_Entry):
    def __init__(self, core, parent):
        super().__init__(parent, 'random-scope')


class OnScreenRegionDialog(_Entry):
    """화면 자막 영역을 끈 뒤 읽을 언어를 확인한다. 재생 화면에서 연다.

    region_id가 있으면 이미 정한 그 영역을 region 자리로 고친다(읽을 언어 기본값은 지금 언어).
    """

    def __init__(self, core, video_id, region, parent, *, region_id=None):
        super().__init__(parent, 'onscreen-region', video_id=video_id, region=region, region_id=region_id)


class OnScreenRegionDeleteDialog(_Entry):
    """이미 정한 화면 자막 영역 하나를 지울지 묻는다. 재생 화면에서 연다."""

    def __init__(self, core, video_id, region_id, parent):
        super().__init__(parent, 'onscreen-region-delete', video_id=video_id, region_id=region_id)


class ReviewDialog(_Entry):
    def __init__(self, core, video_id, jump, changed, parent=None):
        super().__init__(parent, 'review', video_id=video_id, jump=jump, changed=changed)
