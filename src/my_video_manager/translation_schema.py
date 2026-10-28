"""번역 출처 저장 구조와 원어 자막 참조 보장. 이전과 최초 생성이 공유한다."""

from .translation_source import TRANSCRIPT


SOURCE_TABLES = {
    "translation_lines": """line_id TEXT NOT NULL, text TEXT NOT NULL,
        video_id INTEGER NOT NULL REFERENCES videos(id), source TEXT NOT NULL,
        PRIMARY KEY(video_id, source, line_id)""",
    "translation_queue": """id TEXT PRIMARY KEY,
        video_id INTEGER NOT NULL REFERENCES videos(id), transcript_id TEXT NOT NULL,
        requested_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', retry_at TEXT,
        error_kind TEXT, error_detail TEXT, source TEXT NOT NULL, spoken_language TEXT,
        UNIQUE(video_id, source)""",
    "translation_targets": """queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
        line_id TEXT NOT NULL, text TEXT, PRIMARY KEY(queue_id, line_id)""",
    "translation_line_providers": """line_id TEXT NOT NULL, provider TEXT NOT NULL,
        video_id INTEGER NOT NULL REFERENCES videos(id), source TEXT NOT NULL,
        PRIMARY KEY(video_id, source, line_id)""",
    "translation_omissions": """transcript_id TEXT NOT NULL,
        video_id INTEGER NOT NULL REFERENCES videos(id), source TEXT NOT NULL,
        PRIMARY KEY(video_id, source)""",
}


def create_source_tables(db):
    for table, schema in SOURCE_TABLES.items():
        db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({schema})")


def install_transcript_references(db):
    for table in ("translation_lines", "translation_line_providers"):
        db.execute(f"CREATE INDEX IF NOT EXISTS {table}_source_line ON {table}(source, line_id)")
    db.execute("CREATE INDEX IF NOT EXISTS translation_targets_line ON translation_targets(line_id)")
    # SQLite의 트리거 DDL은 바인딩을 지원하지 않는다. 제품 상수 하나만 사용한다.
    # 실행 SQL과 이전의 데이터 복사는 모두 매개변수로 출처를 전달한다.
    for table in ("translation_lines", "translation_line_providers"):
        for event in ("INSERT", "UPDATE"):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_transcript_{event.lower()}
                BEFORE {event} ON {table} WHEN new.source='{TRANSCRIPT}'
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l JOIN transcripts t ON t.id=l.transcript_id
                    WHERE l.id=new.line_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript line'); END""")
    for table in ("translation_queue", "translation_omissions"):
        for event in ("INSERT", "UPDATE"):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_transcript_{event.lower()}
                BEFORE {event} ON {table} WHEN new.source='{TRANSCRIPT}'
                AND NOT EXISTS (SELECT 1 FROM transcripts t
                    WHERE t.id=new.transcript_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript generation'); END""")
    for event in ("INSERT", "UPDATE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS translation_targets_transcript_{event.lower()}
            BEFORE {event} ON translation_targets
            WHEN EXISTS (SELECT 1 FROM translation_queue q WHERE q.id=new.queue_id AND q.source='{TRANSCRIPT}'
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l
                    WHERE l.id=new.line_id AND l.transcript_id=q.transcript_id))
            BEGIN SELECT RAISE(ABORT, 'invalid transcript target'); END""")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS translation_transcript_line_delete
        AFTER DELETE ON transcript_lines BEGIN
        DELETE FROM translation_lines WHERE source='{TRANSCRIPT}' AND line_id=old.id;
        DELETE FROM translation_line_providers WHERE source='{TRANSCRIPT}' AND line_id=old.id;
        DELETE FROM translation_targets WHERE line_id=old.id AND queue_id IN
            (SELECT id FROM translation_queue WHERE source='{TRANSCRIPT}'); END""")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS translation_transcript_delete
        AFTER DELETE ON transcripts BEGIN
        DELETE FROM translation_queue WHERE source='{TRANSCRIPT}' AND transcript_id=old.id;
        DELETE FROM translation_omissions WHERE source='{TRANSCRIPT}' AND transcript_id=old.id; END""")
    # 원래 FK의 ON UPDATE NO ACTION도 유지한다. 부모 ID 변경으로 고아 참조를 만들 수 없다.
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS translation_transcript_line_identity
        BEFORE UPDATE OF id ON transcript_lines WHEN new.id != old.id AND (
            EXISTS (SELECT 1 FROM translation_lines WHERE source='{TRANSCRIPT}' AND line_id=old.id)
            OR EXISTS (SELECT 1 FROM translation_line_providers WHERE source='{TRANSCRIPT}' AND line_id=old.id)
            OR EXISTS (SELECT 1 FROM translation_targets g JOIN translation_queue q ON q.id=g.queue_id
                WHERE q.source='{TRANSCRIPT}' AND g.line_id=old.id))
        BEGIN SELECT RAISE(ABORT, 'referenced transcript line'); END""")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS translation_transcript_identity
        BEFORE UPDATE OF id ON transcripts WHEN new.id != old.id AND (
            EXISTS (SELECT 1 FROM translation_queue WHERE source='{TRANSCRIPT}' AND transcript_id=old.id)
            OR EXISTS (SELECT 1 FROM translation_omissions WHERE source='{TRANSCRIPT}' AND transcript_id=old.id))
        BEGIN SELECT RAISE(ABORT, 'referenced transcript generation'); END""")


def migrate_translation_sources(db):
    """호출자가 FK를 끈 트랜잭션과 자동 백업·롤백을 소유한다."""
    copies = {
        "translation_lines": "SELECT l.line_id, l.text, t.video_id, ? FROM translation_lines l "
                             "JOIN transcript_lines o ON o.id=l.line_id JOIN transcripts t ON t.id=o.transcript_id",
        "translation_queue": "SELECT q.id, q.video_id, q.transcript_id, q.requested_at, q.state, "
                             "q.retry_at, q.error_kind, q.error_detail, ?, t.spoken_language "
                             "FROM translation_queue q JOIN transcripts t ON t.id=q.transcript_id",
        "translation_targets": "SELECT queue_id, line_id, text FROM translation_targets",
        "translation_line_providers": "SELECT l.line_id, l.provider, t.video_id, ? FROM translation_line_providers l "
                                      "JOIN transcript_lines o ON o.id=l.line_id JOIN transcripts t ON t.id=o.transcript_id",
        "translation_omissions": "SELECT o.transcript_id, t.video_id, ? FROM translation_omissions o "
                                 "JOIN transcripts t ON t.id=o.transcript_id",
    }
    for table, schema in SOURCE_TABLES.items():
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        db.execute(f"CREATE TABLE {table}_v7 ({schema})")
        db.execute(f"INSERT INTO {table}_v7 {copies[table]}", () if table == "translation_targets" else (TRANSCRIPT,))
        db.execute(f"DROP TABLE {table}")
        db.execute(f"ALTER TABLE {table}_v7 RENAME TO {table}")
    # 번역 모듈이 없었던 DB는 모듈을 열 때 생성한다.
    if all(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
           for name in (*SOURCE_TABLES, "transcripts", "transcript_lines")):
        install_transcript_references(db)
