"""Linux 클라우드 전용 우회: `check_web_*.py --offscreen`을 Linux offscreen에서 돌려 스크린샷만 얻는다.

    python scripts/linux_offscreen_check.py scripts/check_web_queue.py --offscreen --output .local/shots/queue
    MVM_SHOT_MAX_DIR=.local/shots/queue-max MVM_SHOT_FONT_LOG=.local/shots/fonts.log \
        python scripts/linux_offscreen_check.py scripts/check_web_queue.py --offscreen --output .local/shots/queue

**초점·키 단언은 믿을 수 없다.** 화면 검증의 기준은 Windows다(실창은 데스크톱 잠금 안에서). 이 보조는 제품 코드와
`tests/conftest.py`를 건드리지 않고, 스크립트를 띄우기 전에 아래 세 가지만 바꾼다.

1. Linux offscreen에서는 앱 전역 Python 이벤트 필터로 QWebEngine 안쪽 QQuick 객체가 넘어오면 PySide6가 세그폴트한다
   (conftest가 웹 셸 테스트를 건너뛰는 이유). `QApplication.installEventFilter`를 위젯·창 단위 필터로 바꿔 건다.
   그래서 전역 필터가 받던 키(긴급 탈출·Ctrl+숫자·F1)와 초점 전달은 실제 앱과 다르게 움직이고, 그에 기대는 단언은
   실패할 수 있다. 실패 전까지 저장된 스크린샷은 정상이다.
2. 스크립트가 offscreen에서 읽는 `%WINDIR%\\Fonts\\malgun.ttf`가 없으므로, 임시 폴더에 번들 Pretendard를 그 이름으로 둔다.
   대체 글꼴(맑은 고딕)은 등록되지 않는다. 화면 글자는 웹 번들의 Pretendard로 그려진다.
3. root로 실행하는 컨테이너에서 Chromium이 뜨도록 sandbox를 끈다.

환경 변수(선택):
- `MVM_SHOT_MAX_DIR`: 스크립트가 1100px 폭 PNG를 저장할 때마다 같은 상태에서 창을 1920×1017로 키워 한 장 더 저장한다.
  창 크기를 바꾸므로 뒤따르는 단언이 실패할 수 있다.
- `MVM_SHOT_FONT_LOG`: 저장하는 화면마다 웹 문서의 글꼴 이름과 번들 글꼴 로드 여부를 한 줄씩 적는다.
  대체 글꼴로 찍힌 화면을 가려내는 데 쓴다.
"""
import faulthandler
import os
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

if sys.platform == 'win32':
    sys.exit('Windows에서는 check_web_*.py를 직접 실행하세요. 이 보조는 Linux offscreen 전용입니다.')
if len(sys.argv) < 2:
    sys.exit(__doc__)

faulthandler.enable()
ROOT = Path(__file__).resolve().parents[1]
fonts = Path(tempfile.mkdtemp(prefix='mvm-windir-')) / 'Fonts'
fonts.mkdir()
bundled = ROOT / 'src/my_video_manager/web/qt-fonts'
for source, name in (('Pretendard-Regular.ttf', 'malgun.ttf'), ('Pretendard-SemiBold.ttf', 'malgunbd.ttf')):
    if (bundled / source).exists():
        shutil.copy(bundled / source, fonts / name)
os.environ.setdefault('WINDIR', str(fonts.parent))
os.environ['QTWEBENGINE_DISABLE_SANDBOX'] = '1'

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_filters = []
_seen = {}
_install_filter = QObject.installEventFilter
_remove_filter = QObject.removeEventFilter
_timer = []


def _spread():
    """전역 필터를 지금 있는 모든 위젯과 최상위 창에 건다. 새로 생긴 위젯은 타이머가 따라 건다."""
    app = QApplication.instance()
    if app is None:
        return
    targets = list(app.allWidgets()) + [w for w in QGuiApplication.topLevelWindows() if type(w).__name__ in ('QWindow', 'QWidgetWindow')]
    for event_filter in list(_filters):
        seen = _seen.setdefault(id(event_filter), set())
        for target in targets:
            if id(target) not in seen:
                seen.add(id(target))
                try:
                    _install_filter(target, event_filter)
                except RuntimeError:
                    pass


def _install(self, event_filter):
    if not isinstance(self, QCoreApplication):
        return _install_filter(self, event_filter)
    if event_filter not in _filters:
        _filters.append(event_filter)
    _spread()
    if not _timer:
        _timer.append(QTimer())
        _timer[0].timeout.connect(_spread)
        _timer[0].start(30)


def _remove(self, event_filter):
    if not isinstance(self, QCoreApplication):
        return _remove_filter(self, event_filter)
    if event_filter in _filters:
        _filters.remove(event_filter)
        _seen.pop(id(event_filter), None)
        for target in QApplication.instance().allWidgets():
            try:
                _remove_filter(target, event_filter)
            except RuntimeError:
                pass


QObject.installEventFilter = _install
QObject.removeEventFilter = _remove

MAX_DIR = os.environ.get('MVM_SHOT_MAX_DIR')
FONT_LOG = os.environ.get('MVM_SHOT_FONT_LOG')
FONT_STATE = ("JSON.stringify({family: getComputedStyle(document.body).fontFamily,"
              " loaded: [400, 500, 600].map(weight => document.fonts.check(weight + ' 14px Pretendard', '가A1')),"
              " status: document.fonts.status})")
if MAX_DIR or FONT_LOG:
    _busy = [False]
    _save_pixmap = QPixmap.save

    def _evaluate(window, code):
        try:
            page = window.web_host.view.page()
        except Exception:
            return None
        result, loop = [], QEventLoop()
        page.runJavaScript(code, lambda value: (result.append(value), loop.quit()))
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        return result[0] if result else None

    def _hook(save):
        def saved(self, path, *args, **kwargs):
            ok = save(self, path, *args, **kwargs)
            name = os.path.basename(str(path))
            windows = [w for w in QApplication.topLevelWidgets() if type(w).__name__ == 'MainWindow' and w.isVisible()]
            if _busy[0] or not name.endswith('.png') or self.width() != 1100 or not windows:
                return ok
            window = windows[0]
            _busy[0] = True
            try:
                if FONT_LOG:
                    Path(FONT_LOG).parent.mkdir(parents=True, exist_ok=True)
                    with open(FONT_LOG, 'a', encoding='utf-8') as log:
                        log.write(f'{name}\t{_evaluate(window, FONT_STATE)}\n')
                if MAX_DIR:
                    os.makedirs(MAX_DIR, exist_ok=True)
                    size = window.size()
                    window.resize(1920, 1017)
                    QTest.qWait(700)
                    _save_pixmap(window.grab(), os.path.join(MAX_DIR, name))
                    window.resize(size)
                    QTest.qWait(400)
            finally:
                _busy[0] = False
            return ok
        return saved

    QPixmap.save = _hook(QPixmap.save)
    QImage.save = _hook(QImage.save)

script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
runpy.run_path(script, run_name='__main__')
