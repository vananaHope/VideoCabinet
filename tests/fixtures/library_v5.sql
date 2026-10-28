-- 고정 v5 스키마: v4에 #288의 transcripts.model 열만 추가. 작업 종류 도입 전 형식.
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE watched_folders (path TEXT PRIMARY KEY);

CREATE TABLE videos (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL, duration REAL NOT NULL, format TEXT NOT NULL,
            thumbnail TEXT NOT NULL, registered_at TEXT NOT NULL, excluded INTEGER NOT NULL DEFAULT 0, width INTEGER, height INTEGER, resolution_checked INTEGER NOT NULL DEFAULT 0);

CREATE TABLE locations (
            path TEXT PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id), size INTEGER, mtime_ns INTEGER);

CREATE TABLE library_file_checks (
            path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
            duration REAL, fingerprint TEXT);

CREATE INDEX videos_resolution_pending ON videos(id) WHERE resolution_checked=0;

CREATE INDEX locations_video_id ON locations(video_id);

CREATE TABLE external_subtitle_files (
                id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id),
                path TEXT NOT NULL, size INTEGER, mtime_ns INTEGER, encoding TEXT, warning TEXT,
                UNIQUE(video_id, path));

CREATE TABLE external_subtitles (
                id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES external_subtitle_files(id)
                ON DELETE CASCADE, language TEXT, language_class TEXT NOT NULL);

CREATE INDEX external_subtitles_file ON external_subtitles(file_id);

CREATE TABLE external_subtitle_lines (
                id INTEGER PRIMARY KEY, subtitle_id INTEGER NOT NULL REFERENCES external_subtitles(id)
                ON DELETE CASCADE, start REAL NOT NULL, end REAL NOT NULL, text TEXT NOT NULL);

CREATE INDEX external_subtitle_lines_track ON external_subtitle_lines(subtitle_id);

CREATE TABLE series (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    folder TEXT,
                    title_template TEXT,
                    edited INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(folder, title_template)
                );

CREATE TABLE series_videos (
                    series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
                    video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
                    position INTEGER NOT NULL,
                    PRIMARY KEY(series_id, position)
                );

CREATE TABLE series_overrides (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id)
                );

CREATE TABLE series_order_changes (
                    series_id INTEGER PRIMARY KEY REFERENCES series(id) ON DELETE CASCADE
                );

CREATE TABLE highlights (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    start REAL NOT NULL CHECK(start >= 0),
                    end REAL CHECK(end > start),
                    note TEXT
                );

CREATE INDEX highlights_video_start
                    ON highlights(video_id, start, id);

CREATE TABLE dismissed_videos (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE
                );

CREATE TABLE highlight_created_at (
                    highlight_id INTEGER PRIMARY KEY REFERENCES highlights(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL
                );

CREATE TABLE tags (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE
                );

CREATE TABLE video_tags (
                    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (video_id, tag_id)
                );

CREATE TABLE highlight_tags (
                    highlight_id INTEGER NOT NULL REFERENCES highlights(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (highlight_id, tag_id)
                );

CREATE INDEX video_tags_tag ON video_tags(tag_id);

CREATE INDEX highlight_tags_tag ON highlight_tags(tag_id);

CREATE TABLE viewings (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    duration REAL NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ended_at TEXT,
                    intervals TEXT NOT NULL,
                    last_position REAL
                );

CREATE INDEX viewings_video ON viewings(video_id);

CREATE TABLE subtitle_queue_order (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE,
                    automatic INTEGER NOT NULL,
                    promoted INTEGER NOT NULL DEFAULT 0
                );

CREATE TABLE subtitle_queue_hidden (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE
                );

CREATE TABLE subtitle_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
                    spoken_language TEXT,
                    requested_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    error TEXT
                );

CREATE TABLE transcripts (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id),
                    id TEXT NOT NULL UNIQUE,
                    spoken_language TEXT NOT NULL,
                    language_specified INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT 'large-v3'
                );

CREATE TABLE transcript_lines (
                    id TEXT PRIMARY KEY,
                    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    start REAL NOT NULL,
                    end REAL NOT NULL,
                    text TEXT NOT NULL,
                    UNIQUE(transcript_id, ordinal)
                );

CREATE TABLE subtitle_reviews (
                    line_id TEXT PRIMARY KEY REFERENCES transcript_lines(id) ON DELETE CASCADE,
                    original_reviewed INTEGER NOT NULL DEFAULT 0,
                    translation_reviewed INTEGER NOT NULL DEFAULT 0
                );

CREATE TABLE subtitle_review_ranges (
                    queue_id INTEGER PRIMARY KEY REFERENCES subtitle_queue(id) ON DELETE CASCADE,
                    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    start REAL NOT NULL,
                    end REAL NOT NULL
                );

CREATE TABLE translation_lines (
                    line_id TEXT PRIMARY KEY REFERENCES transcript_lines(id) ON DELETE CASCADE,
                    text TEXT NOT NULL
                );

CREATE TABLE translation_queue (
                    id TEXT PRIMARY KEY,
                    video_id INTEGER NOT NULL UNIQUE REFERENCES videos(id),
                    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    requested_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    retry_at TEXT,
                    error_kind TEXT,
                    error_detail TEXT
                );

CREATE TABLE translation_targets (
                    queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
                    line_id TEXT NOT NULL REFERENCES transcript_lines(id) ON DELETE CASCADE,
                    text TEXT,
                    PRIMARY KEY(queue_id, line_id)
                );

CREATE TABLE translation_cli_backoff (
                    cli TEXT PRIMARY KEY,
                    retry_at TEXT NOT NULL
                );

CREATE TABLE translation_limit_attempts (
                    queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
                    cli TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    PRIMARY KEY(queue_id, cli)
                );

CREATE TABLE translation_line_providers (
                    line_id TEXT PRIMARY KEY REFERENCES transcript_lines(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL
                );

CREATE TABLE translation_target_providers (
                    queue_id TEXT NOT NULL,
                    line_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    PRIMARY KEY(queue_id, line_id),
                    FOREIGN KEY(queue_id, line_id) REFERENCES translation_targets(queue_id, line_id) ON DELETE CASCADE
                );

CREATE TABLE translation_routes (
                    queue_id TEXT PRIMARY KEY REFERENCES translation_queue(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL
                );

CREATE TABLE translation_job_options (
                    queue_id TEXT PRIMARY KEY REFERENCES translation_queue(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    selections TEXT NOT NULL
                );

CREATE TABLE translation_fallback_notices (
                    queue_id TEXT PRIMARY KEY REFERENCES translation_queue(id) ON DELETE CASCADE,
                    message TEXT NOT NULL
                );

CREATE TABLE translation_omissions (
                    transcript_id TEXT PRIMARY KEY REFERENCES transcripts(id) ON DELETE CASCADE
                );

CREATE TABLE auto_subtitle_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder TEXT UNIQUE REFERENCES watched_folders(path) ON DELETE CASCADE,
                    tag_id INTEGER UNIQUE REFERENCES tags(id) ON DELETE CASCADE,
                    spoken_language TEXT,
                    CHECK ((folder IS NULL) != (tag_id IS NULL))
                );

CREATE TABLE revisits (
                    highlight_id INTEGER PRIMARY KEY REFERENCES highlights(id) ON DELETE CASCADE,
                    last_revisited_at TEXT NOT NULL
                );

CREATE TABLE search_subtitle_lines (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, line_id TEXT NOT NULL,
                text TEXT NOT NULL, normalized TEXT, UNIQUE(source, line_id)
            );

CREATE INDEX search_pending_normalization
                ON search_subtitle_lines(id) WHERE normalized IS NULL;

CREATE TABLE search_backfill_sources (source TEXT PRIMARY KEY);

CREATE VIRTUAL TABLE subtitle_search_v2 USING fts5(
                normalized, content='search_subtitle_lines', content_rowid='id', tokenize='trigram'
            );

CREATE TRIGGER search_content_insert
                AFTER INSERT ON search_subtitle_lines WHEN new.normalized IS NOT NULL BEGIN
                INSERT INTO subtitle_search_v2(rowid, normalized) VALUES(new.id, new.normalized); END;

CREATE TRIGGER search_content_delete
                AFTER DELETE ON search_subtitle_lines WHEN old.normalized IS NOT NULL BEGIN
                INSERT INTO subtitle_search_v2(subtitle_search_v2, rowid, normalized)
                VALUES('delete', old.id, old.normalized); END;

CREATE TRIGGER search_content_update
    AFTER UPDATE ON search_subtitle_lines BEGIN
    INSERT INTO subtitle_search_v2(subtitle_search_v2, rowid, normalized)
        SELECT 'delete', old.id, old.normalized WHERE old.normalized IS NOT NULL;
    INSERT INTO subtitle_search_v2(rowid, normalized)
        SELECT new.id, new.normalized WHERE new.normalized IS NOT NULL; END;

CREATE TRIGGER search_transcript_insert
                AFTER INSERT ON transcript_lines BEGIN INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('transcript', new.id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;

CREATE TRIGGER search_transcript_delete
                AFTER DELETE ON transcript_lines BEGIN DELETE FROM search_subtitle_lines WHERE source='transcript' AND line_id=CAST(old.id AS TEXT); END;

CREATE TRIGGER search_transcript_update
                AFTER UPDATE OF text ON transcript_lines BEGIN DELETE FROM search_subtitle_lines WHERE source='transcript' AND line_id=CAST(old.id AS TEXT);INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('transcript', new.id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;

CREATE TRIGGER search_translation_insert
                AFTER INSERT ON translation_lines BEGIN INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('translation', new.line_id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;

CREATE TRIGGER search_translation_delete
                AFTER DELETE ON translation_lines BEGIN DELETE FROM search_subtitle_lines WHERE source='translation' AND line_id=CAST(old.line_id AS TEXT); END;

CREATE TRIGGER search_translation_update
                AFTER UPDATE OF text ON translation_lines BEGIN DELETE FROM search_subtitle_lines WHERE source='translation' AND line_id=CAST(old.line_id AS TEXT);INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('translation', new.line_id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;

CREATE TRIGGER search_external_insert
                AFTER INSERT ON external_subtitle_lines BEGIN INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('external', new.id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;

CREATE TRIGGER search_external_delete
                AFTER DELETE ON external_subtitle_lines BEGIN DELETE FROM search_subtitle_lines WHERE source='external' AND line_id=CAST(old.id AS TEXT); END;

CREATE TRIGGER search_external_update
                AFTER UPDATE OF text ON external_subtitle_lines BEGIN DELETE FROM search_subtitle_lines WHERE source='external' AND line_id=CAST(old.id AS TEXT);INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('external', new.id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;
CREATE TABLE translation_glossary (
    queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
    source TEXT NOT NULL, target TEXT NOT NULL, ordinal INTEGER NOT NULL,
    PRIMARY KEY(queue_id, source));
PRAGMA user_version=5;
