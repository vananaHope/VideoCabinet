"""작업 종류와 v5 이전을 공개 대기열·백업·검수 결과로 확인한다."""
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from legacy_schema import replace_with_frozen
from my_video_manager.backup import create_backup
from my_video_manager.core import AppCore
from my_video_manager.library import migrate_library
from my_video_manager.subtitle_queue import QueueOrder, SubtitleQueue, SubtitleQueueItem
from my_video_manager.subtitle_queue_kind import TRANSCRIPTION
from my_video_manager.web_queue_data import row_data
from test_backup import apply
from test_review import Transcriber
from test_subtitles import FakeMedia, NOW, reopen, setup


def connection_factory(database):
    @contextmanager
    def connect():
        with closing(sqlite3.connect(database)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            yield db
    return connect


def test_order_priority_and_promotion_are_per_video_and_kind(setup):
    core, _, (a, b) = setup
    connect = connection_factory(core.database)
    order = QueueOrder(connect)
    direct = SubtitleQueueItem(a.id, a.title, "queued", 0)
    other = replace(direct, queue_kind="test-kind")
    automatic = replace(direct, video_id=b.id)
    with connect() as db:
        order.request(db, a.id, kind=other.queue_kind, automatic=True)
        order.request(db, b.id, automatic=True)
        order.request(db, a.id)
    assert order.sort((other, automatic, direct)) == (direct, other, automatic)
    order.promote(a.id, kind=other.queue_kind)
    assert order.sort((direct, automatic, other)) == (other, direct, automatic)
    with connect() as db:
        order.request(db, a.id)  # 같은 종류의 중복 요청은 기존 순서를 유지한다.
    assert QueueOrder(connect).sort((direct, automatic, other)) == (other, direct, automatic)


def test_pending_kinds_coexist_at_public_queue_boundary(setup, monkeypatch):
    core, _, (a, _) = setup
    original = core.request_subtitles(a.id)
    other = replace(original, id=original.id + 1, queue_kind="test-kind")
    connect = connection_factory(core.database)
    order = QueueOrder(connect)
    with connect() as db:
        order.request(db, a.id, kind=other.queue_kind, automatic=True)
    # 다음 종류의 처리 모듈을 공개 조회 경계에서 대역으로 제공한다.
    # 실제 DB에는 영상·순서·숨김을 사용하며 시험용 저장/실행기는 제품에 넣지 않는다.
    monkeypatch.setattr(core, "subtitle_queue", lambda *, kind=TRANSCRIPTION:
                        tuple(e for e in (original, other) if kind is None or e.queue_kind == kind))
    queue = SubtitleQueue(core, order)
    assert [(e.video_id, e.queue_kind, e.state) for e in queue.items()] == [
        (a.id, TRANSCRIPTION, "queued"), (a.id, other.queue_kind, "queued")]
    queue.hide(a.id, kind=other.queue_kind)
    assert [(e.video_id, e.queue_kind) for e in queue.items()] == [(a.id, TRANSCRIPTION)]
    with connect() as db:
        order.request(db, a.id, kind=other.queue_kind)
    assert len(queue.items()) == 2


def test_completion_and_hidden_records_are_per_video_and_kind(setup):
    core, adapter, (a, _) = setup
    adapter.result = replace(adapter.result, segments=())
    core.request_subtitles(a.id)
    completed = core.process_next_subtitle()
    other = replace(completed, queue_kind="test-kind", no_speech=False)
    connect = connection_factory(core.database)
    order = QueueOrder(connect)
    queue = SubtitleQueue(core, order)
    queue.record(completed)
    queue.record(other)
    assert {e.queue_kind for e in queue.items()} == {TRANSCRIPTION, other.queue_kind}
    assert queue.take_completion() == (1, 0, 1)
    assert queue.take_completion() is None
    queue.record(completed)
    queue.record(other)
    queue.hide(a.id, kind=other.queue_kind)
    assert [e.queue_kind for e in queue.items()] == [TRANSCRIPTION]
    assert queue.take_completion() == (0, 0, 1)
    queue.record(other)  # 숨긴 종류의 늦은 완료는 다시 나타나지 않는다.
    assert queue.take_completion() is None
    with connect() as db:
        order.request(db, a.id, kind=other.queue_kind, renew=True)
    queue.record(other)
    assert queue.take_completion() == (1, 0, 0)


def test_v5_hidden_completion_remains_hidden_after_migration(setup):
    core, adapter, (a, _) = setup
    adapter.result = replace(adapter.result, segments=())
    core.request_subtitles(a.id)
    completed = core.process_next_subtitle()
    core.remove_from_subtitle_queue(a.id)
    replace_with_frozen(core.database, 5)
    core = reopen(core, adapter)
    queue = SubtitleQueue(core, QueueOrder(connection_factory(core.database)))
    queue.record(completed)
    assert queue.items() == ()
    assert queue.take_completion() is None
    core.request_subtitles(a.id)
    assert len(core.subtitle_queue_items()) == 1


def test_v5_migration_preserves_pending_failed_order_and_backup(setup, tmp_path):
    core, adapter, (a, b) = setup
    adapter.error = RuntimeError("saved failure")
    core.request_subtitles(a.id, "ja")
    core.process_next_subtitle()
    core.request_automatic_subtitles(b.id, "en")
    core.promote_subtitle(b.id)
    expected = core.subtitle_queue()
    expected_rows = core.subtitle_queue_items()
    replace_with_frozen(core.database, 5)

    migrated = reopen(core, adapter)
    assert migrated.subtitle_queue() == expected
    assert migrated.subtitle_queue_items() == expected_rows
    assert all(e.queue_kind == TRANSCRIPTION for e in migrated.subtitle_queue())
    backup, = migrated.automatic_backups()
    assert migrated.inspect_backup(backup).db_version == 5
    assert migrated.create_backup(tmp_path / "v6.zip").metadata.db_version == 6
    assert reopen(migrated, adapter).subtitle_queue() == expected
    assert len(migrated.automatic_backups()) == 1
    assert migrated.retry_failed_subtitles().retried == 1
    assert [e.video_id for e in migrated.subtitle_queue()] == [b.id, a.id]


def test_v5_migration_keeps_range_retry_and_deleted_request_ids(setup):
    core, _, (a, b) = setup
    adapter = Transcriber()
    core = reopen(core, adapter)
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    core.request_subtitle_range(a.id, 10, 12)
    adapter.error = RuntimeError("range failure")
    core.process_next_subtitle()
    failed, = core.subtitle_queue()
    discarded = core.request_subtitles(b.id)
    core.remove_from_subtitle_queue(b.id)
    replace_with_frozen(core.database, 5)
    # frozen 복사는 살아 있는 행만 옮기므로, v5에서 지운 요청의 마지막 id도 준비한다.
    with closing(sqlite3.connect(core.database)) as db, db:
        db.execute("UPDATE sqlite_sequence SET seq=? WHERE name='subtitle_queue'", (discarded.id,))

    migrated = reopen(core, adapter)
    assert migrated.subtitle_queue() == (failed,)
    assert migrated.retry_failed_subtitles().retried == 1
    adapter.error = None
    result = migrated.process_next_subtitle()
    assert result.state == "completed", result
    assert adapter.calls[-1]["start"] == 10
    assert adapter.calls[-1]["duration"] == 2
    assert migrated.request_subtitles(b.id).id > discarded.id


@pytest.mark.parametrize("version", [5, 6])
def test_queue_survives_backup_restore_roundtrip(setup, tmp_path, version):
    core, adapter, (a, b) = setup
    adapter.error = RuntimeError("saved failure")
    core.request_subtitles(a.id)
    core.process_next_subtitle()
    core.request_automatic_subtitles(b.id)
    core.promote_subtitle(b.id)
    expected = core.subtitle_queue()
    if version == 5:
        replace_with_frozen(core.database, 5)
    archive = create_backup(core.database, tmp_path / "queue.zip")
    assert archive.metadata.db_version == version
    core = reopen(core, adapter)
    core.remove_from_subtitle_queue(a.id)
    core.remove_from_subtitle_queue(b.id)
    core.request_backup_restore(archive.path)
    assert apply(core.database).status == "applied"
    restored = reopen(core, adapter)
    assert restored.subtitle_queue() == expected
    assert restored.create_backup(tmp_path / "restored.zip").metadata.db_version == 6


def test_v5_migration_failure_rolls_back_and_can_retry(setup):
    core, adapter, (a, _) = setup
    core.request_subtitles(a.id)
    expected = core.subtitle_queue()
    replace_with_frozen(core.database, 5)
    before = core.database.read_bytes()
    with closing(sqlite3.connect(core.database)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        # 마지막 테이블의 ALTER를 거절해 앞서 수행한 DDL·복사도 되돌려야 한다.
        db.set_authorizer(lambda action, first, second, *_:
                          sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_ALTER_TABLE
                          and second == "subtitle_queue_hidden_v6" else sqlite3.SQLITE_OK)
        with pytest.raises(sqlite3.DatabaseError):
            migrate_library(db)
        db.set_authorizer(lambda *_: sqlite3.SQLITE_OK)
        assert not db.in_transaction
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert core.database.read_bytes() == before
    assert reopen(core, adapter).subtitle_queue() == expected


@pytest.mark.parametrize("existing_tables", [False, True])
def test_v5_empty_queue_schema_and_repeated_open(tmp_path, existing_tables):
    database = tmp_path / "library.sqlite3"
    fixture = "library_v5.sql" if existing_tables else "library_v4_without_subtitles.sql"
    with closing(sqlite3.connect(database)) as db:
        db.executescript((Path(__file__).parent / "fixtures" / fixture).read_text(encoding="utf-8"))
        db.execute("PRAGMA user_version=5")
    for _ in range(2):
        core = AppCore(database=database, media=FakeMedia(), clock=lambda: NOW)
        assert core.subtitle_queue_items() == ()
    assert core.create_backup(tmp_path / "empty.zip").metadata.db_version == 6


@pytest.mark.parametrize("language,stage", [("en", "translation"), ("ko", "refinement")])
def test_translation_stage_keeps_transcription_queue_kind(setup, language, stage):
    core, _, (a, _) = setup
    core.request_subtitles(a.id, language)
    core.process_next_subtitle()
    entry, = core.translation_queue()
    assert entry.kind == stage
    assert entry.queue_kind == TRANSCRIPTION
    item, = core.subtitle_queue_items()
    assert item.queue_kind == TRANSCRIPTION
    assert row_data(item)["queueKind"] == TRANSCRIPTION
