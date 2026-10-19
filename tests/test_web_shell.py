"""웹 탭과 Qt 전환, 생성된 공개 브리지의 실제 Qt 시그니처 계약."""
import json
import pytest

from PySide6.QtCore import QMetaMethod
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from test_web_library_page import window_factory
from test_web_library_data import core
from my_video_manager.web_contract import CONTRACTS, TABS
from qt_wait import wait_for
from wait_helpers import UI_READY_TIMEOUT


def wait_frontend_ready(host, tab):
    wait_for(lambda: host._frontend_ready and tab in host._ready_pages)


@pytest.mark.parametrize('tab', ['library', 'search', 'settings'])
def test_tray_playback_restore_requests_library_focus(window_factory, core, monkeypatch, tab):
    from PySide6.QtWidgets import QSystemTrayIcon
    from test_library_return_ui import Player

    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    video = core.videos()[0]
    window = window_factory()
    window.player_factory = Player
    host = window.web_host
    wait_frontend_ready(host, 'library')
    window.navigate_web_tab(tab)
    wait_frontend_ready(host, tab)
    requests = []
    window.library_page.bridge.libraryFocusRequested.connect(
        lambda target: requests.append((host.active_tab, target)))
    window.play_video(video.id, start=0)
    window.close()
    assert host._pending_focus == 'grid'
    assert requests == []
    window.tray.open()
    assert requests == [('library', 'grid')]
    assert host._pending_focus is None


def test_tray_restore_after_recommendation_playback_requests_recommend_focus(window_factory, core, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    from test_library_return_ui import Player

    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    video = core.videos()[0]
    core.playback.start(video.id, 0)
    core.playback.report(40)
    core.playback.end()
    window = window_factory()
    window.player_factory = Player
    host = window.web_host
    page = host.controllers['recommend']
    wait_frontend_ready(host, 'library')
    window.navigate_web_tab('recommend')
    wait_frontend_ready(host, 'recommend')
    requests = []
    for name in ('library', 'recommend'):
        host.controllers[name].focus_requested.connect(lambda target, name=name: requests.append((name, host.active_tab, target)))
    page.bridge.perform_play(video.id)
    window.player.positions.append((40, False))
    window.close()
    assert host._pending_focus == 'recommendations'
    window.tray.open()
    assert requests == [('recommend', 'recommend', 'recommendations')]
    assert host._pending_focus is None


def test_tray_playback_before_frontend_ready_replaces_search_focus(window_factory, core, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    from test_library_return_ui import Player

    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    window = window_factory()
    window.player_factory = Player
    host = window.web_host
    host.frontend_loading()
    window.navigate_web_tab('search')
    assert host._pending_focus == 'search-content'
    window.play(core.videos()[0].id)
    window.close()
    assert host.active_tab == 'library'
    assert host._pending_focus == 'grid'
    window.tray.open()
    assert host._pending_focus == 'grid'


@pytest.mark.parametrize('tab', ['library', 'queue'])
def test_tray_show_queue_refreshes_hidden_changes_immediately(window_factory, core, monkeypatch, tab):
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    window = window_factory()
    window.subtitles.timer.stop()
    window.navigate_web_tab(tab)
    queue = window.web_host.controllers['queue']
    changes = []
    queue.bridge.queueChanged.connect(lambda value: changes.append(json.loads(value)))
    window.close()
    video = core.videos()[0]
    core.request_subtitles(video.id)
    assert changes == []
    window.tray.show_queue()
    # 이벤트 루프나 500ms 타이머를 기다리지 않고 새 행을 전달한다.
    assert len(changes) == 1
    assert changes[0]['order'] == [video.id]
    assert [row['videoId'] for row in changes[0]['rows']] == [video.id]


@pytest.mark.parametrize('tab', [tab for tab, _ in TABS])
@pytest.mark.parametrize('destination', ['restore', 'queue', 'playback', 'fullscreen'])
def test_tray_restore_activates_only_destination(window_factory, core, monkeypatch, tab, destination):
    from PySide6.QtWidgets import QSystemTrayIcon
    from test_library_return_ui import Player

    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    window = window_factory()
    window.player_factory = Player
    host = window.web_host
    assert TABS and set(host.controllers) == {name for name, _ in TABS}
    window.navigate_web_tab(tab)
    events = []
    for name, controller in host.controllers.items():
        for method in ('activated', 'deactivated'):
            original = getattr(controller, method)

            def record(name=name, method=method, original=original):
                events.append((name, method))
                original()

            monkeypatch.setattr(controller, method, record)
    transitions = []
    host.bridge.shellChanged.connect(lambda state: transitions.append(json.loads(state)['tab']))
    controllers = dict(host.controllers)
    playing = destination in ('playback', 'fullscreen')
    if playing:
        window.play(core.videos()[0].id)
        if destination == 'fullscreen':
            window.set_playback_fullscreen(True)
        events.clear()
    window.close()
    assert not window.isVisible()
    assert core.playback.session is None
    assert events == ([] if playing else [(tab, 'deactivated')])
    events.clear()
    transitions.clear()
    if destination == 'queue':
        window.tray.show_queue()
    else:
        window.tray.open()
    # 재생 중 창을 닫으면 라이브러리로 돌아온다. 추천 탭처럼 출발한 탭을 지키는 페이지는 예외다.
    returned = tab if host.controllers[tab].keeps_tab_after_close else 'library'
    expected = {'restore': tab, 'queue': 'queue', 'playback': returned, 'fullscreen': returned}[destination]
    assert window.isVisible()
    assert window.pages.currentWidget() is host
    assert host.active_tab == expected
    assert events == [(expected, 'activated')]
    assert transitions == (['queue'] if destination == 'queue' else [])
    assert host.controllers == controllers
    # 열린 창에서 다시 열기를 눌러도 페이지 수명을 다시 시작하지 않는다.
    window.tray.open()
    assert events == [(expected, 'activated')]


def hide_to_tray(window, how):
    """창 X 또는 긴급 탈출 키로 트레이에 숨긴다."""
    if how == 'close':
        window.close()
    else:
        window.activateWindow()
        wait_for(window.isActiveWindow)
        QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_H,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert not window.isVisible()


@pytest.mark.parametrize('how', ['close', 'emergency'])
def test_tray_restore_preserves_library_filter_and_selection(window_factory, monkeypatch, how):
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    window = window_factory()
    library = window.library_page
    wait_frontend_ready(window.web_host, 'library')
    library.bridge.filter('Python', 0)
    selected = library.visible_ids[-1]
    library.bridge.select(selected)
    focus_requests = []
    library.bridge.libraryFocusRequested.connect(focus_requests.append)
    hide_to_tray(window, how)
    window.tray.open()
    assert library.query == 'Python'
    assert library.selected_video_id() == selected
    assert focus_requests == []
    assert window.web_host._pending_focus is None


@pytest.mark.parametrize('how', ['close', 'emergency'])
def test_tray_restore_preserves_rendered_settings_category_and_scroll(window_factory, monkeypatch, how):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    window = window_factory()
    host = window.web_host

    def js(source):
        loop = QEventLoop()
        results = []
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def received(value):
            results.append(value)
            loop.quit()

        host.engine_page.runJavaScript(source, received)
        timer.start(int(UI_READY_TIMEOUT * 1000))
        loop.exec()
        timer.stop()
        assert results, 'JavaScript 응답 시간 초과'
        return results[0]

    def wait_js(source):
        wait_for(lambda: js(source))

    window.navigate_web_tab('settings')
    wait_js('!!document.querySelector("[data-category=keys]")')
    js('document.querySelector("[data-category=keys]").click()')
    wait_js('document.querySelector("[data-category=keys]").getAttribute("aria-current") === "true"')
    js("""window.trayScroll = document.querySelector('table[aria-label="명령별 키 배치"]').parentElement;
          window.trayScroll.scrollTop = 180""")
    before = js('window.trayScroll.scrollTop')
    assert before > 0
    hide_to_tray(window, how)
    window.tray.open()
    assert host.active_tab == 'settings'
    assert js('document.querySelector("[data-category=keys]").getAttribute("aria-current")') == 'true'
    assert js('window.trayScroll.scrollTop') == before


def test_tab_routes_keep_one_web_view_and_native_numbering(window_factory):
    from PySide6.QtWebEngineWidgets import QWebEngineView
    window = window_factory()
    page = window.web_host
    for index, (tab, _) in enumerate(TABS):
        window.navigate_web_tab(tab)
        route = page.routes[tab]
        target = page
        assert window.pages.currentWidget() is target
        assert json.loads(page.bridge.shellSnapshot()) == {'tab': tab, 'status': ''}
        assert window.pages.count() == 2
        assert not window.menuBar().isVisible()
        assert not window.statusBar().isVisible()
        assert len(window.findChildren(QWebEngineView)) == 1
    assert page.active_tab == next(tab for tab, _ in reversed(TABS) if tab in page.controllers)
    assert window.pages.currentWidget() is page


def test_global_web_keys_and_native_escape_return(window_factory):
    window = window_factory()
    window.activateWindow()
    wait_for(window.isActiveWindow)
    for index, (tab, _) in enumerate(TABS):
        target = window.focusWidget() or window
        QTest.keyClick(target, Qt.Key.Key_1 + index, Qt.KeyboardModifier.ControlModifier)
        assert window.web_host.active_tab == tab
    QTest.keyClick(window.focusWidget(), Qt.Key.Key_Escape)
    assert window.pages.currentWidget() is window.web_host
    assert window.web_host.active_tab == next(tab for tab, _ in reversed(TABS) if tab in window.web_host.controllers)




@pytest.mark.parametrize('contract', CONTRACTS, ids=lambda contract: contract.name)
def test_actual_qt_public_slots_and_signals_match_generator_contract(window_factory, contract):
    bridge = window_factory().web_host.channel.registeredObjects()[contract.name]
    meta = bridge.metaObject()
    methods = {bytes(meta.method(i).name()).decode(): meta.method(i)
               for i in range(meta.methodOffset(), meta.methodCount())}
    assert set(methods) == set(contract.slots) | set(contract.signals)
    names = {str: 'QString', int: 'int', float: 'double', bool: 'bool'}
    for name, arguments in contract.slots.items():
        method = methods[name]
        assert method.methodType() == QMetaMethod.MethodType.Slot
        assert method.typeName() == 'QString'
        assert [bytes(t).decode() for t in method.parameterTypes()] == [names[arg.python_type] for arg in arguments]
    for name, kind in contract.signals.items():
        assert methods[name].methodType() == QMetaMethod.MethodType.Signal
        assert [bytes(t).decode() for t in methods[name].parameterTypes()] == [names[kind]]


# 웹 정규화가 코어와 달랐던 이름과 일반 공백·호환 문자. (태그 이름, 사용자가 칠 질의)
@pytest.mark.parametrize('name, query', [
    ('ＳＦＡｃｔｉｏｎ', 'SFAction'), ('ﬃ', 'ffi'), ('Straße', 'STRAẞE'), ('Straße', 'STRASSE'),
    ('ΟΣ', 'ΟΣ'), ('ΟΣ', 'ος'), ('ΟΣ', 'οσ'), ('ışık', 'ışık'), ('IŞIK', 'IŞIK'), ('İ', 'İ'), ('Ꭰ', 'Ꭰ'), ('Ꭰ', 'ꭰ'),
    ('A　B', '  a	 b '), ('A-Ｂ!', 'a-b!'), ('한​글', '한글'),
])
def test_tag_search_key_finds_own_tag_with_core_normalization(core, name, query):
    from my_video_manager.web_shell_bridge import ShellBridge
    tag = core.create_tag(name)
    key = json.loads(ShellBridge(None).tagSearchKey(query))['key']
    assert [usage.tag for usage in core.tag_usage() if key in usage.key] == [tag]
    assert next(usage.key for usage in core.tag_usage() if usage.tag == tag) == key


def test_navigation_rejects_unknown_names_without_transition(window_factory):
    window = window_factory()
    assert 'error' in json.loads(window.web_host.bridge.navigate('deleteLater'))
    QApplication.processEvents()
    assert window.pages.currentWidget() is window.web_host






def test_web_library_playback_restores_filter_and_selection(window_factory, core):
    from test_library_return_ui import Player
    window = window_factory()
    window.player_factory = Player
    window.navigate_web_tab('library')
    library = window.library_page
    library.bridge.filter('Python', 0)
    selected = library.visible_ids[-1]
    library.bridge.select(selected)
    window.play(selected)
    window.back_to_list()
    assert library.query == 'Python' and library.selected_video_id() == selected
    assert window.web_host.active_tab == 'library'


@pytest.mark.parametrize('contract', CONTRACTS, ids=lambda contract: contract.name)
def test_public_javascript_wrapper_hides_qobject_methods_and_signal_emit(contract):
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
      const api = module.exports[contract.wrapper](raw);
      assert.deepEqual(Object.keys(api).sort(), [...contract.slots, ...contract.signals].sort());
      assert.equal(api.deleteLater, undefined); assert.equal(api.objectName, undefined);
      assert(Object.isFrozen(api));
      for (const name of contract.signals) { assert.equal(api[name].emit, undefined); assert(Object.isFrozen(api[name])); }
      let received; api[contract.slots[0]](value => received = value); assert.equal(received, '{}');
    """
    result = subprocess.run(['node', '-e', script], input=json.dumps({'slots': list(contract.slots), 'signals': list(contract.signals), 'wrapper': f'public{contract.interface}'}),
                            cwd=root / 'frontend', text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_chrome_visibility_survives_fullscreen_exit_and_native_window_restore(window_factory, core):
    from test_library_return_ui import Player
    window = window_factory()
    window.player_factory = Player
    window.play(core.videos()[0].id)
    window.set_playback_fullscreen(True)
    assert not window.menuBar().isVisible()
    assert not window.statusBar().isVisible()
    window.set_playback_fullscreen(False)
    assert not window.menuBar().isVisible()
    window.set_playback_fullscreen(True)
    window.showNormal()  # changeEvent 경로도 숨김 정책을 유지한다.
    QApplication.processEvents()
    assert not window.menuBar().isVisible()
    window.back_to_list()
    assert not window.menuBar().isVisible()
    assert not window.statusBar().isVisible()


def test_hidden_status_bar_delivers_notices_to_web(window_factory):
    window = window_factory()
    changes = []
    window.web_host.bridge.shellStatusChanged.connect(changes.append)
    window.show_status('등록 작업 완료')
    assert changes == ['등록 작업 완료']
    assert json.loads(window.web_host.bridge.shellSnapshot())['status'] == '등록 작업 완료'
    window.statusBar().clearMessage()
    assert changes == ['등록 작업 완료', '']
    assert json.loads(window.web_host.bridge.shellSnapshot())['status'] == ''


def test_shell_status_tone_uses_only_known_failure_prefixes(window_factory):
    # 셸 작업 알림은 위계 없는 문자열이다. 앱이 직접 만드는 고정 접두사만 오류·경고로 보이고,
    # 문장 속 "실패"(실패 0개, 영상 제목 등)는 정보로 남는다(frontend/src/lib/shell-status.ts).
    from my_video_manager.library_operations import SCAN_RUNNING_MESSAGE
    from my_video_manager.subtitle_queue import NO_SPEECH_NOTICE
    from my_video_manager.translation_kind import REFINEMENT, TRANSLATION
    cases = [
        ('검사 실패: 폴더에 접근할 수 없습니다.', 'error'),
        ('자막 처리 실패: 작업자 오류', 'error'),
        ('자막 실패 — 다시 시도하세요: 모델 오류', 'error'),
        ('번역 처리 실패: 작업자 오류', 'error'),
        *((f'{task.label} 실패 · 서버 오류 번역 방식 / 재시도에서 다시 요청하세요.', 'error') for task in (TRANSLATION, REFINEMENT)),
        ('썸네일 채우기 실패: 디스크 오류 · 다시 검사하면 재시도합니다.', 'error'),
        ('해상도 채우기 실패: 디스크 오류 · 다시 검사하면 재시도합니다.', 'error'),
        *((f'{task.label} 보류 · 12:30 자동 재시도 · 사용량 한도', 'warning') for task in (TRANSLATION, REFINEMENT)),
        ('자막은 저장됐지만 표시에 실패했습니다: mpv 오류', 'warning'),
        *((f'{task.subtitle_label}은 저장됐지만 표시에 실패했습니다: mpv 오류', 'warning') for task in (TRANSLATION, REFINEMENT)),
        ('썸네일을 만들지 못했습니다: 손상된 파일 · 다시 검사하면 재시도합니다.', 'warning'),
        ('해상도를 읽지 못했습니다: 손상된 파일 · 다시 검사하면 재시도합니다.', 'warning'),
        ('영상 3개 등록 · 전체 10개 · 안내 0개', 'info'),
        (SCAN_RUNNING_MESSAGE, 'info'),
        (f'받아쓰기 완료 · {NO_SPEECH_NOTICE}', 'info'),
        ('원어 자막 완료 · 원어 en · 12줄', 'info'),
        ('이번 처리: 완료 3개 · 말소리 없음 0개 · 실패 0개', 'info'),
        ('‘번역 처리 실패 모음’ 영상을 대기열에 추가했습니다.', 'info'),
        ('번역 처리 실패 모음 영상 등록 완료', 'info'),
    ]
    window = window_factory()
    host = window.web_host

    def js(source):
        result = []
        host.engine_page.runJavaScript(source, result.append)
        wait_for(lambda: bool(result))
        return result[0]

    notice = "document.querySelector('[role][aria-label=\"작업 알림\"]')"
    for text, tone in cases:
        window.show_status(text)
        wait_for(lambda: js(f"{notice}?.textContent ?? ''") == text)
        assert js(f"{notice}.dataset.tone") == tone, text
        assert js(f"{notice}.getAttribute('role')") == ('alert' if tone == 'error' else 'status'), text
