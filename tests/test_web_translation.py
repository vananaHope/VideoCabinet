"""실제 WebEngine에서 번역 편집·취소·비동기 수명과 키보드를 확인한다."""
from datetime import timedelta
from dataclasses import replace
import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest

from test_translation_connection import connected, save
from test_web_library_page import window_factory as base_window_factory
from test_web_dialogs import within, wait_for, state, act


@pytest.fixture
def window_factory(base_window_factory):
    def create():
        window = base_window_factory()
        window.activateWindow()
        window.web_host.view.setFocus()
        wait_for(lambda: window.web_host._loaded_notified)
        # 초기 라이브러리 focus 신호의 두 프레임 적용까지 끝낸 뒤 모달을 연다.
        js(window, 'window.translationTestReady = false; requestAnimationFrame(() => requestAnimationFrame(() => {window.translationTestReady = true}))')
        wait_for(lambda: js(window, 'window.translationTestReady'))
        return window
    return create


@pytest.fixture
def core(connected):
    return connected[0]


def js(window, source):
    result = []
    window.web_host.engine_page.runJavaScript(source, result.append)
    wait_for(lambda: bool(result))
    return result[0]


def loaded(window):
    window.subtitles.timer.stop()
    window.translations.timer.stop()
    wait_for(lambda: js(window, '!!document.querySelector("[data-translation-form]")'))
    wait_for(lambda: js(window, 'document.activeElement.getAttribute("aria-label")') == '번역 방식')


def rendered(window):
    # 입력/React 갱신이 두 프레임을 통과했는지 확인한다. 고정 시간에 기대지 않는다.
    js(window, 'window.translationRendered = false; requestAnimationFrame(() => requestAnimationFrame(() => {window.translationRendered = true}))')
    wait_for(lambda: js(window, 'window.translationRendered'))


def click(window, text):
    assert js(window, f"""(() => {{ const e = Array.from(document.querySelectorAll('[role=dialog] button')).find(e => e.textContent === {json.dumps(text)});
        if (!e || e.disabled) return false; e.click(); return true; }})()""")
    rendered(window)


def input_text(window, label, value):
    js(window, f"""(() => {{ const e = document.querySelector('[aria-label={json.dumps(label)}]');
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, {json.dumps(value)});
        e.dispatchEvent(new Event('input', {{bubbles:true}})); e.focus(); }})()""")
    rendered(window)


def open_choice(window, label):
    js(window, f"""(() => {{ const e = document.querySelector('[aria-label={json.dumps(label)}]');
        e.focus(); e.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}})); }})()""")
    wait_for(lambda: js(window, '!!document.querySelector("[data-slot=select-content]")'))


def choose(window, label, value):
    # Radix Select는 목록을 연 뒤 바깥 값(data-value)이 같은 항목을 눌러 고른다.
    open_choice(window, label)
    js(window, f"document.querySelector('[data-slot=select-item][data-value={json.dumps(value)}]').click()")
    wait_for(lambda: js(window, '!document.querySelector("[data-slot=select-content]")'))
    rendered(window)


def choice_options(window, label):
    open_choice(window, label)
    text = js(window, 'document.querySelector("[data-slot=select-content]").textContent')
    js(window, "document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    wait_for(lambda: js(window, '!document.querySelector("[data-slot=select-content]")'))
    return text


def capture(window, name):
    if output := os.environ.get('MVM_TRANSLATION_SCREEN_DIR'):
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        rendered(window)
        pixmap = window.grab()
        assert (pixmap.width(), pixmap.height()) == (1100, 720)
        assert pixmap.save(str(directory / (name + '.png')))


@pytest.mark.parametrize('provider,key,expired,long_model', [
    ('codex', False, False, False), ('claude', False, False, False),
    ('opencode_go', False, False, False), ('opencode_go', True, False, False),
    ('opencode_go', True, True, False), ('codex', True, False, True),
])
def test_real_translation_layout_and_keyboard(window_factory, connected, provider, key, expired, long_model):
    core, _, _, store, clock, _ = connected
    if key:
        store.save('screenshot-fake-key-1234')
    if expired:
        clock[0] += timedelta(days=20)
    model = 'extremely-long-custom-model-' * 12 if long_model else None
    save(core, provider, model=model)
    window = window_factory()
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    window.resize(1100, 720)
    dialogs = window.web_host.dialogs
    def check():
        loaded(window)
        assert js(window, 'document.activeElement.getAttribute("aria-label")') == '번역 방식'
        assert js(window, 'document.querySelector("[data-dialog-frame]").scrollWidth <= document.querySelector("[data-dialog-frame]").clientWidth')
        assert js(window, '!!document.querySelector("[aria-label=\'추론 강도\']")') == (provider != 'opencode_go')
        text = js(window, 'document.querySelector("[role=dialog]").textContent')
        if provider == 'opencode_go':
            assert '2026-10-31' in text and 'OpenCode 서버' in text
            assert ('주의:' in text) == expired
        assert ('등록됨 (****1234)' in text) == key
        if expired:
            assert js(window, 'document.querySelector("[role=note] .bg-highlight") !== null')
        if long_model:
            assert js(window, 'document.querySelector("[aria-label=\'모델 직접 입력\']").value') == model
        geometry = json.loads(js(window, """JSON.stringify((() => {
            const footer = document.querySelector('[role=dialog] footer').getBoundingClientRect();
            const last = document.querySelector('[data-dialog-body]').getBoundingClientRect();
            return {bottom: footer.bottom, top: footer.top, fields: last.bottom, height: innerHeight};
        })())"""))
        assert geometry['bottom'] <= geometry['height'] and geometry['fields'] <= geometry['top'], geometry
        capture(window, f'{provider}-key-{key}-expired-{expired}-long-{long_model}')
        view = window.web_host.view.focusProxy() or window.web_host.view
        QTest.keyClick(view, Qt.Key.Key_Tab)
        wait_for(lambda: js(window, 'document.activeElement.getAttribute("aria-label")') == '모델 목록')
        assert js(window, 'document.activeElement.getAttribute("aria-label")') == '모델 목록'
        QTest.keyClick(view, Qt.Key.Key_Tab)
        wait_for(lambda: js(window, 'document.activeElement.getAttribute("aria-label")') == '모델 직접 입력')
        assert js(window, 'document.activeElement.getAttribute("aria-label")') == '모델 직접 입력'
        for keycode in range(Qt.Key.Key_1, Qt.Key.Key_7 + 1):
            QTest.keyClick(view, Qt.Key(keycode), Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(view, Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier)
        QTest.keyClick(view, Qt.Key.Key_F1)
        assert dialogs.active and window.web_host.active_tab == 'library'
        # 합성 IME 조합 중 Esc는 닫지 않고, 조합 종료 뒤 Esc는 초안을 버린다.
        js(window, "document.activeElement.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true}))")
        QTest.keyClick(view, Qt.Key.Key_Escape)
        rendered(window)
        assert dialogs.active
        js(window, "document.activeElement.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true}))")
        rendered(window)
        QTest.keyClick(view, Qt.Key.Key_Escape)
        wait_for(lambda: not dialogs.active)
    within(window.translations.settings, dialogs, check)


def test_real_editor_preserves_each_provider_and_discards_key_on_cancel(window_factory, connected):
    core, _, _, store, _, _ = connected
    store.save('existing-key-1234')
    window = window_factory()
    dialogs = window.web_host.dialogs
    def cancel():
        loaded(window)
        input_text(window, '모델 직접 입력', 'my-codex')
        choose(window, '추론 강도', 'max')
        choose(window, '번역 방식', 'claude')
        input_text(window, '모델 직접 입력', 'my-claude')
        choose(window, '번역 방식', 'codex')
        assert js(window, 'document.querySelector("[aria-label=\'모델 직접 입력\']").value') == 'my-codex'
        assert js(window, 'document.querySelector("[aria-label=\'추론 강도\']").dataset.value') == 'max'
        input_text(window, 'OpenCode Go 키 입력', 'replacement-key-5678')
        click(window, '키 지우기')
        assert js(window, 'document.querySelector("input[type=checkbox]").disabled')
        assert not js(window, 'document.querySelector("input[type=checkbox]").checked')
        click(window, '취소')
    within(window.translations.settings, dialogs, cancel)
    assert store.read().reveal() == 'existing-key-1234'
    assert core.translation_settings()['selections'][0]['model'] == 'gpt-5.6-terra'
    def commit():
        loaded(window)
        input_text(window, '모델 직접 입력', 'saved-model')
        input_text(window, 'OpenCode Go 키 입력', 'replacement-key-5678')
        click(window, '확인')
    within(window.translations.settings, dialogs, commit)
    assert store.read().reveal() == 'replacement-key-5678'
    assert core.translation_settings()['selections'][0]['model'] == 'saved-model'


@pytest.mark.parametrize('action', ['check-key', 'load-models'])
def test_async_key_request_cancels_without_saving_or_stale_dialog_update(window_factory, connected, action):
    core, http, _, store, _, _ = connected
    window = window_factory()
    dialogs = window.web_host.dialogs
    http.delay = True
    def check():
        loaded(window)
        act(dialogs, action, key_action='replace', key='draft-secret-1234')
        wait_for(http.waiting.is_set)
        assert state(dialogs)['network_busy']
        assert store.read() is None
        click(window, '취소')
        wait_for(lambda: dialogs.translation_worker is None)
        assert store.read() is None
    within(window.translations.settings, dialogs, check)
    assert len(http.requests) == 1
    def reopened():
        loaded(window)
        assert not state(dialogs)['network_busy'] and not state(dialogs)['warning']
    within(window.translations.settings, dialogs, reopened)


def test_explicit_key_check_models_and_settings_status(window_factory, connected):
    core, http, _, store, _, _ = connected
    window = window_factory()
    window.resize(1100, 720)
    dialogs = window.web_host.dialogs
    def check():
        loaded(window)
        assert not http.requests
        input_text(window, 'OpenCode Go 키 입력', 'draft-secret-1234')
        click(window, '키 확인')
        wait_for(lambda: dialogs.translation_worker is None)
        assert '키 확인 성공' in state(dialogs)['information']
        assert not state(dialogs)['warning']
        assert store.read() is None
        click(window, '모델 목록 조회')
        wait_for(lambda: dialogs.translation_worker is None)
        choose(window, '번역 방식', 'opencode_go')
        assert 'custom-model' in choice_options(window, '모델 목록')
        assert dialogs.active
        click(window, '확인')
    within(window.translations.settings, dialogs, check)
    assert store.read().reveal() == 'draft-secret-1234'
    assert 'OpenCode Go (API)' in window.statusBar().currentMessage()
    assert 'opencode_go' not in window.statusBar().currentMessage()
    window.navigate_web_tab('settings')
    wait_for(lambda: js(window, '!!document.querySelector("[data-category=translation]")'))
    js(window, 'document.querySelector("[data-category=translation]").click()')
    wait_for(lambda: js(window, '!!document.querySelector("[aria-label=\'번역 설정\']")'))
    text = js(window, 'document.querySelector("[aria-label=\'번역 설정\']").textContent')
    assert 'OpenCode Go (API)' in text and 'deepseek-v4.1-flash' in text
    assert '등록됨 (****1234)' in text and '이어서: 켬' in text
    capture(window, 'settings-translation')


def test_training_policy_warning_comes_from_bridge_data(window_factory, connected, monkeypatch):
    from my_video_manager import translation_options
    core = connected[0]
    go = translation_options.PROVIDERS[-1]
    choice = go.models[0]
    training = replace(choice, policy=replace(choice.policy, training=True))
    monkeypatch.setattr(translation_options, 'PROVIDERS', (*translation_options.PROVIDERS[:-1], replace(go, models=(training,))))
    core.set_translation_cli('opencode_go')
    window = window_factory()
    window.resize(1100, 720)
    dialogs = window.web_host.dialogs
    def check():
        loaded(window)
        text = js(window, 'document.querySelector("[role=note]").textContent')
        assert '학습 사용 ·' in text and '주의:' in text
        assert js(window, 'document.querySelector("[role=note] .bg-destructive") !== null')
        capture(window, 'opencode-policy-training-fixture')
    within(window.translations.settings, dialogs, check)


def test_high_effort_and_key_feedback_scroll_above_footer(window_factory):
    window = window_factory()
    window.resize(1100, 720)
    dialogs = window.web_host.dialogs
    def check():
        loaded(window)
        choose(window, '추론 강도', 'max')
        input_text(window, 'OpenCode Go 키 입력', 'draft-key-1234')
        click(window, '키 확인')
        wait_for(lambda: dialogs.translation_worker is None)
        assert '키 확인 성공' in state(dialogs)['information']
        assert not state(dialogs)['warning']
        geometry = json.loads(js(window, """JSON.stringify((() => {
            const d=document.querySelector('[role=dialog]'), f=d.querySelector('footer').getBoundingClientRect();
            const b=d.querySelector('[data-dialog-body]');
            return {footer:f.top, body:b.getBoundingClientRect().bottom, height:b.clientHeight, content:b.scrollHeight};
        })())"""))
        assert geometry['body'] <= geometry['footer'], geometry
        assert geometry['content'] > geometry['height'], geometry
        js(window, "document.querySelector('[data-dialog-body]').scrollTop = 9999")
        capture(window, 'high-effort-feedback')
        click(window, '취소')
    within(window.translations.settings, dialogs, check)


def test_fallback_notice_and_manual_label_in_real_window(window_factory, connected):
    from test_translation import source, finish
    from my_video_manager.translation import TranslationError
    from my_video_manager.web_dialogs_entries import ReviewDialog
    core, _, cli, store, _, _ = connected
    store.save('key')
    video = core.videos()[0]
    transcript = source(core, video.id)
    cli.error = TranslationError('usage_limit', 'quota')
    results = finish(core)
    line = transcript.lines[0]
    core.edit_translation_line(video.id, line.id, '직접 고친 번역')
    window = window_factory()
    window.resize(1100, 720)
    window.translations.completed(results[-1])
    assert '사용량 한도' in window.statusBar().currentMessage()
    assert 'OpenCode Go로 이어서 번역' in window.statusBar().currentMessage()
    dialogs = window.web_host.dialogs
    def check():
        wait_for(lambda: js(window, '!!document.querySelector("[role=dialog]")'))
        row = next(r for r in state(dialogs)['rows'] if r['id'] == line.id)
        assert '직접 수정' in row['status'] and 'OpenCode' not in row['status']
        capture(window, 'manual-review-fallback-notice')
    within(lambda: ReviewDialog(core, video.id, window.review_jump, window.review_changed, window).exec(), dialogs, check)
    window.navigate_web_tab('queue')
    wait_for(lambda: '사용량 한도' in js(window, 'document.body.textContent'))
    assert '사용량 한도' in js(window, 'document.body.textContent')
    capture(window, 'queue-fallback-notice')


def test_key_failure_diagnostic_is_rendered(window_factory, connected, tmp_path, monkeypatch):
    core, http, _, _, _, _ = connected
    http.status = 402
    window = window_factory()
    window.resize(1100, 720)
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    dialogs = window.web_host.dialogs
    def check():
        loaded(window)
        input_text(window, 'OpenCode Go 키 입력', 'fake-key-for-check')
        click(window, '키 확인')
        wait_for(lambda: dialogs.translation_worker is None)
        rendered(window)
        warning = state(dialogs)['warning']
        assert 'HTTP 402: quota_exceeded' in warning and '구독 또는 결제' in warning
        assert warning in js(window, 'document.querySelector("[role=dialog]").textContent')
        if output := os.environ.get('MVM_KEY_FAILURE_SCREEN_DIR'):
            monkeypatch.setenv('MVM_TRANSLATION_SCREEN_DIR', output)
            js(window, "document.querySelector('[role=dialog] [role=status]').scrollIntoView({block:'center',behavior:'instant'})")
            QTest.qWait(500)
            capture(window, 'key-check-failure')
        click(window, '취소')
    within(window.translations.settings, dialogs, check)
