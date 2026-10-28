from contextlib import closing
import sqlite3
import zipfile

import pytest

from legacy_schema import replace_with_frozen, snapshot_rows
from my_video_manager.library import LIBRARY_DB_VERSION, migrate_library
from test_translation import setup, source


@pytest.mark.parametrize('version', [2, 3])
def test_fixed_old_schema_migrates_with_progress_and_pre_upgrade_backup(setup, tmp_path, version):
    core, _, _, _, reopen = setup
    video = core.videos()[0].id
    source(core, video)
    core.process_next_translation()
    replace_with_frozen(core.database, version)
    with closing(sqlite3.connect(core.database)) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        columns = {table: ','.join('"' + r[1] + '"' for r in db.execute(f'PRAGMA table_info("{table}")')) for table in tables}
        before = {t: snapshot_rows(db, columns[t], t) for t in tables}
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='translation_glossary'").fetchone()
    upgraded = reopen()
    archive, = upgraded.automatic_backups()
    assert upgraded.inspect_backup(archive).db_version == version
    with zipfile.ZipFile(archive) as saved:
        db_name = next(n for n in saved.namelist() if n.endswith('.sqlite3'))
        backup = tmp_path / 'before.sqlite3'
        backup.write_bytes(saved.read(db_name))
    for path, expected in ((backup, version), (core.database, LIBRARY_DB_VERSION)):
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == expected
            assert {t: snapshot_rows(db, columns[t], t) for t in tables} == before
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert upgraded.translation_queue()[0].completed_lines == 2
    assert upgraded.process_next_translation().completed_lines == 4
    assert reopen().automatic_backups() == (archive,)


@pytest.mark.parametrize('version', [2, 3])
def test_v4_ddl_failure_rolls_back_version_and_columns(setup, version):
    core, _, _, _, _ = setup
    replace_with_frozen(core.database, version)
    seen = []
    with closing(sqlite3.connect(core.database)) as db:
        before = db.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name').fetchall()
        def authorizer(action, name, *rest):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and name == 'translation_glossary' else sqlite3.SQLITE_OK
        db.set_authorizer(authorizer)
        with pytest.raises(sqlite3.DatabaseError), db:
            migrate_library(db, before_upgrade=lambda db, target: seen.append((db.in_transaction, target)))
        db.set_authorizer(lambda *args: sqlite3.SQLITE_OK)
        assert seen == [(False, LIBRARY_DB_VERSION)]
        assert db.execute('PRAGMA user_version').fetchone()[0] == version
        assert db.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name').fetchall() == before
