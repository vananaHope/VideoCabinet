"""고정된 과거 DDL로 DB를 만든다. 현재 코드의 열 삭제로 이전 버전을 흉내 내지 않는다."""
from collections import Counter
from contextlib import closing
from pathlib import Path
import sqlite3


def snapshot_rows(db, columns, table):
    """표의 행을 값과 중복 개수로 돌려준다. 행의 물리 순서는 스키마가 보증하지 않으며,
    이전이 AUTOINCREMENT 표를 다시 만들면 `sqlite_sequence`의 행 순서가 바뀐다."""
    if table == 'translation_glossary' and 'queue_id' in columns and any(
            row[1] == 'video_id' for row in db.execute('PRAGMA table_info(translation_glossary)')):
        return Counter(db.execute('SELECT q.id, g.source, g.target, g.ordinal FROM translation_glossary g '
                                  'JOIN translation_queue q ON q.video_id=g.video_id').fetchall())
    return Counter(db.execute(f'SELECT {columns} FROM "{table}"').fetchall())


def frozen_database(database, version, *, copy_from=None):
    schema = (Path(__file__).parent / 'fixtures' / f'library_v{version}.sql').read_text(encoding='utf-8')
    with closing(sqlite3.connect(database)) as db:
        db.executescript(schema)
        if copy_from is None:
            return
        # 테이블의 과거 열만 옮기고, FTS는 rowid를 포함해 복사한다. 트리거 이중 실행을 막는다.
        triggers = db.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'").fetchall()
        for name, _ in triggers:
            db.execute(f'DROP TRIGGER "{name}"')
        db.execute('ATTACH DATABASE ? AS original', (str(copy_from),))
        tables = [(row[1], row[2]) for row in db.execute('PRAGMA main.table_list')
                  if row[2] in ('table', 'virtual') and not row[1].startswith('sqlite_')]
        for name, kind in tables:
            columns = ', '.join('"' + row[1] + '"' for row in db.execute(f'PRAGMA main.table_info("{name}")'))
            if kind == 'virtual':
                columns = 'rowid, ' + columns
            if name == 'translation_glossary' and any(
                    row[1] == 'video_id' for row in db.execute('PRAGMA original.table_info(translation_glossary)')):
                db.execute('INSERT INTO main.translation_glossary SELECT q.id, g.source, g.target, g.ordinal '
                           "FROM original.translation_glossary g JOIN original.translation_queue q ON q.video_id=g.video_id WHERE q.source='transcript'")
            elif name in ('translation_lines', 'translation_line_providers', 'translation_queue', 'translation_omissions'):
                db.execute(f'INSERT INTO main."{name}" ({columns}) SELECT {columns} FROM original."{name}" '
                           "WHERE source='transcript'")
            elif name.startswith('translation_') and '"queue_id"' in columns:
                db.execute(f'INSERT INTO main."{name}" ({columns}) SELECT {columns} FROM original."{name}" '
                           "WHERE queue_id IN (SELECT id FROM original.translation_queue WHERE source='transcript')")
            else:
                db.execute(f'INSERT INTO main."{name}" ({columns}) SELECT {columns} FROM original."{name}"')
        for _, sql in triggers:
            db.execute(sql)
        db.commit()


def replace_with_frozen(database, version):
    replacement = database.with_name(f'frozen-v{version}.sqlite3')
    frozen_database(replacement, version, copy_from=database)
    replacement.replace(database)
