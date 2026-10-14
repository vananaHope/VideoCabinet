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
from my_video_manager import web_pages, web_shell
from my_video_manager.web_contract import Argument, BridgeContract, CONTRACTS, TABS
from my_video_manager.web_page import WebPageController


def test_new_page_registers_its_bridge_refresh_and_focus_without_host_changes(window_factory, monkeypatch):
    contract = BridgeContract('search', 'SearchBridge',
        slots={'ready': (), 'find': (Argument('query', str, 'string'),)}, signals={'focusRequested': str})

    class SearchBridge(QObject):
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

    class SearchPage(WebPageController):
        tab = 'search'
        default_focus = 'query'

        def __init__(self, host):
            super().__init__(host)
            self.refresh_count = 0
            self.bridge = SearchBridge(self)
            self.focus_requested = self.bridge.focusRequested
            host.register_page(self)

        def refresh(self):
            self.refresh_count += 1

    # 새 모듈의 컨트롤러 등록 한 줄 + 이전 Qt 경로 제거만으로 실제 앱에 연결한다.
    monkeypatch.setattr(web_pages, 'WEB_PAGES', (*web_pages.WEB_PAGES, SearchPage))
    monkeypatch.setattr(web_pages, 'NATIVE_PAGES', {k: v for k, v in web_pages.NATIVE_PAGES.items() if k != 'search'})
    monkeypatch.setattr(web_shell, 'CONTRACTS', (*CONTRACTS, contract))
    window = window_factory('1')
    host = window.web_host
    loaded = QSignalSpy(host.view.loadFinished)
    if host.engine_page.isLoading():
        assert loaded.wait(5000)
    registered = host.channel.registeredObjects()
    assert set(registered) == {'shell', 'library', 'search'}
    assert json.loads(registered['search'].find('한글')) == {'query': '한글'}
    focus = []
    registered['search'].focusRequested.connect(focus.append)
    registered['shell'].ready()
    registered['shell'].navigate('search')
    QApplication.processEvents()
    assert window.pages.currentWidget() is host
    assert host.controllers['search'].refresh_count == 1
    assert focus == []  # 페이지가 준비되기 전 포커스 요청도 보존한다.
    registered['search'].ready()
    assert focus == ['query']
    window.navigate_web_tab('folders')
    window.return_to_web()
    assert host.active_tab == 'search'
    assert host.controllers['search'].refresh_count == 2
    assert focus == ['query', 'query']


@pytest.mark.parametrize('change', ['missing', 'unknown', 'duplicate'])
def test_incomplete_or_duplicate_routes_fail_at_start(window_factory, change):
    from my_video_manager.web_shell import WebShellHost
    window = window_factory('0')
    host = WebShellHost(window, initial_tab='library')
    routes = dict(web_pages.NATIVE_PAGES)
    if change == 'missing':
        routes.pop('search')
    elif change == 'unknown':
        routes['typo'] = 2
    else:
        routes['library'] = 0
    with pytest.raises(ValueError, match='등록부|중복'):
        for factory in web_pages.WEB_PAGES:
            factory(host)
        for tab, index in routes.items():
            host.register_native(tab, index)
        host.start()


def test_unregistered_bridge_contract_fails_at_start(window_factory, monkeypatch):
    window = window_factory('1')
    monkeypatch.setattr(web_shell, 'CONTRACTS', (*CONTRACTS, BridgeContract('search', 'SearchBridge')))
    with pytest.raises(ValueError, match='브리지 계약과 채널 등록부'):
        window.web_host.start()


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
    assert {tab for tab, is_web in routes.items() if is_web} == {page.tab for page in web_pages.WEB_PAGES}
    assert {tab for tab, is_web in routes.items() if not is_web} == set(web_pages.NATIVE_PAGES)


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
