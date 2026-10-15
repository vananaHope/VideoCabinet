"""공개 번역 작업과 실제 가짜 CLI/HTTP 어댑터로 품질·묶음 계약을 검증한다."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from my_video_manager.core import AppCore
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment, TranscriptLine
from my_video_manager.translation import TranslationError, TranslationResponse, TranslatedLine
from my_video_manager.translation_cli import parse_translation_response, translation_schema
from my_video_manager.translation_glossary import Glossary, GlossaryEntry, GLOSSARY_LIMIT
from test_translation import Media, Transcriber, source
from test_translation_cli import fake_cli
from test_opencode_go import server, LocalTransport, completion


class RecordingTranslator:
    def __init__(self):
        self.calls = []
        self.action = None

    def translate(self, lines, language, **kwargs):
        self.calls.append((lines, kwargs))
        if self.action:
            result = self.action(lines, kwargs)
            if result is not None:
                return result
        return TranslationResponse(tuple(TranslatedLine(l.id, '번역 ' + l.text) for l in lines),
                                   (GlossaryEntry('Jon', '존'),))


@pytest.fixture
def quality(tmp_path):
    clock = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    adapter = RecordingTranslator()
    transcriber = Transcriber()

    def create(count=500, *, batch_size=None, translator=adapter, transport=None):
        transcriber.result = TranscriberResult('en', tuple(
            TranscriptSegment(i, i + 1, f'Jon line {i}') for i in range(count)))
        core = AppCore(media=Media(), clock=lambda: clock[0], database=tmp_path / 'data/library.sqlite3',
                       transcriber=transcriber, translator=translator, translation_batch_size=batch_size,
                       translation_transport=transport)
        if not core.videos():
            path = tmp_path / 'video.mkv'
            path.write_bytes(b'video')
            core.add_file(path)
        return core

    return create, adapter, clock


def test_context_glossary_hold_and_single_line_retranslation(quality):
    create, adapter, clock = quality
    core = create(35, batch_size=12)
    video = core.videos()[0].id
    transcript = source(core, video)
    assert core.process_next_translation().completed_lines == 12
    adapter.action = lambda *args: (_ for _ in ()).throw(TranslationError('usage_limit', 'limit'))
    assert core.process_next_translation().state == 'held'
    clock[0] += timedelta(minutes=15)
    adapter.action = lambda lines, kwargs: TranslationResponse(
        tuple(TranslatedLine(l.id, '새 번역') for l in lines), (GlossaryEntry('Jon', '욘'),))
    core.process_next_translation()
    core.process_next_translation()
    assert adapter.calls[-1][1]['glossary'] == (GlossaryEntry('Jon', '존'),)
    context = adapter.calls[1][1]['context']
    assert [l.id for l in context] == [l.id for l in transcript.lines[2:12]]
    assert all(l.translation == '번역 ' + l.text for l in context)
    core.edit_transcript_line(video, transcript.lines[20].id, 'changed')
    core.process_next_translation()
    lines, kwargs = adapter.calls[-1]
    assert [l.id for l in lines] == [transcript.lines[20].id]
    assert [l.id for l in kwargs['context']] == [l.id for l in transcript.lines[10:20]]


def test_untranslated_context_never_uses_stale_translation(quality):
    create, adapter, _ = quality
    core = create(30)
    video = core.videos()[0].id
    transcript = source(core, video)
    core.remove_from_subtitle_queue(video)
    core.request_translation(video, line_ids=[transcript.lines[20].id])
    core.process_next_translation()
    assert len(adapter.calls[0][1]['context']) == 10
    assert all(l.translation is None for l in adapter.calls[0][1]['context'])


def test_context_ids_rejected_and_malformed_glossary_items_ignored():
    lines = (TranscriptLine('target', 1, 2, 'Jon'),)
    response = {'lines': [{'id': 'target', 'text': '존'}], 'glossary': [
        {'source': 'Jon', 'target': '존'}, {'source': 5, 'target': '오'}, None,
        {'source': ' ', 'target': '빈 값'}, {'source': 'Jon'}, {'source': 'x', 'target': 'y', 'extra': 1}]}
    result = parse_translation_response(json.dumps(response), lines)
    assert result.glossary == (GlossaryEntry('Jon', '존'),)
    assert result[0].text == '존'
    response['lines'].append({'id': 'context', 'text': '맥락'})
    with pytest.raises(TranslationError, match='형식'):
        parse_translation_response(json.dumps(response), lines)
    assert translation_schema(lines)['properties']['lines']['items']['properties']['id']['enum'] == ['target']


def test_glossary_limit_preserves_first_translation_and_recently_used():
    entries = tuple(GlossaryEntry(f'name{i:03d}', f'이름{i}') for i in range(GLOSSARY_LIMIT))
    glossary = Glossary(entries).updated((TranscriptLine('x', 0, 1, 'name000'),),
                                        (GlossaryEntry('new', '새 이름'), GlossaryEntry('name001', '다른 이름')))
    assert len(glossary.entries) == GLOSSARY_LIMIT
    values = {e.source: e.target for e in glossary.entries}
    assert values['name000'] == '이름0' and values['name001'] == '이름1'
    assert 'name002' not in values and values['new'] == '새 이름'


@pytest.mark.parametrize('kind', ['usage_limit', 'connection', 'other'])
def test_non_format_failure_does_not_shrink(quality, kind):
    create, adapter, _ = quality
    core = create()
    source(core, core.videos()[0].id)
    adapter.action = lambda *args: (_ for _ in ()).throw(TranslationError(kind, 'failure'))
    result = core.process_next_translation()
    assert result.state == ('held' if kind == 'usage_limit' else 'failed')
    assert [len(lines) for lines, _ in adapter.calls] == [120]


@pytest.mark.parametrize('mode', ['cancel', 'remove', 'edit', 'regenerate'])
def test_shrinking_discards_stale_responses_and_stops_new_calls(quality, mode):
    create, adapter, _ = quality
    core = create()
    video = core.videos()[0].id
    transcript = source(core, video)

    def action(lines, kwargs):
        if len(adapter.calls) == 1:
            raise TranslationError('format', 'bad')
        if mode == 'cancel':
            core.stop_translation_processing()
        elif mode == 'remove':
            core.remove_from_subtitle_queue(video)
        elif mode == 'edit':
            core.edit_transcript_line(video, transcript.lines[0].id, 'new')
        else:
            core.request_subtitles(video)
        raise TranslationError('format', 'stale')

    adapter.action = action
    core.process_next_translation()
    assert [len(lines) for lines, _ in adapter.calls] == [120, 60]
    assert core.translation(video) is None
    assert all(e.completed_lines == 0 for e in core.translation_queue())


@pytest.mark.parametrize('identifier,default', [('codex', 120), ('claude', 120), ('opencode_go', 100)])
def test_real_adapters_shrink_recover_and_share_context_glossary(quality, tmp_path, server, identifier, default):
    create, _, _ = quality
    capture = tmp_path / 'calls.jsonl'
    script = '''
import json, sys
from pathlib import Path
args = sys.argv[1:]
data = json.loads(sys.stdin.read().split('SUBTITLE_DATA_JSON:\\n')[1])
path = Path(CAPTURE)
count = len(path.read_text(encoding='utf-8').splitlines()) if path.exists() else 0
with path.open('a', encoding='utf-8') as f:
    f.write(json.dumps(data) + '\\n')
result = {'lines': [] if count == 0 else [{'id': l['id'], 'text': '존'} for l in data['targets']],
          'glossary': [{'source': 'Jon', 'target': '존' if count == 1 else '욘'}, {'source': 4}]}
if '--output-last-message' in args:
    Path(args[args.index('--output-last-message') + 1]).write_text(json.dumps(result), encoding='utf-8')
else:
    print(json.dumps({'structured_output': result}))
'''.replace('CAPTURE', repr(str(capture)))
    calls = []

    class RespondingTransport(LocalTransport):
        def request(self, method, url, **kwargs):
            payload = json.loads(kwargs['body'])
            data = json.JSONDecoder().raw_decode(payload['messages'][0]['content'].split('SUBTITLE_DATA_JSON:\n')[1])[0]
            calls.append(data)
            result = {'lines': [] if len(calls) == 1 else [
                {'id': l['id'], 'text': '존'} for l in data['targets']],
                'glossary': [{'source': 'Jon', 'target': '존' if len(calls) == 2 else '욘'}, None]}
            server.reply = 200, {}, json.dumps(completion(json.dumps(result))).encode()
            return super().request(method, url, **kwargs)

    core = create(500, translator=fake_cli(tmp_path, script, cli=identifier, timeout=30),
                  transport=RespondingTransport(server.server_port))
    if identifier == 'opencode_go':
        core.save_translation_settings(identifier, core.translation_settings()['selections'], False,
                                       key_action='replace', key='fake-key')
    else:
        core.set_translation_cli(identifier)
    video = core.videos()[0].id
    source(core, video)
    while core.translation_ready():
        assert core.process_next_translation().state in ('queued', 'completed')
    if identifier != 'opencode_go':
        calls = [json.loads(row) for row in capture.read_text(encoding='utf-8').splitlines()]
    assert [len(c['targets']) for c in calls[:5]] == [default, default // 2, default // 2, default // 2, default]
    assert len(calls[2]['context']) == 10
    assert all(l['translation'] == '존' for l in calls[2]['context'])
    assert all(c['glossary'] == [{'source': 'Jon', 'target': '존'}] for c in calls[2:])
    assert len(core.translation(video).lines) == 500


def test_minimum_size_exhaustion_precedes_fallback(quality, server):
    create, adapter, _ = quality
    calls = []

    class RespondingTransport(LocalTransport):
        def request(self, method, url, **kwargs):
            prompt = json.loads(kwargs['body'])['messages'][0]['content']
            data = json.JSONDecoder().raw_decode(prompt.split('SUBTITLE_DATA_JSON:\n')[1])[0]
            calls.append(data)
            server.reply = 200, {}, json.dumps(completion(json.dumps({'lines': [
                {'id': l['id'], 'text': '번역'} for l in data['targets']]}))).encode()
            return super().request(method, url, **kwargs)

    core = create(200, transport=RespondingTransport(server.server_port))
    core.save_translation_settings('codex', core.translation_settings()['selections'], True,
                                   key_action='replace', key='fake-key')
    source(core, core.videos()[0].id)
    adapter.action = lambda *args: (_ for _ in ()).throw(TranslationError('format', 'bad'))
    result = core.process_next_translation()
    assert [len(lines) for lines, _ in adapter.calls] == [120, 60, 30, 15, 10, 10, 10]
    assert len(calls[0]['targets']) == 100
    assert result.completed_lines == 100 and '형식 오류 재시도 소진' in result.notice


@pytest.mark.parametrize('kind', ['usage_limit', 'other'])
def test_glossary_survives_restart_and_failed_retry(quality, kind):
    create, adapter, clock = quality
    core = create(40, batch_size=12)
    video = core.videos()[0].id
    source(core, video)
    core.process_next_translation()
    adapter.action = lambda *args: (_ for _ in ()).throw(TranslationError(kind, 'failure'))
    core.process_next_translation()
    core = create(40, batch_size=12)
    if kind == 'usage_limit':
        clock[0] += timedelta(minutes=15)
    else:
        core.request_translation(video)
    adapter.action = None
    assert core.process_next_translation().completed_lines == 24
    lines, kwargs = adapter.calls[-1]
    assert kwargs['glossary'] == (GlossaryEntry('Jon', '존'),)
    assert lines[0].text == 'Jon line 12'
    assert all(l.translation is not None for l in kwargs['context'])


@pytest.mark.parametrize('finish', ['complete', 'remove', 'regenerate'])
def test_glossary_removed_with_job_and_never_leaks_into_new_job(quality, finish):
    create, adapter, _ = quality
    core = create(25, batch_size=12)
    video = core.videos()[0].id
    source(core, video)
    core.process_next_translation()
    if finish == 'complete':
        while core.translation_ready():
            core.process_next_translation()
        core.request_translation(video)
    elif finish == 'remove':
        core.remove_from_subtitle_queue(video)
        core.request_translation(video)
    else:
        source(core, video)
    core.process_next_translation()
    assert adapter.calls[-1][1]['glossary'] == ()


def test_request_replacement_keeps_committed_glossary_but_not_stale_result(quality):
    create, adapter, _ = quality
    core = create(50, batch_size=12)
    video = core.videos()[0].id
    transcript = source(core, video)
    core.process_next_translation()

    def edit_during_response(lines, kwargs):
        core.edit_transcript_line(video, transcript.lines[30].id, 'new')
        return TranslationResponse(tuple(TranslatedLine(l.id, 'stale') for l in lines),
                                   (GlossaryEntry('stale', '낡음'),))

    adapter.action = edit_during_response
    core.process_next_translation()
    assert core.translation_queue()[0].completed_lines == 12
    adapter.action = None
    core.process_next_translation()
    assert adapter.calls[-1][1]['glossary'] == (GlossaryEntry('Jon', '존'),)


def test_progress_and_glossary_rollback_together(quality):
    from contextlib import closing
    import sqlite3
    create, adapter, _ = quality
    core = create(50, batch_size=12)
    video = core.videos()[0].id
    source(core, video)
    core.process_next_translation()
    # 성공 줄 저장 뒤 용어집 쓰기가 실패해도 부분 진행을 커밋하지 않는다.
    with closing(sqlite3.connect(core.database)) as db:
        db.execute("CREATE TRIGGER fail_glossary BEFORE INSERT ON translation_glossary "
                   "BEGIN SELECT RAISE(ABORT, 'injected write failure'); END")
    result = core.process_next_translation()
    assert result.state == 'failed' and result.completed_lines == 12
    with closing(sqlite3.connect(core.database)) as db:
        db.execute('DROP TRIGGER fail_glossary')
    core = create(50, batch_size=12)
    core.request_translation(video)
    assert core.process_next_translation().completed_lines == 24
    assert adapter.calls[-1][1]['glossary'] == (GlossaryEntry('Jon', '존'),)


def test_repeated_format_failures_shrink_and_recover_in_steps(quality):
    create, adapter, _ = quality
    core = create(500)
    source(core, core.videos()[0].id)
    def action(lines, kwargs):
        if len(adapter.calls) <= 4:
            raise TranslationError('format', 'bad')
    adapter.action = action
    for _ in range(10):
        core.process_next_translation()
    assert [len(lines) for lines, _ in adapter.calls] == [120, 60, 30, 15, 10, 10, 10, 20, 20, 20, 40, 40, 40, 80]


def test_tail_shrinks_actual_size_and_new_job_uses_default(quality):
    create, adapter, _ = quality
    core = create(23)
    video = core.videos()[0].id
    source(core, video)
    def action(lines, kwargs):
        if len(adapter.calls) == 1:
            raise TranslationError('format', 'bad tail')
    adapter.action = action
    core.process_next_translation()
    assert [len(lines) for lines, _ in adapter.calls] == [23, 11]
    while core.translation_ready():
        core.process_next_translation()
    assert [len(lines) for lines, _ in adapter.calls] == [23, 11, 11, 1]
    core.request_translation(video)
    core.process_next_translation()
    assert len(adapter.calls[-1][0]) == 23


def test_hold_breaks_consecutive_successes_without_resetting_reduced_size(quality):
    create, adapter, clock = quality
    core = create()
    source(core, core.videos()[0].id)
    def action(lines, kwargs):
        if len(adapter.calls) == 1:
            raise TranslationError('format', 'bad')
        if len(adapter.calls) == 4:
            raise TranslationError('usage_limit', 'limit')
    adapter.action = action
    for _ in range(3):
        core.process_next_translation()
    clock[0] += timedelta(minutes=15)
    for _ in range(4):
        core.process_next_translation()
    assert [len(lines) for lines, _ in adapter.calls] == [120, 60, 60, 60, 60, 60, 60, 120]
