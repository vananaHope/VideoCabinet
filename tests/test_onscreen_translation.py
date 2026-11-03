"""실제 임시 DB와 가짜 OCR·번역 주체로 화면 번역의 공개 동작을 검증한다."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Event

import pytest

from legacy_schema import replace_with_frozen
from my_video_manager.core import AppCore
from my_video_manager.library import LIBRARY_DB_VERSION
from my_video_manager.onscreen_translation import onscreen_generation_token
from my_video_manager.onscreen_subtitles import RegionRect
from my_video_manager.secret_store import SecretStore
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment
from my_video_manager.subtitle_queue_kind import ONSCREEN_SUBTITLE, TRANSCRIPTION
from my_video_manager.translation import TranslationCancelled, TranslationError, TranslatedLine, TranslationResponse
from my_video_manager.translation_cli import translation_prompt
from my_video_manager.translation_glossary import GlossaryEntry
from my_video_manager.translation_kind import ONSCREEN_TRANSLATION
from my_video_manager.translation_source import ONSCREEN, TRANSCRIPT
from test_backup import apply
from test_onscreen_subtitles import FakeMedia, FakeOcr, BAND, NOW
from test_translation import Transcriber, source, finish
from test_translation_connection import HTTP, save


class Translator:
    def __init__(self):
        self.calls = []
        self.action = None

    def translate(self, lines, language, **kwargs):
        self.calls.append((lines, language, kwargs))
        if self.action:
            result = self.action(lines, kwargs)
            if result is not None:
                return result
        return TranslationResponse(tuple(TranslatedLine(line.id, '번역 ' + line.text) for line in lines),
                                   (GlossaryEntry('Jon', '존'),))


@pytest.fixture
def screen(tmp_path):
    media, ocr, adapter, transcriber = FakeMedia(), FakeOcr(('en', 'ja')), Translator(), Transcriber()
    http, store, clock = HTTP(), SecretStore(tmp_path / 'data'), [NOW]

    def reopen(*, batch_size=2, translator=adapter):
        return AppCore(media=media, clock=lambda: clock[0], ocr_engine=ocr,
                       database=tmp_path / 'data/library.sqlite3', translator=translator,
                       transcriber=transcriber, translation_batch_size=batch_size,
                       translation_secret_store=store, translation_transport=http)

    core = reopen()
    for name in ('a', 'b'):
        path = tmp_path / f'{name}.mkv'
        path.write_bytes(name.encode())
        core.add_file(path)
    return core, media, adapter, transcriber, http, store, clock, reopen


def read_screen(core, media, video, *, captions=((10, 12, 'Jon show'), (20, 22, 'Next'), (30, 32, 'End')),
                regions=((BAND, 'en'),)):
    media.captions = captions
    core.set_onscreen_subtitle_regions(video, regions)
    assert core.process_next_onscreen_subtitle().state == 'completed'
    return tuple(line for subtitle in core.onscreen_subtitles(video) for line in subtitle.lines)


def test_automatic_translation_is_one_to_one_and_resumes_after_restart(screen):
    core, media, adapter, _, _, _, _, reopen = screen
    video = core.videos()[0].id
    original = read_screen(core, media, video)
    entry, = core.translation_queue()
    assert (entry.source, entry.kind, entry.queue_kind) == (ONSCREEN, 'onscreen_translation', ONSCREEN_SUBTITLE)
    assert core.subtitle_queue_items()[0].task_label == '화면 번역'
    assert core.onscreen_translation_skip_reason(video) is None
    assert core.take_subtitle_queue_completion() is None
    assert core.process_next_translation().completed_lines == 2
    assert core.translation(video, source=ONSCREEN) is None
    core = reopen()
    assert core.translation_queue()[0].completed_lines == 2  # 등록 전에 조회하면 KeyError였던 경로
    assert core.process_next_translation().state == 'completed'
    translated = core.translation(video, source=ONSCREEN)
    assert translated.transcript_id == onscreen_generation_token(
        (subtitle.region.id, subtitle.id) for subtitle in core.onscreen_subtitles(video))
    assert [(l.id, l.start, l.end, l.text) for l in translated.lines] == [
        (l.id, l.start, l.end, '번역 ' + l.text) for l in original]
    assert core.translation(video) is None
    assert set(core.translation_line_providers(video, source=ONSCREEN).values()) == {'codex'}
    assert [len(call[0]) for call in adapter.calls] == [2, 1]
    assert core.subtitle_queue_items()[0].task_label == '화면 번역'
    assert core.take_subtitle_queue_completion() == (1, 0, 0, 0)
    assert core.take_subtitle_queue_completion() is None
    assert core.request_translation(video, source=ONSCREEN) is None


@pytest.mark.parametrize('first', [TRANSCRIPT, ONSCREEN])
def test_glossary_is_shared_by_video_across_completion_and_sources_but_not_videos(screen, first):
    core, media, adapter, _, _, _, _, reopen = screen
    a, b = core.videos()
    source(core, a.id)
    read_screen(core, media, a.id)
    core.promote_subtitle(a.id, kind=TRANSCRIPTION if first == TRANSCRIPT else ONSCREEN_SUBTITLE)
    assert core.process_next_translation().source == first
    adapter.action = lambda lines, kwargs: TranslationResponse(
        tuple(TranslatedLine(l.id, '번역 ' + l.text) for l in lines), (GlossaryEntry('Jon', '욘'),))
    finish(core)
    second_calls = [kw for _, _, kw in adapter.calls if kw.get('source', TRANSCRIPT) != first]
    assert second_calls and all(kw['glossary'] == (GlossaryEntry('Jon', '존'),) for kw in second_calls)
    assert core.translation(a.id) is not None and core.translation(a.id, source=ONSCREEN) is not None
    original = core.translation(a.id)
    core = reopen()
    read_screen(core, media, a.id, captions=((1, 3, 'Jon returns'),))
    core.process_next_translation()
    assert adapter.calls[-1][2]['glossary'] == (GlossaryEntry('Jon', '존'),)
    assert core.translation(a.id) == original
    read_screen(core, media, b.id)
    core.process_next_translation()
    assert adapter.calls[-1][2]['glossary'] == ()


@pytest.mark.parametrize('translated', [False, True])
def test_context_is_contemporaneous_speech_and_never_a_target(screen, translated):
    core, media, adapter, transcriber, *_ = screen
    video = core.videos()[0].id
    transcriber.result = TranscriberResult('ko', tuple(TranscriptSegment(start, end, text) for start, end, text in (
        (0, 1, '멀리 있는 말'), (7, 7.99, '경계 밖'), (7.5, 8, '앞 여유'),
        (10.5, 11, '겹치는 말'), (14, 15, '뒤 여유'), (14.01, 15, '뒤 경계 밖'))), model='test')
    transcript = source(core, video)
    if translated:
        finish(core)
    read_screen(core, media, video, captions=((10, 12, 'Jon show'),))
    core.promote_subtitle(video, kind=ONSCREEN_SUBTITLE)
    assert core.process_next_translation().kind == 'onscreen_translation'
    targets, language, kwargs = adapter.calls[-1]
    assert language == 'en' and {line.language for line in targets} == {'en'}
    assert [line.text for line in kwargs['context']] == ['앞 여유', '겹치는 말', '뒤 여유']
    assert all(line.translation == ('번역 ' + line.text if translated else None) for line in kwargs['context'])
    assert {line.id for line in targets}.isdisjoint(line.id for line in transcript.lines)
    prompt = translation_prompt(targets, language, **{k: kwargs[k] for k in ('context', 'glossary', 'source')})
    assert prompt.startswith(ONSCREEN_TRANSLATION.instructions)
    assert json.loads(prompt.split('SUBTITLE_DATA_JSON:\n')[1])['targets'][0]['language'] == 'en'


def test_mixed_region_languages_are_kept_per_target(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    regions = ((BAND, 'en'), (RegionRect(0, 0, 0.5, 0.2), 'ja'))
    read_screen(core, media, video, captions=((1, 3, 'Text'),), regions=regions)
    assert core.process_next_translation().state == 'completed'
    targets, language, kwargs = adapter.calls[-1]
    assert [(line.region_id, line.language) for line in targets] == [(r.id, r.language) for r in core.onscreen_subtitle_regions(video)]
    payload = json.loads(translation_prompt(targets, language, source=ONSCREEN).split('SUBTITLE_DATA_JSON:\n')[1])
    assert [line['language'] for line in payload['targets']] == ['en', 'ja']


@pytest.mark.parametrize('kind', ['usage_limit', 'other', 'format'])
def test_fallback_keeps_progress_settings_notice_and_line_providers(screen, kind):
    core, media, adapter, _, http, store, _, reopen = screen
    video = core.videos()[0].id
    store.save('synthetic-test-key')
    save(core, model='test-model', effort='high')
    original = read_screen(core, media, video)
    assert core.process_next_translation().completed_lines == 2
    assert adapter.calls[-1][2]['model'] == 'test-model' and adapter.calls[-1][2]['effort'] == 'high'
    adapter.action = lambda *_: (_ for _ in ()).throw(TranslationError(kind, 'synthetic failure'))
    result = core.process_next_translation()
    assert result.state == 'completed' and 'OpenCode Go로 이어서 화면 번역' in result.notice
    assert core.translation_line_providers(video, source=ONSCREEN) == {
        original[0].id: 'codex', original[1].id: 'codex', original[2].id: 'opencode_go'}
    prompt = http.requests[-1][3]['messages'][0]['content']
    assert prompt.startswith(ONSCREEN_TRANSLATION.instructions)
    data = json.JSONDecoder().raw_decode(prompt.split('SUBTITLE_DATA_JSON:\n')[1])[0]
    assert [l['id'] for l in data['targets']] == [original[2].id]
    assert data['glossary'] == [{'source': 'Jon', 'target': '존'}]
    assert reopen().translation(video, source=ONSCREEN) == core.translation(video, source=ONSCREEN)


def test_held_and_failed_sources_retry_independently_and_delay_completion(screen):
    core, media, adapter, _, _, _, clock, _ = screen
    video = core.videos()[0].id
    save(core, fallback=False)
    source(core, video)
    adapter.action = lambda *_: (_ for _ in ()).throw(TranslationError('other', 'failed speech'))
    assert core.process_next_translation().state == 'failed'
    read_screen(core, media, video)
    adapter.action = lambda *_: (_ for _ in ()).throw(TranslationError('usage_limit', 'held screen'))
    assert core.process_next_translation().state == 'held'
    assert core.take_subtitle_queue_completion() is None
    assert core.retry_failed_subtitles(kind=ONSCREEN_SUBTITLE).retried == 0
    assert core.retry_failed_subtitles(kind=TRANSCRIPTION).retried == 1
    assert {e.source: e.state for e in core.translation_queue()} == {TRANSCRIPT: 'queued', ONSCREEN: 'held'}
    clock[0] += timedelta(minutes=16)
    adapter.action = None
    finish(core)
    assert core.take_subtitle_queue_completion() == (2, 0, 0, 0)


def test_no_text_reason_is_computed_per_video_and_does_not_omit_future_generation(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    assert core.onscreen_translation_skip_reason(video) is None
    read_screen(core, media, video, captions=())
    assert core.onscreen_translation_skip_reason(video) == 'no_onscreen_text'
    assert not core.translation_queue() and not adapter.calls
    read_screen(core, media, video, captions=((1, 3, 'Found'),))
    assert core.onscreen_translation_skip_reason(video) is None
    finish(core)
    assert core.translation(video, source=ONSCREEN).lines[0].text == '번역 Found'


def test_user_edit_during_response_is_protected_and_persisted(screen):
    core, media, adapter, _, _, _, _, reopen = screen
    video = core.videos()[0].id
    original = read_screen(core, media, video)
    def edit(lines, kwargs):
        core.edit_onscreen_translation_line(original[0].id, '직접 고친 화면 번역')
    adapter.action = edit
    core.process_next_translation()
    adapter.action = None
    finish(core)
    assert core.translation(video, source=ONSCREEN).lines[0].text == '직접 고친 화면 번역'
    assert core.translation_line_providers(video, source=ONSCREEN)[original[0].id] is None
    core = reopen()
    assert core.onscreen_translation_reviewed_lines(video) == {original[0].id}
    assert core.request_translation(video, [original[0].id], source=ONSCREEN) is None
    assert core.request_translation(video, source=ONSCREEN) is None
    assert core.translation(video, source=ONSCREEN).lines[0].text == '직접 고친 화면 번역'
    with pytest.raises(ValueError):
        core.edit_onscreen_translation_line(original[0].id, ' ')
    read_screen(core, media, video)
    assert not core.onscreen_translation_reviewed_lines(video)
    with pytest.raises(ValueError):
        core.edit_onscreen_translation_line(original[0].id, '지워진 줄')


@pytest.mark.parametrize('empty', [False, True])
def test_regeneration_during_inflight_response_discards_old_lines_and_glossary(screen, empty):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    read_screen(core, media, video)
    entered, release = Event(), Event()
    def delayed(lines, kwargs):
        entered.set()
        assert release.wait(10)
        return TranslationResponse(tuple(TranslatedLine(l.id, '낡은 응답') for l in lines), (GlossaryEntry('stale', '낡음'),))
    adapter.action = delayed
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(core.process_next_translation)
        try:
            assert entered.wait(10)
            read_screen(core, media, video, captions=() if empty else ((1, 3, 'New'),))
        finally:
            release.set()
        assert work.result(timeout=10) is None
    adapter.action = None
    if empty:
        assert core.onscreen_translation_skip_reason(video) == 'no_onscreen_text'
        assert not core.translation_queue() and core.translation(video, source=ONSCREEN) is None
    else:
        finish(core)
        assert core.translation(video, source=ONSCREEN).lines[0].text == '번역 New'
        assert adapter.calls[-1][2]['glossary'] == ()


def test_generation_token_changes_for_any_region_and_does_not_depend_on_uuid_order():
    baseline = [(1, 'fff'), (2, 'aaa')]
    token = onscreen_generation_token(baseline)
    assert onscreen_generation_token(reversed(baseline)) == token
    for changed in ([(1, 'fff'), (2, '000')], [(1, 'fff')], baseline + [(3, None)],
                    [(1, 'fff'), (2, 'empty-generation')], [(1, None), (2, 'aaa')]):
        assert onscreen_generation_token(changed) != token


@pytest.mark.parametrize('change', ['regenerate', 'delete', 'empty'])
def test_changed_source_generation_discards_inflight_response_without_replacing_request(screen, change):
    """#283의 개별 영역 편집 API 없이, 공개 출처 주입 경계에서 세대만 바뀐 경우를 재현한다."""
    from dataclasses import replace
    from my_video_manager.subtitles import TranscriptLine
    from my_video_manager.translation_source import TranslationSourceLines
    core, _, adapter, *_ = screen
    video = core.videos()[0].id
    regions = [(1, 'fff'), (2, 'aaa')]
    original = [TranslationSourceLines(onscreen_generation_token(regions), video, 'en',
                tuple(TranscriptLine(str(i), i, i + 1, f'Line {i}') for i in range(3)))]
    test_source = 'injected-region-generations'
    core.register_translation_source(test_source, lambda video_id, *, connection=None: original[0], queue_kind=test_source)
    before = core.request_translation(video, source=test_source)
    def change_generation(lines, kwargs):
        changed = [(1, 'fff')] if change == 'delete' else [(1, 'fff'), (2, '000' if change == 'regenerate' else 'empty')]
        original[0] = replace(original[0], id=onscreen_generation_token(changed))
    adapter.action = change_generation
    assert core.process_next_translation() is None
    entry, = core.translation_queue()
    assert entry.id == before.id and entry.completed_lines == 0
    assert core.translation(video, source=test_source) is None
    adapter.action = None
    core.request_translation(video, source=test_source)
    finish(core)
    assert core.translation(video, source=test_source).transcript_id == original[0].id
    assert adapter.calls[1][2]['glossary'] == ()


def test_generation_change_finishes_surviving_saved_targets_without_retranslating(screen):
    """출처 경계로 영역 삭제를 재현한다. 남은 두 줄은 이전 묶음에서 이미 저장했다."""
    from dataclasses import replace
    from my_video_manager.subtitles import TranscriptLine
    from my_video_manager.translation_source import TranslationSourceLines
    core, _, adapter, *_ = screen
    video = core.videos()[0].id
    original = [TranslationSourceLines(onscreen_generation_token([(1, 'fff'), (2, 'aaa')]), video, 'en',
                tuple(TranscriptLine(str(i), i, i + 1, f'Line {i}') for i in range(3)))]
    test_source = 'injected-region-generations'
    core.register_translation_source(test_source, lambda video_id, *, connection=None: original[0], queue_kind=test_source)
    core.request_translation(video, source=test_source)
    assert core.process_next_translation().completed_lines == 2
    original[0] = replace(original[0], id=onscreen_generation_token([(1, 'fff')]), lines=original[0].lines[:2])
    assert core.request_translation(video, source=test_source).state == 'completed'
    assert not core.translation_queue() and len(adapter.calls) == 1
    assert [line.text for line in core.translation(video, source=test_source).lines] == ['번역 Line 0', '번역 Line 1']
    assert set(core.translation_line_providers(video, source=test_source).values()) == {'codex'}


def test_empty_region_does_not_hide_other_regions_text(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    region_frames = media.region_frames
    def per_region(path, rect, **kwargs):
        media.captions = ((1, 3, 'Text'),) if rect == BAND else ()
        yield from region_frames(path, rect, **kwargs)
    media.region_frames = per_region
    read_screen(core, media, video, regions=((BAND, 'en'), (RegionRect(0, 0, 0.5, 0.2), 'ja')))
    subtitles = core.onscreen_subtitles(video)
    assert [subtitle.no_text for subtitle in subtitles] == [False, True]
    assert core.onscreen_translation_skip_reason(video) is None
    finish(core)
    assert len(core.translation(video, source=ONSCREEN).lines) == 1
    assert core.translation(video, source=ONSCREEN).transcript_id == onscreen_generation_token(
        (s.region.id, s.id) for s in subtitles)


def test_batch_retries_shrink_and_cancelled_work_resumes_from_saved_lines(screen):
    _, media, adapter, _, _, _, _, reopen = screen
    core = reopen(batch_size=120)
    video = core.videos()[0].id
    read_screen(core, media, video, captions=tuple((i * 3, i * 3 + 2, f'Line {i}') for i in range(23)))
    def too_large(lines, kwargs):
        if len(lines) > 15:
            raise TranslationError('format', 'synthetic truncated response')
    adapter.action = too_large
    assert core.process_next_translation().completed_lines == 11
    def cancel(lines, kwargs):
        core.stop_translation_processing()
        raise TranslationCancelled
    adapter.action = cancel
    core.process_next_translation()
    assert core.translation_queue()[0].completed_lines == 11
    core.resume_subtitle_processing()
    adapter.action = None
    finish(core)
    assert len(core.translation(video, source=ONSCREEN).lines) == 23
    assert [len(call[0]) for call in adapter.calls] == [23, 11, 11, 11, 1]


def test_context_ids_in_response_are_rejected(screen):
    core, media, adapter, *_ = screen
    save(core, fallback=False)
    video = core.videos()[0].id
    transcript = source(core, video)
    read_screen(core, media, video, captions=((1, 3, 'Text'),))
    core.promote_subtitle(video, kind=ONSCREEN_SUBTITLE)
    adapter.action = lambda lines, kwargs: TranslationResponse(
        tuple(TranslatedLine(l.id, '번역') for l in lines) + (TranslatedLine(transcript.lines[0].id, '참고 문맥'),))
    assert core.process_next_translation().state == 'failed'
    assert core.translation(video, source=ONSCREEN) is None


@pytest.mark.parametrize('version', [7, 8])
def test_upgrade_carries_pending_legacy_glossary_to_both_sources(screen, version):
    core, media, adapter, _, _, _, _, reopen = screen
    video = core.videos()[0].id
    source(core, video)
    assert core.process_next_translation().completed_lines == 2
    replace_with_frozen(core.database, version)
    core = reopen()
    read_screen(core, media, video)
    core.promote_subtitle(video, kind=ONSCREEN_SUBTITLE)
    assert core.process_next_translation().source == ONSCREEN
    assert adapter.calls[-1][2]['glossary'] == (GlossaryEntry('Jon', '존'),)
    assert next(e for e in core.translation_queue() if e.source == TRANSCRIPT).completed_lines == 2


def test_v9_migration_failure_rolls_back_and_preserves_backup(screen):
    from contextlib import closing
    import sqlite3
    from my_video_manager.library import migrate_library
    core, media, _, _, _, _, _, reopen = screen
    read_screen(core, media, core.videos()[0].id)
    replace_with_frozen(core.database, 8)
    before = core.database.read_bytes()
    with closing(sqlite3.connect(core.database)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY
                          if action == sqlite3.SQLITE_CREATE_TABLE and name == 'onscreen_translation_reviews'
                          else sqlite3.SQLITE_OK)
        with pytest.raises(sqlite3.DatabaseError):
            migrate_library(db)
        db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)
        assert not db.in_transaction and db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert db.execute('PRAGMA user_version').fetchone()[0] == 8
    assert core.database.read_bytes() == before
    restored = reopen()
    assert all(restored.inspect_backup(path).db_version == 8 for path in restored.automatic_backups())
    assert restored.translation_queue()[0].source == ONSCREEN


@pytest.mark.parametrize('version', [7, 8, 9])
def test_upgrade_backup_restore_keeps_onscreen_results_protection_progress_and_video_glossary(screen, tmp_path, version):
    core, media, adapter, _, _, _, _, reopen = screen
    a, b = core.videos()
    source(core, a.id)
    finish(core)
    read_screen(core, media, a.id)
    finish(core)
    first = core.translation(a.id, source=ONSCREEN).lines[0].id
    core.edit_onscreen_translation_line(first, '보호된 번역')
    read_screen(core, media, b.id)
    core.process_next_translation()
    if version < 9:
        # 고정된 이전 버전 DDL에는 화면 번역·보호·영상 용어집이 아직 없다.
        replace_with_frozen(core.database, version)
    archive = core.create_backup(tmp_path / f'v{version}.zip')
    assert archive.metadata.db_version == version
    upgraded = reopen()
    assert upgraded.create_backup(tmp_path / 'upgraded.zip').metadata.db_version == LIBRARY_DB_VERSION == 9
    if version < 9:
        assert upgraded.inspect_backup(upgraded.automatic_backups()[0]).db_version == version
    else:
        assert upgraded.translation(a.id, source=ONSCREEN).lines[0].text == '보호된 번역'
        assert upgraded.onscreen_translation_reviewed_lines(a.id) == {first}
        assert upgraded.translation_queue()[0].completed_lines == 2
    expected = (upgraded.translation(a.id), upgraded.onscreen_subtitles(a.id),
                upgraded.translation(a.id, source=ONSCREEN), upgraded.translation_line_providers(a.id, source=ONSCREEN))
    upgraded.request_backup_restore(archive.path)
    assert apply(core.database).status == 'applied'
    restored = reopen()
    assert (restored.translation(a.id), restored.onscreen_subtitles(a.id),
            restored.translation(a.id, source=ONSCREEN), restored.translation_line_providers(a.id, source=ONSCREEN)) == expected
    if version == 9:
        finish(restored)
        assert adapter.calls[-1][2]['glossary'] == (GlossaryEntry('Jon', '존'),)
