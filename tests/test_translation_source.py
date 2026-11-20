"""출처 격리는 공개 경계로, 이전의 참조 보장은 저장된 행과 직접 SQL로 확인한다."""
from collections import Counter
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys

import pytest

from legacy_schema import replace_with_frozen, snapshot_rows
from my_video_manager.backup import create_backup
from my_video_manager.core import AppCore
from my_video_manager.library import LIBRARY_DB_VERSION, migrate_library
from my_video_manager.subtitles import TranscriptLine
from my_video_manager.translation import TranslationError, TranslatedLine
from my_video_manager.translation_source import TRANSCRIPT, TranslationSourceLines
from test_backup import apply
from test_translation import setup, source, finish, Media
from test_translation_quality import RecordingTranslator
from test_translation_connection import connected


OTHER = 'test-only-source'
OTHER_KIND = 'test-only-kind'


def register(core, video_id, lines):
    bundle = TranslationSourceLines('test-generation', video_id, 'ja', tuple(
        replace(line, text='Separate ' + line.text) for line in lines))
    core.register_translation_source(OTHER, read_lines=lambda vid, *, connection=None: bundle if vid == video_id else None,
                                     queue_kind=OTHER_KIND)
    return bundle


def test_sources_with_identical_line_ids_coexist_resume_and_keep_results(setup):
    core, _, adapter, _, reopen = setup
    video = core.videos()[0].id
    original = source(core, video)
    bundle = register(core, video, original.lines)
    other = core.request_translation(video, source=OTHER)
    assert {(e.source, e.queue_kind) for e in core.translation_queue()} == {
        (TRANSCRIPT, 'transcription'), (OTHER, OTHER_KIND)}
    assert {e.queue_kind for e in core.subtitle_queue_items()} == {'transcription', OTHER_KIND}
    assert core.process_next_translation().completed_lines == 2
    # 둘째 출처가 원어 쪽 진행, 보호 상태 또는 문맥을 읽지 않는다.
    core.promote_subtitle(video, kind=OTHER_KIND)
    assert core.process_next_translation().source == OTHER
    assert core.translation(video, source=OTHER) is None
    core = reopen()
    register(core, video, original.lines)
    assert {e.source: e.completed_lines for e in core.translation_queue()} == {TRANSCRIPT: 2, OTHER: 2}
    finish(core)
    assert [l.text for l in core.translation(video).lines] == ['번역 ' + l.text for l in original.lines]
    assert [l.text for l in core.translation(video, source=OTHER).lines] == ['번역 ' + l.text for l in bundle.lines]
    assert core.translation(video, source=OTHER).source == OTHER
    assert set(core.translation_line_providers(video, source=OTHER).values()) == {'codex'}
    before = core.translation(video, source=OTHER)
    core.edit_translation_line(video, original.lines[0].id, '사용자 수정')
    core.request_translation(video, [original.lines[0].id], source=OTHER)
    assert core.process_next_translation().state == 'completed'
    assert core.translation(video).lines[0].text == '사용자 수정'
    assert core.translation(video, source=OTHER) == before
    assert not core.search('Separate').results
    with pytest.raises(ValueError):
        core.request_translation(video, ['missing-line'], source=OTHER)
    assert other.source == OTHER


@pytest.mark.parametrize('removed', [TRANSCRIPT, OTHER])
def test_removal_cancels_only_matching_source_and_keeps_other_work(setup, removed):
    core, _, adapter, _, _ = setup
    video = core.videos()[0].id
    original = source(core, video)
    register(core, video, original.lines)
    core.request_translation(video, source=OTHER)
    kind = 'transcription' if removed == TRANSCRIPT else OTHER_KIND
    retained = OTHER if removed == TRANSCRIPT else TRANSCRIPT
    core.remove_from_subtitle_queue(video, kind=kind)
    assert [e.source for e in core.translation_queue()] == [retained]
    finish(core)
    assert core.translation(video, source=retained) is not None
    assert core.translation(video, source=removed) is None


def test_fake_source_without_transcript_and_failed_retry_are_independent(setup):
    core, _, adapter, _, _ = setup
    video = core.videos()[0].id
    register(core, video, (TranscriptLine('independent', 1, 2, 'text'),))
    core.request_translation(video, source=OTHER)
    core.request_subtitles(video)  # 원어 작업은 다른 출처의 번역을 막지 않는다.
    adapter.error = TranslationError('missing_cli', 'test')
    assert core.process_next_translation().state == 'failed'
    assert core.retry_failed_subtitles().retried == 0
    assert core.retry_failed_subtitles(kind=OTHER_KIND).retried == 1
    adapter.error = None
    assert core.process_next_translation().state == 'completed'
    assert core.translation(video, source=OTHER).lines[0].text == '번역 Separate text'
    assert core.translation(video) is None
    assert core.review_lines(video) == ()


@pytest.mark.parametrize('language', ['en', 'ko'])
@pytest.mark.parametrize('archive_version', [6, LIBRARY_DB_VERSION])
def test_migration_and_backup_keep_results_reviews_progress_providers_glossary(setup, tmp_path, language, archive_version):
    _, transcriber, _, _, reopen = setup
    adapter = RecordingTranslator()
    core = reopen(adapter)
    a, b = core.videos()
    original = source(core, a.id, language)
    finish(core)
    core.edit_translation_line(a.id, original.lines[0].id, '보호된 수정본')
    source(core, b.id, language)
    assert core.process_next_translation().completed_lines == 2
    expected = (core.translation(a.id), core.review_lines(a.id), core.translation_line_providers(a.id),
                core.translation_queue(), core.translation_line_providers(b.id))
    if archive_version == 6:
        replace_with_frozen(core.database, 6)
    archive = create_backup(core.database, tmp_path / 'saved.zip')
    assert archive.metadata.db_version == archive_version
    core = reopen(adapter)
    assert (core.translation(a.id), core.review_lines(a.id), core.translation_line_providers(a.id),
            core.translation_queue(), core.translation_line_providers(b.id)) == expected
    if archive_version == 6:
        automatic, = core.automatic_backups()
        assert core.inspect_backup(automatic).db_version == 6
    core.remove_from_subtitle_queue(b.id)
    core.edit_translation_line(a.id, original.lines[0].id, '복원 전 변경')
    core.request_backup_restore(archive.path)
    assert apply(core.database).status == 'applied'
    restored = reopen(adapter)
    assert (restored.translation(a.id), restored.review_lines(a.id), restored.translation_line_providers(a.id),
            restored.translation_queue(), restored.translation_line_providers(b.id)) == expected
    assert restored.create_backup(tmp_path / 'restored.zip').metadata.db_version == LIBRARY_DB_VERSION
    assert restored.process_next_translation().completed_lines == 4
    assert [(entry.source, entry.target) for entry in adapter.calls[-1][1]['glossary']] == [('Jon', '존')]
    assert len(adapter.calls[-1][0]) == 2
    finish(restored)
    restored.request_translation(a.id)
    finish(restored)
    assert restored.translation(a.id).lines[0].text == '보호된 수정본'


def test_v6_migration_preserves_all_old_columns_and_rolls_back_failure(setup):
    core, _, _, _, reopen = setup
    video = core.videos()[0].id
    source(core, video)
    core.process_next_translation()
    expected = core.translation_queue()
    replace_with_frozen(core.database, 6)
    before_bytes = core.database.read_bytes()
    with closing(sqlite3.connect(core.database)) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        columns = {table: ','.join('"' + r[1] + '"' for r in db.execute(f'PRAGMA table_info("{table}")')) for table in tables}
        before = {table: snapshot_rows(db, columns[table], table) for table in tables}
        db.execute('PRAGMA foreign_keys=ON')
        db.set_authorizer(lambda action, first, second, *_: sqlite3.SQLITE_DENY
                          if action == sqlite3.SQLITE_ALTER_TABLE and second == 'translation_omissions_v7'
                          else sqlite3.SQLITE_OK)
        with pytest.raises(sqlite3.DatabaseError):
            migrate_library(db)
        db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert not db.in_transaction
        assert db.execute('PRAGMA user_version').fetchone()[0] == 6
    assert core.database.read_bytes() == before_bytes
    core = reopen()
    assert core.translation_queue() == expected
    with closing(sqlite3.connect(core.database)) as db:
        assert {table: snapshot_rows(db, columns[table], table) for table in tables} == before
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert reopen().translation_queue() == expected


def translation_rows(database, video_id, source):
    """현재 원어 줄과 조인하지 않아 삭제 후 숨겨진 고아 행도 스냅숏에 포함한다."""
    with closing(sqlite3.connect(database)) as db:
        rows = {table: Counter(db.execute(
            f"SELECT * FROM {table} WHERE video_id=? AND source=?", (video_id, source)).fetchall())
            for table in ('translation_lines', 'translation_line_providers')}
        rows['translation_targets'] = Counter(db.execute(
            "SELECT g.* FROM translation_targets g JOIN translation_queue q ON q.id=g.queue_id "
            "WHERE q.video_id=? AND q.source=?", (video_id, source)).fetchall())
        return rows


def assert_no_orphan_transcript_references(database, video_id):
    with closing(sqlite3.connect(database)) as db:
        for table in ('translation_lines', 'translation_line_providers'):
            assert db.execute(
                f"SELECT COUNT(*) FROM {table} g WHERE g.video_id=? AND g.source=? "
                "AND NOT EXISTS (SELECT 1 FROM transcript_lines l WHERE l.id=g.line_id)",
                (video_id, TRANSCRIPT)).fetchone()[0] == 0, table
        assert db.execute(
            "SELECT COUNT(*) FROM translation_targets g JOIN translation_queue q ON q.id=g.queue_id "
            "WHERE q.video_id=? AND q.source=? "
            "AND NOT EXISTS (SELECT 1 FROM transcript_lines l WHERE l.id=g.line_id)",
            (video_id, TRANSCRIPT)).fetchone()[0] == 0, 'translation_targets'


@pytest.mark.parametrize('migrated', [False, True], ids=['new-v7', 'v6-to-v7'])
@pytest.mark.parametrize('table', ['translation_lines', 'translation_line_providers', 'translation_targets'])
@pytest.mark.parametrize('operation', ['insert', 'update'])
def test_transcript_references_reject_missing_line(setup, migrated, table, operation):
    core, _, _, _, reopen = setup
    video = core.videos()[0].id
    original = source(core, video)
    finish(core)
    pending = core.request_translation(video)
    if migrated:
        replace_with_frozen(core.database, 6)
        core = reopen()
    before = translation_rows(core.database, video, TRANSCRIPT)
    assert all(len(rows) == len(original.lines) for rows in before.values())
    missing = 'missing-transcript-line'
    assert missing not in {line.id for line in original.lines}
    with closing(sqlite3.connect(core.database)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError):
            if operation == 'insert':
                if table == 'translation_targets':
                    db.execute('INSERT INTO translation_targets(queue_id, line_id, text) VALUES (?, ?, ?)',
                               (pending.id, missing, 'invalid'))
                else:
                    value_column = 'text' if table == 'translation_lines' else 'provider'
                    db.execute(f'INSERT INTO {table}(line_id, {value_column}, video_id, source) VALUES (?, ?, ?, ?)',
                               (missing, 'invalid', video, TRANSCRIPT))
            elif table == 'translation_targets':
                assert db.execute('UPDATE translation_targets SET line_id=? WHERE queue_id=? AND line_id=?',
                                  (missing, pending.id, original.lines[0].id)).rowcount == 1
            else:
                assert db.execute(f'UPDATE {table} SET line_id=? WHERE video_id=? AND source=? AND line_id=?',
                                  (missing, video, TRANSCRIPT, original.lines[0].id)).rowcount == 1
    assert translation_rows(core.database, video, TRANSCRIPT) == before


@pytest.mark.parametrize('mode', ['range', 'regenerate'])
def test_migrated_original_deletion_cleans_only_original_translation(setup, mode):
    core, transcriber, _, _, reopen = setup
    video = core.videos()[0].id
    original = source(core, video)
    finish(core)
    replace_with_frozen(core.database, 6)
    core = reopen()
    register(core, video, original.lines)
    core.request_translation(video, source=OTHER)
    finish(core)
    saved = core.translation(video, source=OTHER)
    # 확정 결과·방식과 재번역 대상이 양쪽 출처에 모두 있는 상태에서 삭제한다.
    core.request_translation(video)
    core.request_translation(video, source=OTHER)
    original_rows = translation_rows(core.database, video, TRANSCRIPT)
    other_rows = translation_rows(core.database, video, OTHER)
    assert all(len(rows) == len(original.lines) for rows in original_rows.values())
    assert all(len(rows) == len(original.lines) for rows in other_rows.values())
    old_id = original.lines[0].id
    if mode == 'range':
        core.request_subtitle_range(video, 0, 1)
        transcriber.result = replace(transcriber.result, segments=())
    else:
        core.request_subtitles(video)
    assert core.process_next_subtitle().state == 'completed'
    assert old_id not in {line.original.id for line in core.review_lines(video)}
    assert_no_orphan_transcript_references(core.database, video)
    assert translation_rows(core.database, video, OTHER) == other_rows
    assert core.translation(video, source=OTHER) == saved
    finish(core)
    assert core.translation(video, source=OTHER) == saved
    assert_no_orphan_transcript_references(core.database, video)


@pytest.mark.parametrize('with_tables', [False, True])
def test_v6_empty_library_migrates_and_reopens(setup, tmp_path, with_tables):
    core, _, _, _, reopen = setup
    if with_tables:
        replace_with_frozen(core.database, 6)
    else:
        database = tmp_path / 'empty.sqlite3'
        with closing(sqlite3.connect(database)) as db:
            db.executescript((Path(__file__).parent / 'fixtures/library_v4_without_subtitles.sql').read_text(encoding='utf-8'))
            db.execute('PRAGMA user_version=6')
        reopen = lambda: AppCore(media=Media(), clock=lambda: None, database=database)
    for _ in range(2):
        current = reopen()
        assert current.translation_queue() == ()
    assert current.create_backup(tmp_path / 'empty.zip').metadata.db_version == LIBRARY_DB_VERSION


@pytest.mark.parametrize('active_source', [TRANSCRIPT, OTHER])
def test_removing_other_source_does_not_cancel_running_batch(setup, active_source):
    core, _, adapter, _, _ = setup
    video = core.videos()[0].id
    original = source(core, video)
    register(core, video, original.lines)
    core.request_translation(video, source=OTHER)
    active_kind = 'transcription' if active_source == TRANSCRIPT else OTHER_KIND
    removed_kind = OTHER_KIND if active_source == TRANSCRIPT else 'transcription'
    core.promote_subtitle(video, kind=active_kind)

    def response(lines):
        core.remove_from_subtitle_queue(video, kind=removed_kind)
        return tuple(TranslatedLine(line.id, 'kept ' + line.text) for line in lines)

    adapter.response = response
    result = core.process_next_translation()
    assert result.source == active_source and result.completed_lines == 2
    assert [entry.source for entry in core.translation_queue()] == [active_source]
    adapter.response = None
    finish(core)
    assert core.translation(video, source=active_source) is not None


def test_pending_targets_reviews_and_context_are_scoped_to_source(setup):
    _, _, _, _, reopen = setup
    adapter = RecordingTranslator()
    core = reopen(adapter)
    video = core.videos()[0].id
    original = source(core, video)
    finish(core)
    register(core, video, original.lines)
    core.request_translation(video, [original.lines[3].id], source=OTHER)
    core.process_next_translation()
    context = adapter.calls[-1][1]['context']
    assert len(context) == 3
    assert all(line.text.startswith('Separate ') and line.translation is None for line in context)
    core.request_translation(video, source=OTHER)
    pending = next(e for e in core.translation_queue() if e.source == OTHER)
    core.edit_translation_line(video, original.lines[0].id, 'protected original')
    assert next(e for e in core.translation_queue() if e.source == OTHER) == pending
    finish(core)
    assert core.translation(video).lines[0].text == 'protected original'
    assert core.translation(video, source=OTHER).lines[0].text.startswith('번역 Separate ')


@pytest.mark.usefixtures('portable_dpapi')
def test_v6_fallback_route_and_per_line_providers_resume_after_migration(connected):
    core, http, cli, store, _, reopen = connected
    store.save('fake-key')
    video = core.videos()[0].id
    original = source(core, video)
    assert core.process_next_translation().completed_lines == 2
    cli.error = TranslationError('usage_limit', 'limit')
    held = core.process_next_translation()
    assert held.completed_lines == 4 and 'OpenCode Go' in held.notice
    expected = core.translation_queue()
    replace_with_frozen(core.database, 6)
    core = reopen()
    assert core.translation_queue() == expected
    result = core.process_next_translation()
    assert result.state == 'completed' and result.notice == held.notice
    providers = core.translation_line_providers(video)
    assert [providers[line.id] for line in original.lines] == ['codex'] * 2 + ['opencode_go'] * 3
    assert len(cli.calls) == 2 and len(http.requests) == 2
