"""실제 임시 DB와 가짜 OCR·번역 주체로 화면 번역의 공개 동작을 검증한다."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
import json
import sqlite3
from threading import Event

import pytest

from legacy_schema import replace_with_frozen
from my_video_manager.core import AppCore
from my_video_manager.library import LIBRARY_DB_VERSION
from my_video_manager.onscreen_translation import onscreen_generation_token
from my_video_manager.onscreen_subtitles import OnScreenRegionChanged, RegionRect
from my_video_manager.review import ReviewConfirmationRequired
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
    assert core.subtitle_queue_items()[0].error == '화면 자막 3줄'
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


def test_overlapping_screen_targets_share_deduplicated_speech_context(screen):
    core, media, adapter, transcriber, *_ = screen
    video = core.videos()[0].id
    transcriber.result = TranscriberResult('en', (
        TranscriptSegment(10, 11, 'Shared speech'), TranscriptSegment(12, 13, 'Next speech')),
        model='test')
    transcript = source(core, video)
    core.remove_from_subtitle_queue(video)
    read_screen(core, media, video, captions=((10, 12, 'Jon show'),),
                regions=((BAND, 'en'), (RegionRect(0, 0, 1, .2), 'ja')))
    finish(core)
    targets, _, kwargs = adapter.calls[-1]
    assert len(targets) == 2 and len({line.region_id for line in targets}) == 2
    assert [line.id for line in kwargs['context']] == [line.id for line in transcript.lines]


@pytest.mark.parametrize('count', [120, 250])
def test_large_onscreen_batches_share_nearest_context_across_every_target(screen, tmp_path, count):
    core, media, adapter, transcriber, _, _, _, reopen = screen
    media.duration = max(1300, count * 10 + 20)
    path = tmp_path / 'long.mkv'
    path.write_bytes(b'long-context-video')
    core.add_file(path)
    video = next(v.id for v in core.videos() if v.title == 'long')
    core = reopen(batch_size=count)
    transcriber.result = TranscriberResult('en', tuple(
        TranscriptSegment(i * 2, i * 2 + 1, f'Speech {i}') for i in range(count * 5)), model='test')
    transcript = source(core, video)
    core.remove_from_subtitle_queue(video)
    read_screen(core, media, video, captions=tuple((i * 10, i * 10 + 2, f'Caption {i}') for i in range(count)))
    finish(core)
    speech = {line.id: line for line in transcript.lines}
    assert sum(len(targets) for targets, _, _ in adapter.calls) == count
    for targets, _, kwargs in adapter.calls:
        context = kwargs['context']
        assert len(targets) <= 200 and len(context) <= max(100, len(targets)) <= 200
        assert len({line.id for line in context}) == len(context)
        assert [speech[line.id].start for line in context] == sorted(speech[line.id].start for line in context)
        # 먼저 가장 가까운 겹치는 말소리를 배분해야 앞쪽의 여유 문맥이 뒤쪽 대상을 밀어내지 않는다.
        for target in targets:
            assert any(speech[line.id].start == target.start for line in context), target
        assert all(any(speech[line.id].start <= target.end + 2 and speech[line.id].end >= target.start - 2
                       for target in targets) for line in context)


@pytest.mark.parametrize('remaining', ['saved', 'progress', 'queue', 'none'])
def test_regenerated_speech_shares_glossary_only_when_another_source_remains(screen, remaining):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    source(core, video)
    finish(core)
    if remaining != 'none':
        read_screen(core, media, video)
        if remaining == 'saved':
            finish(core)
        elif remaining == 'progress':
            assert core.process_next_translation().completed_lines == 2
    source(core, video)  # 원어 세대 교체로 기존 말소리 번역 결과와 작업은 사라진다.
    core.promote_subtitle(video, kind=TRANSCRIPTION)
    assert core.process_next_translation().source == TRANSCRIPT
    assert adapter.calls[-1][2]['glossary'] == (() if remaining == 'none' else (GlossaryEntry('Jon', '존'),))


def test_removing_all_partial_sources_clears_glossary_on_next_job_after_restart(screen):
    core, media, adapter, _, _, _, _, reopen = screen
    video = core.videos()[0].id
    source(core, video)
    core.process_next_translation()
    read_screen(core, media, video)
    core.promote_subtitle(video, kind=ONSCREEN_SUBTITLE)
    core.process_next_translation()
    for kind in (TRANSCRIPTION, ONSCREEN_SUBTITLE):
        core.remove_from_subtitle_queue(video, kind=kind)
    assert not core.translation_queue()
    assert core.translation(video) is None and core.translation(video, source=ONSCREEN) is None
    core = reopen()
    core.request_translation(video, source=ONSCREEN)
    core.process_next_translation()
    assert adapter.calls[-1][2]['glossary'] == ()


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
    assert 'spoken_language' not in payload


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
    assert 'spoken_language' not in data
    item = next(item for item in core.subtitle_queue_items() if item.queue_kind == ONSCREEN_SUBTITLE)
    assert item.error.startswith('화면 자막 3줄 · ')
    assert 'OpenCode Go로 이어서 화면 번역' in item.error
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


@pytest.mark.parametrize('version', [7, 8, 9, 10])
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
    if version < LIBRARY_DB_VERSION:
        # 고정된 이전 버전 DDL에는 화면 번역·보호·영상 용어집(v9), 원문 검수·구간 요청(v10)이 아직 없다.
        replace_with_frozen(core.database, version)
    archive = core.create_backup(tmp_path / f'v{version}.zip')
    assert archive.metadata.db_version == version
    upgraded = reopen()
    assert upgraded.create_backup(tmp_path / 'upgraded.zip').metadata.db_version == LIBRARY_DB_VERSION == 10
    if version < LIBRARY_DB_VERSION:
        assert upgraded.inspect_backup(upgraded.automatic_backups()[0]).db_version == version
    if version >= 9:
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
    if version >= 9:
        finish(restored)
        assert adapter.calls[-1][2]['glossary'] == (GlossaryEntry('Jon', '존'),)


# #283 영역 하나씩 고치기·지우기: 그 영역의 화면 번역 자막과 검수 기록만 따라간다.
TOP = RegionRect(0.6, 0.02, 0.38, 0.1)


def read_two_regions(core, media, video):
    media.captions_by_region = {BAND: ((10, 12, 'Jon show'), (20, 22, 'Next')), TOP: ((5, 7, 'Corner'),)}
    core.add_onscreen_subtitle_region(video, BAND, 'en')
    core.add_onscreen_subtitle_region(video, TOP, 'ja')
    assert core.process_next_onscreen_subtitle().state == 'completed'
    return core.onscreen_subtitles(video)


def translated(core, video):
    return {line.id: line.text for line in core.translation(video, source=ONSCREEN).lines}


def test_each_region_line_gets_its_own_onscreen_translation_in_its_language(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, top = read_two_regions(core, media, video)
    finish(core)
    assert translated(core, video) == {**{l.id: '번역 ' + l.text for l in bottom.lines},
                                       top.lines[0].id: '번역 Corner'}
    languages = {line.id: line.language for call in adapter.calls for line in call[0]}
    assert languages == {**{l.id: 'en' for l in bottom.lines}, top.lines[0].id: 'ja'}


def test_reviewed_line_count_is_per_region_and_none_until_read(screen):
    core, media, *_ = screen
    video = core.videos()[0].id
    core.add_onscreen_subtitle_region(video, BAND, 'en')
    waiting, = core.onscreen_subtitle_regions(video)
    assert core.onscreen_subtitle_region_reviewed_line_count(waiting.id) is None
    core.delete_onscreen_subtitle_region(waiting.id)
    bottom, top = read_two_regions(core, media, video)
    finish(core)
    assert [core.onscreen_subtitle_region_reviewed_line_count(s.region.id) for s in (bottom, top)] == [0, 0]
    core.edit_onscreen_translation_line(bottom.lines[0].id, '고친 번역')
    core.edit_onscreen_translation_line(bottom.lines[1].id, '또 고친 번역')
    core.edit_onscreen_translation_line(top.lines[0].id, '고친 코너')
    assert [core.onscreen_subtitle_region_reviewed_line_count(s.region.id) for s in (bottom, top)] == [2, 1]
    # 읽은 글자가 없는 영역도 화면 자막이 있는 영역이다(줄 0개).
    media.captions_by_region[RegionRect(0, 0.4, 0.5, 0.2)] = ()
    core.add_onscreen_subtitle_region(video, RegionRect(0, 0.4, 0.5, 0.2), 'en')
    core.process_next_onscreen_subtitle()
    empty = core.onscreen_subtitles(video)[2]
    assert empty.no_text and core.onscreen_subtitle_region_reviewed_line_count(empty.region.id) == 0
    with pytest.raises(ValueError):
        core.onscreen_subtitle_region_reviewed_line_count(waiting.id)


def test_updating_one_region_retranslates_only_its_lines_and_keeps_other_reviews(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, top = read_two_regions(core, media, video)
    finish(core)
    core.edit_onscreen_translation_line(bottom.lines[0].id, '고친 번역')
    core.edit_onscreen_translation_line(top.lines[0].id, '고친 코너')
    kept = {line.id: translated(core, video)[line.id] for line in bottom.lines}
    moved = RegionRect(0.1, 0.4, 0.8, 0.2)
    media.captions_by_region[moved] = ((40, 42, 'Moved corner'),)
    core.update_onscreen_subtitle_region(top.region.id, moved, 'en')
    assert core.onscreen_translation_reviewed_lines(video) == {bottom.lines[0].id}
    assert core.onscreen_subtitle_region_reviewed_line_count(top.region.id) is None
    assert core.onscreen_subtitle_region_reviewed_line_count(bottom.region.id) == 1
    assert core.process_next_onscreen_subtitle().state == 'completed'
    adapter.calls.clear()
    finish(core)
    _, new_top = core.onscreen_subtitles(video)
    # 다시 번역하는 것은 고친 영역의 새 줄뿐이다. 다른 영역의 번역·검수 수정은 그대로다.
    assert [[line.text for line in call[0]] for call in adapter.calls] == [['Moved corner']]
    assert translated(core, video) == {**kept, new_top.lines[0].id: '번역 Moved corner'}
    assert core.onscreen_translation_reviewed_lines(video) == {bottom.lines[0].id}


def test_deleting_one_region_removes_its_translations_and_reviews_only(screen):
    core, media, adapter, *_, reopen = screen
    video = core.videos()[0].id
    bottom, top = read_two_regions(core, media, video)
    finish(core)
    core.edit_onscreen_translation_line(bottom.lines[0].id, '고친 번역')
    core.edit_onscreen_translation_line(top.lines[0].id, '고친 코너')
    kept = {line.id: translated(core, video)[line.id] for line in bottom.lines}
    calls = len(adapter.calls)
    core.delete_onscreen_subtitle_region(top.region.id)
    assert translated(core, video) == kept
    assert core.onscreen_translation_reviewed_lines(video) == {bottom.lines[0].id}
    assert core.translation_queue() == () and len(adapter.calls) == calls
    reopened = reopen()
    assert reopened.onscreen_subtitles(video) == (bottom,)
    assert translated(reopened, video) == kept
    assert reopened.onscreen_translation_reviewed_lines(video) == {bottom.lines[0].id}


def test_deleting_a_region_mid_translation_finishes_only_the_remaining_lines(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, top = read_two_regions(core, media, video)
    assert core.process_next_translation().completed_lines == 2  # 묶음 크기 2: 세 줄 중 두 줄
    core.delete_onscreen_subtitle_region(top.region.id)
    adapter.calls.clear()
    finish(core)
    sent = {line.text for call in adapter.calls for line in call[0]}
    assert 'Corner' not in sent
    assert set(translated(core, video)) == {line.id for line in bottom.lines}


# #285 검수: 화면 자막 원문 줄 고치기. 원문 검수됨으로 남고 그 줄의 화면 번역만 다시 번역한다.
def review_flags(core, video):
    """줄 ID → (원문, 화면 번역, 원문 검수됨, 직접 수정). 영역마다 검수 화면이 보는 줄."""
    return {line.original.id: (line.original.text, line.translation, line.original_reviewed, line.translation_reviewed)
            for subtitle in core.onscreen_subtitles(video) for line in core.onscreen_review_lines(subtitle.region.id)}


def test_editing_an_onscreen_line_retranslates_only_that_line_and_survives_restart(screen):
    core, media, adapter, *_, reopen = screen
    video, other = (v.id for v in core.videos())
    bottom, top = read_two_regions(core, media, video)
    elsewhere = read_two_regions(core, media, other)
    finish(core)
    core.edit_onscreen_translation_line(top.lines[0].id, '고친 코너')
    before, untouched = review_flags(core, video), review_flags(core, other)
    adapter.calls.clear()
    edited = bottom.lines[1]
    core.edit_onscreen_subtitle_line(edited.id, '  Next   scene \r\n\n second ')
    # 원문은 화면 자막 읽기와 같은 정규화로 저장된다. 줄 ID와 시각은 그대로다.
    changed = {**before, edited.id: ('Next scene\nsecond', '번역 Next', True, False)}
    assert review_flags(core, video) == changed
    new_bottom, new_top = core.onscreen_subtitles(video)
    assert new_top == top and [(l.id, l.start, l.end) for l in new_bottom.lines] == [
        (l.id, l.start, l.end) for l in bottom.lines]
    finish(core)
    assert [[line.text for line in call[0]] for call in adapter.calls] == [['Next scene\nsecond']]
    changed[edited.id] = ('Next scene\nsecond', '번역 Next scene\nsecond', True, False)
    assert review_flags(core, video) == changed
    assert core.onscreen_translation_reviewed_lines(video) == {top.lines[0].id}
    assert review_flags(core, other) == untouched and core.onscreen_subtitles(other) == elsewhere
    reopened = reopen()
    assert review_flags(reopened, video) == changed
    assert reopened.onscreen_subtitles(video)[0].lines[1].text == 'Next scene\nsecond'


def test_unchanged_or_invalid_onscreen_line_edit_changes_nothing(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, _ = read_two_regions(core, media, video)
    finish(core)
    before, calls = review_flags(core, video), len(adapter.calls)
    core.edit_onscreen_subtitle_line(bottom.lines[0].id, ' Jon   show ')  # 정규화하면 같은 글자
    for line_id, text in ((bottom.lines[0].id, ' \n '), ('없는 줄', '글자')):
        with pytest.raises(ValueError):
            core.edit_onscreen_subtitle_line(line_id, text)
    assert review_flags(core, video) == before
    assert core.translation_queue() == () and len(adapter.calls) == calls


def test_onscreen_line_edit_is_locked_while_that_video_is_read(screen):
    core, media, adapter, *_ = screen
    video, other = (v.id for v in core.videos())
    bottom, _ = read_two_regions(core, media, video)
    read_two_regions(core, media, other)
    finish(core)
    core.add_onscreen_subtitle_region(video, RegionRect(0, 0.4, 0.5, 0.2), 'en')  # 그 영상의 화면 자막 읽기 대기
    before = review_flags(core, video)
    with pytest.raises(ValueError, match='읽기가 끝난 뒤 검수'):
        core.edit_onscreen_subtitle_line(bottom.lines[0].id, 'Locked')
    assert review_flags(core, video) == before
    # 다른 영상은 잠기지 않고, 화면 번역 줄 수정은 코어에서 지금처럼 잠그지 않는다.
    core.edit_onscreen_subtitle_line(core.onscreen_subtitles(other)[0].lines[0].id, 'Free')
    core.edit_onscreen_translation_line(bottom.lines[0].id, '고친 번역')
    assert core.onscreen_translation_reviewed_lines(video) == {bottom.lines[0].id}


def test_onscreen_line_edit_is_refused_while_another_region_failed_to_read(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, _ = read_two_regions(core, media, video)
    finish(core)
    media.error_at = 0
    core.add_onscreen_subtitle_region(video, RegionRect(0, 0.4, 0.5, 0.2), 'en')
    assert core.process_next_onscreen_subtitle().state == 'failed'
    before = review_flags(core, video)
    # 실패한 영역의 읽기가 끝나기 전에는 화면 번역을 요청할 수 없어 고친 줄이 다시 번역되지 못한다.
    with pytest.raises(ValueError, match='다시 시도'):
        core.edit_onscreen_subtitle_line(bottom.lines[0].id, 'Waiting')
    assert review_flags(core, video) == before


def test_region_reviewed_count_counts_original_and_translation_edits_once_per_line(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, top = read_two_regions(core, media, video)
    finish(core)
    core.edit_onscreen_subtitle_line(bottom.lines[0].id, 'Jon shows')
    core.edit_onscreen_translation_line(bottom.lines[0].id, '존 쇼')
    core.edit_onscreen_subtitle_line(bottom.lines[1].id, 'Next one')
    core.edit_onscreen_subtitle_line(top.lines[0].id, 'Corner!')
    count = core.onscreen_subtitle_region_reviewed_line_count
    assert [count(bottom.region.id), count(top.region.id)] == [2, 1]
    # 원문만 고친 줄은 보호된 번역이 아니다. 다시 번역되어 새 원문의 번역이 된다.
    assert core.onscreen_translation_reviewed_lines(video) == {bottom.lines[0].id}
    finish(core)
    assert translated(core, video) == {bottom.lines[0].id: '존 쇼', bottom.lines[1].id: '번역 Next one',
                                       top.lines[0].id: '번역 Corner!'}
    with pytest.raises(OnScreenRegionChanged):
        core.delete_onscreen_subtitle_region(top.region.id, expected_reviewed_line_count=0)
    core.delete_onscreen_subtitle_region(top.region.id, expected_reviewed_line_count=1)


def test_v9_library_upgrades_keeping_onscreen_lines_translations_and_reviews(screen):
    core, media, adapter, *_, reopen = screen
    video = core.videos()[0].id
    bottom, top = read_two_regions(core, media, video)
    finish(core)
    core.edit_onscreen_translation_line(top.lines[0].id, '고친 코너')
    expected = (core.onscreen_subtitles(video), core.translation(video, source=ONSCREEN),
                core.translation_line_providers(video, source=ONSCREEN), core.onscreen_translation_reviewed_lines(video))
    replace_with_frozen(core.database, 9)
    upgraded = reopen()
    with closing(sqlite3.connect(core.database)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == LIBRARY_DB_VERSION == 10
    assert upgraded.inspect_backup(upgraded.automatic_backups()[0]).db_version == 9
    assert (upgraded.onscreen_subtitles(video), upgraded.translation(video, source=ONSCREEN),
            upgraded.translation_line_providers(video, source=ONSCREEN),
            upgraded.onscreen_translation_reviewed_lines(video)) == expected
    assert [upgraded.onscreen_subtitle_region_reviewed_line_count(s.region.id) for s in expected[0]] == [0, 1]
    assert not any(flags[2] for flags in review_flags(upgraded, video).values())
    upgraded.edit_onscreen_subtitle_line(bottom.lines[0].id, 'Jon shows')
    assert review_flags(upgraded, video)[bottom.lines[0].id][2]


def test_editing_original_of_a_hand_fixed_translation_asks_and_cancel_changes_nothing(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, _ = read_two_regions(core, media, video)
    assert core.process_next_translation().completed_lines == 2  # 세 줄 중 한 줄은 아직 번역 대기
    line = bottom.lines[0]
    core.edit_onscreen_translation_line(line.id, '직접 고친 번역')
    before = (review_flags(core, video), core.translation_queue(), core.onscreen_translation_reviewed_lines(video),
              core.translation_line_providers(video, source=ONSCREEN))
    with pytest.raises(ReviewConfirmationRequired, match='덮어'):
        core.edit_onscreen_subtitle_line(line.id, 'Jon shows')
    assert (review_flags(core, video), core.translation_queue(), core.onscreen_translation_reviewed_lines(video),
            core.translation_line_providers(video, source=ONSCREEN)) == before
    # 확인하면 그 줄의 보호가 풀리고 새 원문으로 다시 번역된다.
    core.edit_onscreen_subtitle_line(line.id, 'Jon shows', overwrite_reviewed=True)
    assert core.onscreen_translation_reviewed_lines(video) == frozenset()
    assert review_flags(core, video)[line.id] == ('Jon shows', '직접 고친 번역', True, False)
    adapter.calls.clear()
    finish(core)
    assert sorted(line.text for call in adapter.calls for line in call[0]) == ['Jon shows', 'Next']
    assert review_flags(core, video)[line.id] == ('Jon shows', '번역 Jon shows', True, False)


def test_hand_fixed_onscreen_translation_survives_every_retranslation(screen):
    core, media, adapter, *_, reopen = screen
    video = core.videos()[0].id
    bottom, top = read_two_regions(core, media, video)
    finish(core)
    kept = bottom.lines[0]
    core.edit_onscreen_translation_line(kept.id, '고친 번역')
    assert core.request_translation(video, source=ONSCREEN) is None  # 그 영상 화면 번역 재요청
    assert core.request_translation(video, [kept.id], source=ONSCREEN) is None
    core.edit_onscreen_subtitle_line(bottom.lines[1].id, 'Next one')  # 다른 줄 원문 수정
    core.edit_onscreen_subtitle_line(top.lines[0].id, 'Corner!')
    adapter.calls.clear()
    finish(core)
    assert sorted(line.text for call in adapter.calls for line in call[0]) == ['Corner!', 'Next one']
    assert translated(core, video) == {kept.id: '고친 번역', bottom.lines[1].id: '번역 Next one',
                                       top.lines[0].id: '번역 Corner!'}
    assert reopen().onscreen_translation_reviewed_lines(video) == {kept.id}


def three_line_regions(core, media, video):
    """아래 영역 두 줄(Jon show 10–12, Next 20–22), 위 영역 한 줄(Corner 5–7). 번역까지 끝낸다."""
    bottom, top = read_two_regions(core, media, video)
    finish(core)
    return bottom, top


def test_range_regeneration_rereads_only_the_widened_interval_and_translates_only_new_lines(screen):
    core, media, adapter, *_, reopen = screen
    video = core.videos()[0].id
    media.captions_by_region = {BAND: ((10, 12, 'Jon show'), (20, 22, 'Next'), (30, 32, 'End')),
                                TOP: ((5, 7, 'Corner'), (21, 23, 'Top next'))}
    core.add_onscreen_subtitle_region(video, BAND, 'en')
    core.add_onscreen_subtitle_region(video, TOP, 'ja')
    assert core.process_next_onscreen_subtitle().state == 'completed'
    finish(core)
    bottom, top = core.onscreen_subtitles(video)
    first, inside, last = bottom.lines
    core.edit_onscreen_translation_line(first.id, '고친 첫 줄')  # 구간 밖 직접 수정
    core.edit_onscreen_subtitle_line(last.id, 'The End')  # 구간 밖 원문 수정
    core.edit_onscreen_translation_line(inside.id, '사라질 수정')  # 구간 안의 검수 기록은 줄과 함께 사라진다
    finish(core)
    kept = {line_id: flags for line_id, flags in review_flags(core, video).items() if line_id != inside.id}
    assert core.onscreen_subtitle_region_reviewed_line_count(bottom.region.id) == 3
    media.captions_by_region[BAND] = ((10, 12, 'Jon show'), (20, 21, 'New one'), (21, 22, 'New two'), (30, 32, 'End'))
    media.captions_by_region[TOP] = ((5, 7, 'Changed corner'),)  # 다른 영역은 다시 읽지 않는다
    media.intervals.clear()
    entry = core.request_onscreen_subtitle_range(bottom.region.id, 20.5, 21.5)
    assert (entry.state, entry.queue_kind) == ('queued', ONSCREEN_SUBTITLE)
    adapter.calls.clear()
    assert core.process_next_onscreen_subtitle().state == 'completed'
    assert media.intervals == [(BAND, 20, 22)]
    new_bottom, new_top = core.onscreen_subtitles(video)
    assert new_top == top and new_bottom.id == bottom.id
    assert [(l.start, l.end, l.text) for l in new_bottom.lines] == [
        (10, 12, 'Jon show'), (20, 21, 'New one'), (21, 22, 'New two'), (30, 32, 'The End')]
    assert (new_bottom.lines[0].id, new_bottom.lines[3].id) == (first.id, last.id)
    new_ids = {new_bottom.lines[1].id, new_bottom.lines[2].id}
    assert not new_ids & {line.id for line in bottom.lines}
    assert core.onscreen_subtitle_region_reviewed_line_count(bottom.region.id) == 2
    finish(core)
    assert sorted(line.text for call in adapter.calls for line in call[0]) == ['New one', 'New two']
    expected = {**kept, **{line.id: (line.text, '번역 ' + line.text, False, False) for line in new_bottom.lines[1:3]}}
    assert review_flags(core, video) == expected
    assert core.onscreen_translation_reviewed_lines(video) == {first.id}
    assert core.translation(video, source=ONSCREEN) is not None
    reopened = reopen()
    assert reopened.onscreen_subtitles(video) == (new_bottom, new_top)
    assert review_flags(reopened, video) == expected
    assert sorted(r.text for r in core.search('next').results) == ['Top next', '번역 Top next']


@pytest.mark.parametrize('stop', ['failure', 'cancel'])
def test_failed_or_cancelled_range_reading_keeps_the_original_lines(screen, stop):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, top = three_line_regions(core, media, video)
    before = review_flags(core, video)
    media.captions_by_region[BAND] = ((20, 22, 'Replaced'),)
    core.request_onscreen_subtitle_range(bottom.region.id, 20, 22)
    if stop == 'failure':
        media.error_at = 82
        assert core.process_next_onscreen_subtitle().state == 'failed'
        assert core.subtitle_queue(kind=ONSCREEN_SUBTITLE)[0].state == 'failed'
    else:
        media.hook = lambda index: core.stop_onscreen_subtitle_processing() if index == 82 else None
        assert core.process_next_onscreen_subtitle().state == 'queued'
        assert core.subtitle_queue(kind=ONSCREEN_SUBTITLE)[0].state == 'queued'
    assert core.onscreen_subtitles(video) == (bottom, top) and review_flags(core, video) == before
    # 다시 시도하면 같은 구간을 다시 읽는다.
    media.error_at = media.hook = None
    if stop == 'failure':
        core.retry_failed_subtitles(kind=ONSCREEN_SUBTITLE)
    else:
        core.resume_subtitle_processing()
    media.intervals.clear()
    assert core.process_next_onscreen_subtitle().state == 'completed'
    assert media.intervals == [(BAND, 20, 22)]
    assert [l.text for l in core.onscreen_subtitles(video)[0].lines] == ['Jon show', 'Replaced']


def test_range_regeneration_is_locked_while_that_video_is_read(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, top = three_line_regions(core, media, video)
    core.request_onscreen_subtitle_range(bottom.region.id, 20, 22)
    queued = core.subtitle_queue(kind=ONSCREEN_SUBTITLE)
    for call in (lambda: core.request_onscreen_subtitle_range(top.region.id, 5, 7),
                 lambda: core.edit_onscreen_subtitle_line(top.lines[0].id, 'Locked')):
        with pytest.raises(ValueError, match='읽기가 끝난 뒤 검수'):
            call()
    assert core.subtitle_queue(kind=ONSCREEN_SUBTITLE) == queued
    assert core.onscreen_subtitles(video) == (bottom, top)


def test_range_request_survives_adding_a_region_and_is_dropped_when_its_region_changes(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, top = three_line_regions(core, media, video)
    extra = RegionRect(0, 0.4, 0.5, 0.2)
    media.captions_by_region[extra] = ((50, 52, 'Extra'),)
    media.captions_by_region[BAND] = ((20, 22, 'Replaced'),)
    core.request_onscreen_subtitle_range(bottom.region.id, 20, 22)
    # 영역을 더하면 대기열 항목이 새로 바뀌어도 구간 요청은 남아 한 번에 함께 읽는다.
    core.add_onscreen_subtitle_region(video, extra, 'en')
    media.intervals.clear()
    assert core.process_next_onscreen_subtitle().state == 'completed'
    assert media.intervals == [(BAND, 20, 22), (extra, None, None)]
    assert [l.text for l in core.onscreen_subtitles(video)[0].lines] == ['Jon show', 'Replaced']
    finish(core)
    # 영역을 고치면 그 세대의 구간 요청은 버리고 영역 전체를 읽는다.
    core.request_onscreen_subtitle_range(top.region.id, 5, 7)
    moved = RegionRect(0.1, 0.4, 0.8, 0.2)
    media.captions_by_region[moved] = ((40, 42, 'Moved'),)
    core.update_onscreen_subtitle_region(top.region.id, moved, 'en')
    media.intervals.clear()
    assert core.process_next_onscreen_subtitle().state == 'completed'
    assert media.intervals == [(moved, None, None)]
    # 지운 영역의 구간 요청도 남지 않는다.
    core.request_onscreen_subtitle_range(bottom.region.id, 20, 22)
    core.delete_onscreen_subtitle_region(bottom.region.id)
    assert core.process_next_onscreen_subtitle() is None


def test_failed_region_is_read_again_together_with_a_range_request(screen):
    core, media, adapter, *_ = screen
    video = core.videos()[0].id
    bottom, top = three_line_regions(core, media, video)
    extra = RegionRect(0, 0.4, 0.5, 0.2)
    media.captions_by_region[extra] = ((50, 52, 'Extra'),)
    media.error_at = 0
    core.add_onscreen_subtitle_region(video, extra, 'en')
    assert core.process_next_onscreen_subtitle().state == 'failed'
    media.error_at = None
    media.captions_by_region[BAND] = ((20, 22, 'Replaced'),)
    core.request_onscreen_subtitle_range(bottom.region.id, 20, 22)
    media.intervals.clear()
    adapter.calls.clear()
    assert core.process_next_onscreen_subtitle().state == 'completed'
    assert media.intervals == [(BAND, 20, 22), (extra, None, None)]
    finish(core)
    assert sorted(line.text for call in adapter.calls for line in call[0]) == ['Extra', 'Replaced']
