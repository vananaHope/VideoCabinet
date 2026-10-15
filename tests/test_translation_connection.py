"""실행·설정 공개 API로 모델 인자, 이어받기, 줄별 출처를 검증한다."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from threading import Event

import pytest

from my_video_manager.core import AppCore
from my_video_manager.opencode_go import HTTPResponse, OpenCodeGoTranslator
from my_video_manager.secret_store import Secret, SecretStore, SecretStoreError
from my_video_manager.translation import TranslationError, TranslationCancelled
from my_video_manager.translation_models import MODEL_CHOICES
from test_translation import Media, Transcriber, Translator, source, finish
from test_translation_cli import fake_cli
from test_opencode_go import server, LocalTransport, completion, LINES


class HTTP:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.waiting, self.release = Event(), Event()
        self.delay = False

    def request(self, method, url, **kwargs):
        payload = json.loads(kwargs['body']) if kwargs['body'] else None
        self.requests.append((method, url, kwargs['headers'], payload))
        if self.delay:
            self.waiting.set()
            assert kwargs['cancellation'].wait(5)
            raise TranslationCancelled
        if self.status != 200:
            return HTTPResponse(self.status, {'Retry-After': '120'}, b'{"error":"quota_exceeded"}')
        if method == 'GET':
            return HTTPResponse(200, {}, b'{"data":[{"id":"custom-model"}]}')
        if payload.get('max_tokens') == 1:
            return HTTPResponse(200, {}, json.dumps(completion()).encode())
        prompt = payload['messages'][0]['content']
        targets = json.JSONDecoder().raw_decode(prompt.split('SUBTITLE_DATA_JSON:\n')[1])[0]['targets']
        return HTTPResponse(200, {}, json.dumps(completion(json.dumps({'lines': [
            {'id': line['id'], 'text': 'Go ' + line['text']} for line in targets]}))).encode())


@pytest.fixture
def connected(tmp_path):
    http, cli, store = HTTP(), Translator(), SecretStore(tmp_path / 'data')
    clock = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    def reopen(adapter=cli):
        return AppCore(media=Media(), clock=lambda: clock[0], database=tmp_path / 'data/library.sqlite3',
                       transcriber=Transcriber(), translator=adapter, translation_batch_size=2,
                       translation_secret_store=store, translation_transport=http)
    core = reopen()
    for i in range(2):
        path = tmp_path / f'{i}.mkv'
        path.write_bytes(str(i).encode())
        core.add_file(path)
    return core, http, cli, store, clock, reopen


def save(core, identifier='codex', model=None, effort=None, *, fallback=True, key_action='keep', key=''):
    selections = core.translation_settings()['selections']
    selected = next(s for s in selections if s['provider'] == identifier)
    if model is not None:
        selected['model'] = model
    if effort is not None:
        selected['effort'] = effort
    return core.save_translation_settings(identifier, selections, fallback, key_action=key_action, key=key)


@pytest.mark.parametrize('identifier,default', [('codex', 'gpt-5.6-terra'), ('claude', 'claude-sonnet-5-5')])
@pytest.mark.parametrize('model,effort', [(None, ''), ('my-custom-model', 'max'), ('', '')])
def test_actual_cli_arguments_for_unset_explicit_and_cli_default(connected, tmp_path, identifier, default, model, effort):
    _, _, _, _, _, reopen = connected
    capture = tmp_path / 'arguments.json'
    script = '''
import json, sys
from pathlib import Path
args = sys.argv[1:]
Path(CAPTURE).write_text(json.dumps(args))
data = json.loads(sys.stdin.read().split('SUBTITLE_DATA_JSON:\\n')[1])
result = {'lines': [{'id': row['id'], 'text': '번역'} for row in data['targets']]}
if '--output-last-message' in args:
    Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(result), encoding='utf-8')
else:
    print(json.dumps({'structured_output': result}))
'''.replace('CAPTURE', repr(str(capture)))
    adapter = fake_cli(tmp_path, script, cli=identifier)
    core = reopen(adapter)
    if model is None:
        core.set_translation_cli(identifier)
    else:
        save(core, identifier, model, effort)
    source(core, core.videos()[0].id)
    assert core.process_next_translation().state == 'queued'
    args = json.loads(capture.read_text())
    flag = '-m' if identifier == 'codex' else '--model'
    if model == '':
        assert flag not in args
    else:
        assert args[args.index(flag) + 1] == (default if model is None else model)
    if identifier == 'codex':
        assert ('model_reasoning_effort=max' in args) == bool(effort)
        assert '--ignore-user-config' in args
    else:
        assert ('--effort' in args) == bool(effort)
        if effort:
            assert args[args.index('--effort') + 1] == effort


@pytest.mark.parametrize('message', ['The model does not exist', 'Unsupported model custom',
                                    'Invalid value for --effort', 'reasoning_effort is not supported'])
def test_cli_configuration_error_is_failed_not_held(connected, tmp_path, message):
    *_, reopen = connected
    adapter = fake_cli(tmp_path, f'import sys\nprint({message!r}, file=sys.stderr)\nsys.exit(1)')
    core = reopen(adapter)
    save(core, key_action='replace', key='test-key')
    source(core, core.videos()[0].id)
    result = core.process_next_translation()
    assert result.state == 'failed' and result.retry_at is None
    assert '모델을 쓸 수 없음' in result.error
    assert not connected[1].requests
    assert not result.notice


@pytest.mark.parametrize('identifier', ['codex', 'claude'])
@pytest.mark.parametrize('kind,attempts', [('usage_limit', 1), ('other', 1), ('format', 3)])
def test_fallback_only_remaining_lines_persists_route_and_provenance(connected, identifier, kind, attempts):
    core, http, cli, store, _, reopen = connected
    store.save('fake-key-1234')
    core.set_translation_cli(identifier)
    video = core.videos()[0]
    transcript = source(core, video.id)
    assert core.process_next_translation().completed_lines == 2
    cli.error = TranslationError(kind, '실패')
    result = core.process_next_translation()
    assert result.completed_lines == 4
    reason = {'usage_limit': '사용량 한도', 'other': 'CLI 오류', 'format': '형식 오류 재시도 소진'}[kind]
    assert reason in result.notice and 'OpenCode Go로 이어서 번역' in result.notice
    assert reason in core.subtitle_queue_items()[0].error
    assert len(cli.calls) == 1 + attempts
    core = reopen()
    result = core.process_next_translation()
    assert result.state == 'completed'
    assert reason in result.notice
    assert reason in core.subtitle_queue_items()[0].error
    assert len(cli.calls) == 1 + attempts
    assert {h['x-opencode-session'] for _, _, h, _ in http.requests} == {http.requests[0][2]['x-opencode-session']}
    assert len(http.requests) == 2
    providers = core.translation_line_providers(video.id)
    assert [providers[line.id] for line in transcript.lines] == [identifier] * 2 + ['opencode_go'] * 3
    assert [line.text.startswith('Go ') for line in core.translation(video.id).lines] == [False] * 2 + [True] * 3


@pytest.mark.parametrize('registered,enabled', [(False, True), (True, False)])
def test_fallback_requires_key_and_enabled(connected, registered, enabled):
    core, http, cli, store, _, _ = connected
    if registered:
        store.save('key')
    save(core, fallback=enabled)
    source(core, core.videos()[0].id)
    cli.error = TranslationError('usage_limit', '한도')
    assert core.process_next_translation().state == 'held'
    assert not http.requests


def test_go_primary_all_batches_distinct_job_session_and_no_unknown_effort(connected):
    core, http, cli, _, _, _ = connected
    notice = save(core, 'opencode_go', 'custom-model', 'high', key_action='replace', key='test-key-1234')
    assert '기본' in notice
    for video in core.videos():
        source(core, video.id)
    finish(core)
    assert not cli.calls and len(http.requests) == 6
    sessions = [h['x-opencode-session'] for _, _, h, _ in http.requests]
    assert sessions[0] == sessions[1] == sessions[2]
    assert sessions[3] == sessions[4] == sessions[5] != sessions[0]
    assert all(p['model'] == 'custom-model' and 'reasoning_effort' not in p for _, _, _, p in http.requests)


def test_fallback_go_limit_honors_server_retry_time_and_resumes_go(connected):
    core, http, cli, store, clock, _ = connected
    store.save('key')
    source(core, core.videos()[0].id)
    cli.error = TranslationError('usage_limit', '한도')
    http.status = 429
    result = core.process_next_translation()
    assert result.state == 'held' and result.retry_at == clock[0] + timedelta(seconds=120)
    assert not core.translation_ready()
    clock[0] += timedelta(seconds=121)
    http.status = 200
    finish(core)
    assert len(cli.calls) == 1


@pytest.mark.parametrize('during_go', [False, True])
def test_user_cancel_never_falls_back_and_cleans_processing(connected, during_go):
    core, http, cli, store, _, reopen = connected
    store.save('key')
    started = Event()
    class CancelCLI:
        def translate(self, *args, cancellation, **kwargs):
            started.set()
            assert cancellation.wait(5)
            raise TranslationCancelled
    if during_go:
        save(core, 'opencode_go')
        http.delay = True
        started = http.waiting
    else:
        core = reopen(CancelCLI())
    source(core, core.videos()[0].id)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(core.process_next_translation)
        assert started.wait(5)
        core.stop_translation_processing()
        assert future.result(2).completed_lines == 0
    assert len(http.requests) == int(during_go)
    assert core.translation_queue()[0].state == 'queued'


def test_model_key_edit_validation_persistence_and_no_secret_in_snapshot(connected):
    core, _, _, store, _, reopen = connected
    assert save(core, 'codex', 'custom-codex', 'max', key_action='replace', key='secret-1234') == ''
    save(core, 'claude', 'custom-claude', 'high')
    core = reopen()
    state = core.translation_settings()
    assert [(s['model'], s['effort']) for s in state['selections'][:2]] == [('custom-codex', 'max'), ('custom-claude', 'high')]
    assert 'secret-1234' not in json.dumps(state) and state['key_masked'] == '****1234'
    assert b'secret-1234' not in core.database.read_bytes()
    assert b'secret-1234' not in store.path.read_bytes()
    with pytest.raises(ValueError):
        save(core, 'opencode_go', '', key_action='delete')
    assert store.read().reveal() == 'secret-1234'
    assert core.translation_cli == 'claude'
    save(core, key_action='delete')
    assert not core.translation_settings()['key_masked']
    assert not core.translation_settings()['fallback']


def test_local_server_key_check_and_known_effort_payload(server):
    server.reply = 200, {}, json.dumps(completion()).encode()
    choice = replace(MODEL_CHOICES[0], reasoning_efforts=('low', 'high'))
    adapter = OpenCodeGoTranslator(lambda: Secret('fake-key'), session_id='job', transport=LocalTransport(server.server_port),
                                   choices=(choice,), effort='high')
    adapter.translate(LINES, 'en')
    assert json.loads(server.requests[-1][2])['reasoning_effort'] == 'high'
    assert adapter.check_key().status == 'valid'
    assert json.loads(server.requests[-1][2])['max_tokens'] == 1
    assert server.requests[0][1]['X-Opencode-Session'] != server.requests[1][1]['X-Opencode-Session']


def test_key_storage_failure_rolls_back_settings_and_does_not_repeat_decrypt(connected, monkeypatch):
    core, _, _, store, _, _ = connected
    store.save('original-key-1234')
    reads = []
    original = store.read
    def read():
        reads.append(True)
        return original()
    monkeypatch.setattr(store, 'read', read)
    before = core.translation_settings()
    core.translation_settings()
    assert len(reads) == 1
    def fail(key):
        raise SecretStoreError('키를 암호화해 저장하지 못했습니다.')
    monkeypatch.setattr(store, 'save', fail)
    with pytest.raises(SecretStoreError):
        save(core, 'claude', 'changed-model', key_action='replace', key='new-key-5678')
    assert core.translation_settings() == before
    assert original().reveal() == 'original-key-1234'


def test_unreadable_key_can_be_replaced_or_deleted(connected):
    core, _, _, store, _, _ = connected
    store.path.parent.mkdir(parents=True)
    store.path.write_bytes(b'invalid encrypted data')
    assert core.translation_settings()['key_error']
    save(core, key_action='replace', key='recovered-key-1234')
    assert store.read().reveal() == 'recovered-key-1234'
    store.path.write_bytes(b'invalid encrypted data')
    save(core, key_action='delete')
    assert store.read() is None


def test_retranslation_keeps_old_visible_provider_until_atomic_commit(connected):
    core, http, _, store, _, _ = connected
    video = core.videos()[0]
    transcript = source(core, video.id)
    finish(core)
    store.save('key')
    core.set_translation_cli('opencode_go')
    core.request_translation(video.id)
    core.process_next_translation()
    assert set(core.translation_line_providers(video.id).values()) == {'codex'}
    finish(core)
    assert set(core.translation_line_providers(video.id).values()) == {'opencode_go'}
    core.set_translation_cli('claude')
    core.edit_transcript_line(video.id, transcript.lines[0].id, 'edited')
    finish(core)
    provenance = core.translation_line_providers(video.id)
    assert provenance[transcript.lines[0].id] == 'claude'
    assert {provenance[l.id] for l in transcript.lines[1:]} == {'opencode_go'}


@pytest.mark.parametrize('status,expected', [(401, '키 또는 접근 권한'), (503, '요청에 실패')])
def test_primary_go_error_preserves_safe_provider_specific_message(connected, status, expected):
    core, http, _, store, _, _ = connected
    store.save('key')
    core.set_translation_cli('opencode_go')
    source(core, core.videos()[0].id)
    # 한도 응답이 아닌 실제 실패를 주입한다.
    def fail(*args, **kwargs):
        return HTTPResponse(status, {}, b'{"error":"server secret"}')
    http.request = fail
    result = core.process_next_translation()
    assert result.state == 'failed' and result.retry_at is None
    assert expected in result.error and 'server secret' not in result.error_detail


@pytest.mark.parametrize('identifier', ['codex', 'claude', 'opencode_go'])
def test_running_job_freezes_provider_model_effort_across_restart(connected, identifier):
    core, http, cli, store, _, reopen = connected
    store.save('key')
    calls = []
    original = cli.translate
    def translate(*args, **kwargs):
        calls.append((kwargs['cli'], kwargs['model'], kwargs['effort']))
        return original(*args, **kwargs)
    cli.translate = translate
    save(core, identifier, model='first-model', effort='high')
    first, second = core.videos()
    source(core, first.id)
    source(core, second.id)
    core.process_next_translation()
    save(core, identifier, model='next-model', effort='low')
    core.set_translation_cli('claude' if identifier == 'opencode_go' else 'opencode_go')
    core = reopen()
    core.process_next_translation()
    core.process_next_translation()
    if identifier == 'opencode_go':
        assert [p['model'] for _, _, _, p in http.requests] == ['first-model'] * 3
        assert not calls
    else:
        assert calls == [(identifier, 'first-model', 'high')] * 3
        assert not http.requests
    finish(core)
    if identifier == 'opencode_go':
        assert all(c[0] == 'claude' for c in calls)
    else:
        assert len(http.requests) == 3
    core.set_translation_cli(identifier)
    core.request_translation(first.id)
    finish(core)
    if identifier == 'opencode_go':
        assert [p['model'] for _, _, _, p in http.requests[-3:]] == ['next-model'] * 3
    else:
        assert calls[-3:] == [(identifier, 'next-model', 'low')] * 3


def test_manual_translation_removes_machine_provenance(connected):
    core = connected[0]
    video = core.videos()[0]
    transcript = source(core, video.id)
    finish(core)
    line = transcript.lines[0]
    core.edit_translation_line(video.id, line.id, '직접 고친 번역')
    assert core.review_lines(video.id)[0].translation_reviewed
    assert not core.translation_line_providers(video.id)[line.id]


def test_fallback_uses_go_model_from_job_start_and_backoff_keeps_notice(connected):
    core, http, cli, store, _, _ = connected
    store.save('key')
    save(core, 'opencode_go', model='first-go-model')
    core.set_translation_cli('codex')
    first, second = core.videos()
    source(core, first.id)
    core.process_next_translation()
    save(core, 'opencode_go', model='next-go-model')
    core.set_translation_cli('codex')
    cli.error = TranslationError('usage_limit', 'quota')
    finish(core)
    assert [p['model'] for _, _, _, p in http.requests] == ['first-go-model'] * 2
    source(core, second.id)
    result = core.process_next_translation()
    assert '사용량 한도' in result.notice  # 이미 보류된 CLI를 건너뛴 작업도 원인을 남긴다.
    assert http.requests[-1][3]['model'] == 'next-go-model'
    assert len(cli.calls) == 2
