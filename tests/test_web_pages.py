"""README의 페이지 등록 절차와 Qt/웹 등록부의 불일치 실패를 검증한다."""
import json
from pathlib import Path
import subprocess

import pytest
from PySide6.QtCore import QObject
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from test_web_library_page import window_factory
from test_web_library_data import core
from my_video_manager import web_page_registry, web_shell
from my_video_manager.web_contract import Argument, BridgeContract, CONTRACTS, TABS
from my_video_manager.web_page import WebPageController


@pytest.fixture
def example_page(monkeypatch):
    contract = BridgeContract('example', 'ExampleBridge',
        slots={'ready': (), 'find': (Argument('query', str, 'string'),)}, signals={'focusRequested': str})

    class ExampleBridge(QObject):
        focusRequested = contract.signal('focusRequested')

        def __init__(self, page):
            super().__init__(page)
            self.page = page

        @contract.slot('ready')
        def ready(self):
            self.page.frontend_ready()
            return '{}'

        @contract.slot('find')
        def find(self, query):
            return json.dumps({'query': query})

    class ExamplePage(WebPageController):
        tab = 'example'
        default_focus = 'query'

        def __init__(self, host):
            super().__init__(host)
            self.refresh_count = 0
            self.events = []
            self.bridge = ExampleBridge(self)
            self.focus_requested = self.bridge.focusRequested
            host.register_page(self)

        def refresh(self):
            self.refresh_count += 1

        def activated(self):
            self.events.append(('activated', self.core.playback.session is None))

        def deactivated(self):
            self.events.append(('deactivated', self.core.playback.session is None))

    # 실제 페이지 이름과 겹치지 않는 가상 탭을 실행 중에 주입한다.
    monkeypatch.setattr(web_page_registry, 'WEB_PAGES', (*web_page_registry.WEB_PAGES, ExamplePage))
    monkeypatch.setattr(web_shell, 'TABS', (*TABS, ('example', '예시')))
    monkeypatch.setattr(web_shell, 'CONTRACTS', (*CONTRACTS, contract))
    return contract


def test_new_page_registers_its_bridge_refresh_and_focus_without_host_changes(window_factory, example_page):
    window = window_factory('1')
    host = window.web_host
    loaded = QSignalSpy(host.view.loadFinished)
    if host.engine_page.isLoading():
        assert loaded.wait(5000)
    registered = host.channel.registeredObjects()
    assert set(registered) == {contract.name for contract in (*CONTRACTS, example_page)}
    assert json.loads(registered['example'].find('한글')) == {'query': '한글'}
    focus = []
    registered['example'].focusRequested.connect(focus.append)
    registered['shell'].ready()
    registered['shell'].navigate('example')
    QApplication.processEvents()
    assert window.pages.currentWidget() is host
    assert host.controllers['example'].refresh_count == 1
    assert focus == []  # 페이지가 준비되기 전 포커스 요청도 보존한다.
    registered['example'].ready()
    assert focus == ['query']
    window.navigate_web_tab('library')
    window.navigate_web_tab('example')
    assert host.active_tab == 'example'
    assert host.controllers['example'].refresh_count == 2
    assert focus == ['query', 'query']


@pytest.mark.parametrize('change', ['missing', 'unknown', 'duplicate'])
def test_incomplete_or_duplicate_routes_fail_at_start(window_factory, change):
    from my_video_manager.web_shell import WebShellHost
    window = window_factory('0')
    host = WebShellHost(window, initial_tab='library')
    routes = dict(web_page_registry.NATIVE_PAGES)
    if change == 'unknown':
        routes['typo'] = 2
    elif change == 'duplicate':
        routes[web_page_registry.WEB_PAGES[0].tab] = 0
    with pytest.raises(ValueError, match='등록부|중복'):
        for factory in web_page_registry.WEB_PAGES:
            factory(host)
        for tab, index in routes.items():
            host.register_native(tab, index)
        if change == 'missing':
            host.routes.pop(next(iter(host.routes)))
        host.start()


def test_unregistered_bridge_contract_fails_at_start(window_factory, monkeypatch):
    window = window_factory('1')
    monkeypatch.setattr(web_shell, 'CONTRACTS', (*CONTRACTS, BridgeContract('example', 'ExampleBridge')))
    with pytest.raises(ValueError, match='브리지 계약과 채널 등록부'):
        window.web_host.start()


def test_virtual_page_lifecycle_and_playback_return(window_factory, example_page, core, monkeypatch):
    from test_library_return_ui import Player
    window = window_factory('1')
    window.player_factory = Player
    host = window.web_host
    page = host.controllers['example']
    library = window.library_page
    monkeypatch.setattr(library, 'activated', lambda: page.events.append(('library activated', True)))
    monkeypatch.setattr(library, 'deactivated', lambda: page.events.append(('library deactivated', True)))
    window.navigate_web_tab('example')
    assert page.is_active() and not page.isVisible()
    window.navigate_web_tab('example')  # 같은 활성 페이지로 이동해도 수명 이벤트는 중복하지 않는다.
    window.navigate_web_tab('library')
    window.navigate_web_tab('example')
    assert page.events == [
        ('library deactivated', True), ('activated', True),
        ('deactivated', True), ('library activated', True),
        ('library deactivated', True), ('activated', True),
    ]
    page.events.clear()
    host.hide()
    assert not page.is_active()
    host.show()
    window.hide()
    window.show()
    assert page.events == [('deactivated', True), ('activated', True)] * 2
    page.events.clear()
    window.play_video(core.videos()[0].id)
    assert window.pages.currentWidget() is window.playback_page
    assert not page.is_active()
    # 재생 중 다른 영상으로 이어져도 최초 복귀 탭을 보존한다.
    window.play_video(core.videos()[1].id)
    window.back_to_list()
    assert window.pages.currentWidget() is host and host.active_tab == 'example'
    assert page.is_active()
    assert page.events == [('deactivated', False), ('activated', True)]
    assert core.playback.session is None  # 복귀 activated는 시청 종료 뒤 호출한다.


@pytest.mark.parametrize('native_tab', web_page_registry.NATIVE_PAGES)
def test_virtual_page_deactivates_for_qt_and_activates_on_return(window_factory, example_page, native_tab):
    window = window_factory('1')
    window.navigate_web_tab('example')
    page = window.web_host.controllers['example']
    window.navigate_web_tab(native_tab)
    assert not page.is_active()
    window.return_to_web()
    assert window.web_host.active_tab == 'example'
    assert page.events == [('activated', True), ('deactivated', True), ('activated', True)]


@pytest.mark.parametrize('shell_first', [True, False])
def test_frontend_loaded_fires_once_per_load_with_multiple_pages(window_factory, example_page, shell_first):
    host = window_factory('1').web_host
    loaded = QSignalSpy(host.view.loadFinished)
    if host.engine_page.isLoading():
        assert loaded.wait(5000)
    host.frontend_loading()
    notifications = QSignalSpy(host.frontend_loaded)
    if shell_first:
        host.bridge.ready()
    host.controllers['example'].bridge.ready()
    assert notifications.count() == 0  # 비활성 페이지의 준비는 활성 라이브러리 준비를 대신하지 않는다.
    host.controllers['library'].bridge.ready()
    if not shell_first:
        host.bridge.ready()
    assert notifications.count() == 1
    for controller in host.controllers.values():
        controller.frontend_ready()
    host.bridge.ready()
    host.navigate('example')
    host.controllers['example'].bridge.ready()
    assert notifications.count() == 1
    host.frontend_loading()
    host.bridge.ready()
    host.controllers['example'].bridge.ready()
    assert notifications.count() == 2


def test_frontend_registry_matches_all_tabs_and_qt_fallbacks():
    root = Path(__file__).resolve().parents[1]
    script = """
      const ts = require('typescript'), fs = require('fs');
      const code = ts.transpileModule(fs.readFileSync('src/pages/index.ts', 'utf8'),
        {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
      const module = {exports:{}};
      new Function('require','exports',code)(() => ({default: () => null}), module.exports);
      console.log(JSON.stringify(Object.fromEntries(Object.entries(module.exports.pages).map(([k,v]) => [k,v !== null]))));
    """
    result = subprocess.run(['node', '-e', script], cwd=root / 'frontend', capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    routes = json.loads(result.stdout)
    assert set(routes) == {tab for tab, _ in TABS}
    assert {tab for tab, is_web in routes.items() if is_web} == {page.tab for page in web_page_registry.WEB_PAGES}
    assert {tab for tab, is_web in routes.items() if not is_web} == set(web_page_registry.NATIVE_PAGES)


def test_connection_returns_only_public_page_wrappers():
    root = Path(__file__).resolve().parents[1]
    script = """
      const ts = require('typescript'), fs = require('fs'), assert = require('assert');
      function load(path, imports) {
        const module = {exports:{}};
        const code = ts.transpileModule(fs.readFileSync(path, 'utf8'),
          {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
        new Function('require','exports',code)(() => imports, module.exports);
        return module.exports;
      }
      const contracts = JSON.parse(fs.readFileSync(0,'utf8'));
      const raw = {};
      for (const contract of contracts) {
        raw[contract.name] = {deleteLater() {}, objectName: 'private'};
        for (const slot of contract.slots) raw[contract.name][slot] = function(...args) {assert.equal(this, raw[contract.name]); args.at(-1)('{}')};
        for (const signal of contract.signals) raw[contract.name][signal] = {connect() {}, disconnect() {}, emit() {}};
      }
      let connections = 0;
      global.window = {qt:{webChannelTransport:{}}, QWebChannel: function(transport, connected) {connections++; connected({objects:raw})}};
      const api = load('src/bridge.ts', load('src/bridge-types.ts'));
      (async () => {
        const a = api.connectBridge(), b = api.connectBridge();
        assert.equal(a,b); const pages = await a; assert.equal(connections,1); assert(Object.isFrozen(pages));
        assert.deepEqual(Object.keys(pages).sort(), Object.keys(raw).sort());
        for (const contract of contracts) {
          const page = pages[contract.name]; assert.notEqual(page,raw[contract.name]);
          assert.equal(page.deleteLater,undefined); assert.equal(page.objectName,undefined); assert(Object.isFrozen(page));
          for (const name of contract.signals) assert.equal(page[name].emit,undefined);
        }
      })().catch(error => {console.error(error); process.exitCode=1});
    """
    result = subprocess.run(['node', '-e', script], cwd=root / 'frontend', capture_output=True, text=True,
        input=json.dumps([{'name': c.name, 'slots': list(c.slots), 'signals': list(c.signals)} for c in CONTRACTS]))
    assert result.returncode == 0, result.stderr
