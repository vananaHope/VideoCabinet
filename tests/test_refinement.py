"""다듬기의 공개 코어 계약: 별도 경로 없이 번역의 수명과 진행을 공유한다."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from my_video_manager.core import AppCore
from my_video_manager.review import ReviewConfirmationRequired
from my_video_manager.subtitles import TranscriberResult, TranscriptSegment, TranscriptLine
from my_video_manager.translation import TranslationError, TranslationCancelled, TranslationResponse, TranslatedLine
from my_video_manager.translation_cli import translation_prompt, parse_translation_response
from my_video_manager.translation_glossary import GlossaryEntry
from test_translation import Media, Transcriber, source, finish


class Adapter:
    def __init__(self):
        self.calls = []
        self.action = None

    def translate(self, lines, language, **kwargs):
        self.calls.append((lines, language, kwargs))
        if self.action:
            result = self.action(lines, kwargs)
            if result is not None:
                return result
        return TranslationResponse(tuple(TranslatedLine(l.id, l.text.replace('할수', '할 수')) for l in lines),
                                   (GlossaryEntry('한빛', '한빛'),))


@pytest.fixture
def refinement(tmp_path):
    transcriber, adapter = Transcriber(), Adapter()
    transcriber.result = TranscriberResult('ko', tuple(
        TranscriptSegment(i * 2, i * 2 + 1, f'한빛 {i} 할수 있어요.') for i in range(5)))
    now = [datetime(2026, 10, 15, tzinfo=timezone.utc)]

    def reopen():
        return AppCore(media=Media(), clock=lambda: now[0], database=tmp_path / 'data/library.sqlite3',
                       transcriber=transcriber, translator=adapter, translation_batch_size=2)

    core = reopen()
    for i in range(2):
        path = tmp_path / f'video-{i}.mkv'
        path.write_bytes(f'video {i}'.encode())
        core.add_file(path)
    return core, transcriber, adapter, now, reopen


@pytest.mark.parametrize('language', [None, 'ko', 'en'])
def test_automatic_kind_and_independent_storage(refinement, language):
    core, _, adapter, _, reopen = refinement
    vid = core.videos()[0].id
    original = source(core, vid, language)
    expected = 'translation' if language == 'en' else 'refinement'
    assert core.subtitle_task(vid).kind == expected
    assert core.translation_queue()[0].kind == expected
    assert core.process_next_translation().completed_lines == 2
    core = reopen()
    assert core.translation_queue()[0].completed_lines == 2
    assert core.translation_queue()[0].kind == expected
    finish(core)
    assert core.transcript(vid) == original
    result = core.translation(vid)
    assert [(l.id, l.start, l.end) for l in result.lines] == [(l.id, l.start, l.end) for l in original.lines]
    assert all('할 수' in l.text for l in result.lines)
    assert adapter.calls[1][2]['glossary'] == (GlossaryEntry('한빛', '한빛'),)
    assert len(adapter.calls[1][2]['context']) == 2
    with sqlite3.connect(core.database) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4


def test_existing_korean_requires_explicit_bulk_or_individual_request(refinement):
    core, _, _, _, reopen = refinement
    a, b = core.videos()
    source(core, a.id)
    source(core, b.id, 'en')
    core.remove_from_subtitle_queue(a.id)
    # 옛 v4에는 한국어 omission도 없다. 기존 한국어는 시작/묶음마다 자동 등록하지 않는다.
    with sqlite3.connect(core.database) as db:
        db.execute('DELETE FROM translation_omissions')
    core = reopen()
    assert [e.video_id for e in core.translation_queue()] == [b.id]
    finish(core)
    assert not core.translation_queue()
    assert core.request_existing_refinements() == (1, 0)
    assert core.translation_queue()[0].video_id == a.id
    finish(core)
    assert core.request_refinement(a.id).kind == 'refinement'
    with pytest.raises(ValueError):
        core.request_refinement(b.id)


def test_review_protection_source_choice_and_only_changed_line(refinement):
    core, _, adapter, _, reopen = refinement
    vid = core.videos()[0].id
    original = source(core, vid)
    finish(core)
    line = original.lines[0]
    core.edit_translation_line(vid, line.id, '사용자가 고친 한빛')
    core.request_refinement(vid)
    finish(core)
    assert core.translation(vid).lines[0].text == '사용자가 고친 한빛'
    assert core.review_lines(vid)[0].translation_reviewed
    with pytest.raises(ReviewConfirmationRequired):
        core.edit_transcript_line(vid, line.id, '새 원어')
    assert core.transcript(vid) == original
    core.edit_transcript_line(vid, line.id, '새 원어', keep_reviewed=True)
    assert core.translation_queue() == ()
    assert core.translation(vid).lines[0].text == '사용자가 고친 한빛'
    assert reopen().review_lines(vid)[0].translation_reviewed
    adapter.calls.clear()
    core.edit_transcript_line(vid, line.id, '다음 원어', overwrite_reviewed=True)
    finish(core)
    assert [[l.id for l in call[0]] for call in adapter.calls] == [[line.id]]
    assert core.translation(vid).lines[0].text == '다음 원어'
    assert not core.review_lines(vid)[0].translation_reviewed


@pytest.mark.parametrize('next_language', ['en', 'ko'])
def test_language_generation_replaces_results_reviews_and_job(refinement, next_language):
    core, _, _, _, reopen = refinement
    vid = core.videos()[0].id
    old = source(core, vid, 'ko' if next_language == 'en' else 'en')
    finish(core)
    core.edit_translation_line(vid, old.lines[0].id, '수정본')
    source(core, vid, next_language)
    assert core.translation(vid) is None
    assert core.reviewed_line_count(vid) == 0
    assert core.translation_queue()[0].kind == ('refinement' if next_language == 'ko' else 'translation')
    finish(core)
    assert not {l.id for l in old.lines} & {l.id for l in reopen().translation(vid).lines}


def test_hold_resume_cancel_and_stale_result_share_translation_contract(refinement):
    core, _, adapter, now, reopen = refinement
    vid = core.videos()[0].id
    original = source(core, vid)
    assert core.process_next_translation().completed_lines == 2

    def limited(*args):
        raise TranslationError('usage_limit', 'limit')
    adapter.action = limited
    assert core.process_next_translation().state == 'held'
    core = reopen()
    assert not core.translation_ready()
    now[0] += timedelta(minutes=16)
    def cancelled(*args):
        raise TranslationCancelled
    adapter.action = cancelled
    assert core.process_next_translation().completed_lines == 2
    assert core.translation_queue()[0].completed_lines == 2
    def stale(*args):
        core.edit_transcript_line(vid, original.lines[3].id, '바뀐 원어')
    adapter.action = stale
    assert core.process_next_translation() is None
    assert core.translation_queue()[0].completed_lines == 2
    adapter.action = None
    finish(core)
    assert core.translation(vid).lines[3].text == '바뀐 원어'


def test_range_replacement_deletes_old_refinement_and_only_processes_new_lines(refinement):
    core, transcriber, adapter, _, reopen = refinement
    vid = core.videos()[0].id
    old = source(core, vid)
    finish(core)
    core.edit_translation_line(vid, old.lines[0].id, '직접 수정')
    transcriber.result = TranscriberResult('ko', (TranscriptSegment(0, 1, '새로 할수 있어요'),))
    adapter.calls.clear()
    core.request_subtitle_range(vid, 0, 1)
    assert core.process_next_subtitle().state == 'completed'
    finish(core)
    result = reopen().translation(vid)
    assert result.lines[0].id != old.lines[0].id
    assert result.lines[0].text == '새로 할 수 있어요'
    assert [[l.id for l in c[0]] for c in adapter.calls] == [[result.lines[0].id]]
    assert not core.review_lines(vid)[0].translation_reviewed


@pytest.mark.parametrize('texts,ids', [([''], ['a']), (['  '], ['a']), (['음'], ['other']), ([], []), (['음', '어'], ['a', 'a'])])
def test_blank_filler_or_wrong_ids_are_format_errors(texts, ids):
    lines = (TranscriptLine('a', 0, 1, '음'),)
    with pytest.raises(TranslationError) as failure:
        parse_translation_response(json.dumps({'lines': [dict(id=i, text=t) for i, t in zip(ids, texts)]}), lines)
    assert failure.value.kind == 'format'
    assert parse_translation_response('{"lines":[{"id":"a","text":"음"}]}', lines)[0].text == '음'


def test_prompt_and_search_and_export_and_default_playback(refinement):
    core, _, _, _, _ = refinement
    vid = core.videos()[0].id
    original = source(core, vid)
    finish(core)
    prompt = translation_prompt(original.lines, 'ko')
    for requirement in ('띄어쓰기', '문장부호', '결재/결제', '군말', '감탄사', '의도적 반복', '줄 전체', '요약', '존댓말', '사투리', '확실하지'):
        assert requirement in prompt
    assert 'Translate subtitle data' in translation_prompt(original.lines, 'en')
    matches = core.search('한빛').results
    assert len(matches) == 5
    assert all(r.source == 'refinement' for r in matches)
    assert len(core.search('할수').results) == 5
    core.edit_translation_line(vid, original.lines[0].id, '한빛 결제 완료')
    matches = core.search('결제').results
    assert len(matches) == 1 and matches[0].source == 'refinement'
    raw = core.subtitle_export(vid)
    refined = core.subtitle_export(vid, translated=True)
    assert raw.default_path != refined.default_path
    assert '할수' in raw.text and '할 수' in refined.text
    core.playback.start(vid, 0)
    assert core.playback_subtitle_language == 'translated'
    assert '할 수' in core.playback_subtitle(vid).read_text(encoding='utf-8')
    assert core.toggle_subtitle_language()[0]
    assert '할수' in core.playback_subtitle(vid).read_text(encoding='utf-8')
    assert core.playback_subtitle_language == 'original'
    assert core.toggle_subtitle_language() == (True, core.subtitle_task(vid).subtitle_label)


def test_direct_refinement_precedes_automatic_and_cancel_discards_response(refinement):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    core, _, adapter, _, reopen = refinement
    a, b = core.videos()
    core.request_automatic_subtitles(a.id, 'ko')
    core.process_next_subtitle()
    core.request_automatic_subtitles(b.id, 'ko')
    core.process_next_subtitle()
    core.request_refinement(b.id)
    assert [e.video_id for e in core.translation_queue()] == [b.id, a.id]
    entered = Event()
    def blocked(lines, kwargs):
        entered.set()
        assert kwargs['cancellation'].wait(10)
        return TranslationResponse(tuple(TranslatedLine(l.id, '늦은 응답') for l in lines))
    adapter.action = blocked
    with ThreadPoolExecutor() as pool:
        work = pool.submit(core.process_next_translation)
        assert entered.wait(10)
        core.remove_from_subtitle_queue(b.id)
        work.result(10)
    adapter.action = None
    core = reopen()
    assert [e.video_id for e in core.translation_queue()] == [a.id]
    assert core.translation(b.id) is None
    finish(core)
    assert core.translation(a.id) is not None


def test_generation_change_during_refinement_drops_old_result(refinement):
    core, _, adapter, _, _ = refinement
    vid = core.videos()[0].id
    source(core, vid)
    def replace(lines, kwargs):
        source(core, vid, 'en')
        return TranslationResponse(tuple(TranslatedLine(l.id, '낡은 다듬기') for l in lines))
    adapter.action = replace
    assert core.process_next_translation() is None
    assert core.translation_queue()[0].kind == 'translation'
    assert core.translation_queue()[0].completed_lines == 0
    adapter.action = None
    finish(core)
    assert all(l.text != '낡은 다듬기' for l in core.translation(vid).lines)


def test_refinement_format_shrink_failure_retry_and_settings_snapshot(refinement):
    core, transcriber, adapter, _, reopen = refinement
    vid = core.videos()[0].id
    transcriber.result = TranscriberResult('ko', tuple(TranscriptSegment(i, i+1, '원어') for i in range(25)))
    # 공개 생성자 기본 묶음으로 실패 시 줄이기를 검사한다.
    core = AppCore(media=Media(), clock=lambda: datetime.now(timezone.utc), database=core.database,
                   transcriber=transcriber, translator=adapter)
    source(core, vid)
    def shrink(lines, kwargs):
        if len(lines) > 10:
            raise TranslationError('format', 'large batch')
    adapter.action = shrink
    assert core.process_next_translation().completed_lines == 10
    assert [len(call[0]) for call in adapter.calls] == [25, 12, 10]
    frozen = adapter.calls[-1][2]
    def timeout(lines, kwargs):
        raise TranslationError('timeout', 'timeout')
    adapter.action = timeout
    assert core.process_next_translation().state == 'failed'
    assert core.translation_queue()[0].completed_lines == 10
    core = reopen()
    core.request_refinement(vid)
    adapter.action = None
    finish(core)
    assert len(core.translation(vid).lines) == 25
    assert frozen['model'] == adapter.calls[-1][2]['model']


def test_reel_same_video_keeps_explicit_original_choice(refinement):
    core, _, _, _, _ = refinement
    vid = core.videos()[0].id
    source(core, vid)
    finish(core)
    from test_reel import mark
    mark(core, core.video(vid), 1)
    mark(core, core.video(vid), 5)
    core.start_reel()
    assert core.playback_subtitle_language == 'translated'
    core.toggle_subtitle_language()
    core.playback_subtitle(vid)
    from my_video_manager.core import Command, CommandType
    core.execute_highlight_command(Command(CommandType.NEXT_HIGHLIGHT))
    assert core.playback_subtitle_language == 'original'
    assert '할수' in core.playback_subtitle(vid).read_text(encoding='utf-8')


def test_bulk_skips_queued_completed_and_omitted_and_is_automatic(refinement):
    core, _, _, _, reopen = refinement
    a, b = core.videos()
    source(core, a.id)
    source(core, b.id)
    assert core.request_existing_refinements() == (0, 0)
    core.remove_from_subtitle_queue(a.id)
    assert core.existing_refinement_candidates() == (0, 1)
    assert core.request_existing_refinements() == (0, 1)
    finish(core)
    assert core.request_existing_refinements() == (0, 1)
    # 이주 전의 한국어 영상에는 omission이 없다.
    with sqlite3.connect(core.database) as db:
        db.execute('DELETE FROM translation_omissions')
    core = reopen()
    assert core.existing_refinement_candidates() == (1, 0)
    assert core.request_existing_refinements() == (1, 0)
    assert core.request_existing_refinements() == (0, 0)
    core.request_refinement(b.id)
    assert [e.video_id for e in core.translation_queue()] == [b.id, a.id]
    finish(core)
    assert core.request_existing_refinements() == (0, 0)


@pytest.mark.parametrize('text', ['', '  '])
def test_refinement_blank_response_keeps_original_and_translation_rejects(refinement, text):
    core, _, adapter, _, reopen = refinement
    a, b = core.videos()
    original = source(core, a.id)
    adapter.action = lambda lines, _: tuple(TranslatedLine(l.id, text) for l in lines)
    finish(core)
    assert reopen().translation(a.id).lines == original.lines
    source(core, b.id, 'en')
    assert core.process_next_translation().state == 'failed'
    assert core.translation(b.id) is None
    lines = (TranscriptLine('a', 0, 1, '음, 어…'),)
    payload = json.dumps({'lines': [{'id': 'a', 'text': text}]})
    assert parse_translation_response(payload, lines, spoken_language='ko')[0].text == '음, 어…'
    with pytest.raises(TranslationError):
        parse_translation_response(payload, lines, spoken_language='en')


@pytest.mark.parametrize('language,segments', [('und', (TranscriptSegment(0, 1, '음'),)), ('ko', ())])
def test_completed_without_result_is_transcription(refinement, language, segments):
    core, transcriber, _, _, _ = refinement
    transcriber.result = TranscriberResult(language, segments)
    vid = core.videos()[0].id
    source(core, vid, None)
    assert core.subtitle_queue_items()[0].task_label == '받아쓰기'


def test_error_message_does_not_rewrite_external_detail(refinement):
    core, _, adapter, _, _ = refinement
    source(core, core.videos()[0].id)
    def fail(*args):
        raise TranslationError('authentication', '서버 원문: 번역 CLI 인증 오류')
    adapter.action = fail
    result = core.process_next_translation()
    assert result.error == 'CLI 로그인이 필요합니다.'
    assert result.error_detail == '서버 원문: 번역 CLI 인증 오류'


from test_translation_connection import connected


def test_refinement_fallback_notice_and_progress_survive_restart(connected):
    core, http, cli, store, _, reopen = connected
    store.save('fake-key')
    vid = core.videos()[0].id
    transcript = source(core, vid, 'ko')
    assert core.process_next_translation().completed_lines == 2
    cli.error = TranslationError('usage_limit', 'limit')
    result = core.process_next_translation()
    assert result.completed_lines == 4
    assert 'OpenCode Go로 이어서 다듬기' in result.notice
    core = reopen()
    result = core.process_next_translation()
    assert result.state == 'completed'
    assert 'OpenCode Go로 이어서 다듬기' in result.notice
    assert len(cli.calls) == 2
    providers = core.translation_line_providers(vid)
    assert [providers[l.id] for l in transcript.lines] == ['codex'] * 2 + ['opencode_go'] * 3
    assert len(http.requests) == 2
