"""웹 탭과 Qt 전환, 생성된 공개 브리지의 실제 Qt 시그니처 계약."""
import json

from PySide6.QtCore import QMetaMethod
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from test_web_library_page import window_factory
from test_web_library_data import core
from my_video_manager.web_contract import SIGNALS, SLOTS, TABS


def test_tab_routes_keep_one_web_view_and_native_numbering(window_factory):
    from PySide6.QtWebEngineWidgets import QWebEngineView
    window = window_factory('1')
    page = window.library_page
    for index, (tab, _) in enumerate(TABS):
        window.navigate_web_tab(tab)
        target = page if index in (0, 4) else window.navigation_pages[index if index < 4 else index - 1]
        assert window.pages.currentWidget() is target
        assert json.loads(page.bridge.shellSnapshot()) == {'tab': tab}
        assert not window.sidebar.isVisible()
        assert len(window.findChildren(QWebEngineView)) == 1
    window.return_to_web()
    assert page.active_tab == 'statistics'
    assert window.pages.currentWidget() is page


def test_global_web_keys_and_native_escape_return(window_factory):
    window = window_factory('1')
    window.activateWindow()
    QTest.qWait(30)
    for index, (tab, _) in enumerate(TABS):
        target = window.focusWidget() or window
        QTest.keyClick(target, Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
        assert window.library_page.active_tab == tab
    QTest.keyClick(window.focusWidget(), Qt.Key.Key_Escape)
    assert window.pages.currentWidget() is window.library_page
    assert window.library_page.active_tab == 'statistics'


def test_qt_switch_keeps_six_original_destinations(window_factory):
    window = window_factory('0')
    assert len(window.navigation_pages) == 6
    for index in range(6):
        window.navigate(index)
        assert window.pages.currentWidget() is window.navigation_pages[index]
        assert window.sidebar.isVisible()


def test_actual_qt_public_slots_and_signals_match_generator_contract(window_factory):
    bridge = window_factory('1').library_page.bridge
    meta = bridge.metaObject()
    methods = {bytes(meta.method(i).name()).decode(): meta.method(i)
               for i in range(meta.methodOffset(), meta.methodCount())}
    assert set(methods) == set(SLOTS) | set(SIGNALS)
    names = {str: 'QString', int: 'int'}
    for name, arguments in SLOTS.items():
        method = methods[name]
        assert method.methodType() == QMetaMethod.MethodType.Slot
        assert method.typeName() == 'QString'
        assert [bytes(t).decode() for t in method.parameterTypes()] == [names[t] for _, t in arguments]
    for name, kind in SIGNALS.items():
        assert methods[name].methodType() == QMetaMethod.MethodType.Signal
        assert [bytes(t).decode() for t in methods[name].parameterTypes()] == [names[kind]]


def test_navigation_rejects_unknown_names_without_transition(window_factory):
    window = window_factory('1')
    assert 'error' in json.loads(window.library_page.bridge.navigate('deleteLater'))
    QApplication.processEvents()
    assert window.pages.currentWidget() is window.library_page


def test_native_search_playback_returns_to_same_tab_and_state(window_factory, core):
    from test_library_return_ui import Player
    window = window_factory('1')
    window.player_factory = Player
    window.navigate_web_tab('search')
    page = window.navigation_pages[2]
    page.query.setText('Python')
    window.play_video(core.videos()[0].id)
    assert window.pages.currentWidget() is window.playback_page
    window.back_to_list()
    assert window.pages.currentWidget() is page
    assert page.query.text() == 'Python'
    assert window.library_page.active_tab == 'search'
    window.navigate_web_tab('library')
    library = window.library_page
    library.bridge.filter('Python', 0)
    selected = library.visible_ids[-1]
    library.bridge.select(selected)
    window.play(selected)
    window.back_to_list()
    assert library.query == 'Python' and library.selected_video_id() == selected
    assert library.active_tab == 'library'


def test_public_javascript_wrapper_hides_qobject_methods_and_signal_emit():
    import shutil
    import subprocess
    from pathlib import Path
    import pytest
    root = Path(__file__).resolve().parents[1]
    if not shutil.which('node') or not (root / 'frontend/node_modules/typescript').exists():
        pytest.skip('npm ci와 Node가 필요합니다')
    script = """
      const ts = require('typescript'), fs = require('fs'), assert = require('assert');
      const source = fs.readFileSync('src/bridge-types.ts', 'utf8');
      const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
      const module = {exports: {}}; new Function('exports', 'module', code)(module.exports, module);
      const contract = JSON.parse(fs.readFileSync(0, 'utf8'));
      const raw = {deleteLater() {throw Error('must not reach QObject')}, objectName: 'internal'};
      for (const name of contract.slots) raw[name] = function(...args) {assert.equal(this, raw); args.at(-1)('{}')};
      for (const name of contract.signals) raw[name] = {connect() {}, disconnect() {}, emit() {}};
      const api = module.exports.publicBridge(raw);
      assert.deepEqual(Object.keys(api).sort(), [...contract.slots, ...contract.signals].sort());
      assert.equal(api.deleteLater, undefined); assert.equal(api.objectName, undefined);
      assert(Object.isFrozen(api));
      for (const name of contract.signals) { assert.equal(api[name].emit, undefined); assert(Object.isFrozen(api[name])); }
      let received; api.snapshot(value => received = value); assert.equal(received, '{}');
    """
    result = subprocess.run(['node', '-e', script], input=json.dumps({'slots': list(SLOTS), 'signals': list(SIGNALS)}),
                            cwd=root / 'frontend', text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
