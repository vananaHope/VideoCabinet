"""웹 셸은 QML 문서를 실행하지 않는다. WebEngine의 네이티브 의존성만 수집한다."""
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
