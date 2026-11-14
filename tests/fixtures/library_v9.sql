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
                    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    automatic INTEGER NOT NULL,
                    promoted INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL DEFAULT 'transcription',
                    UNIQUE(video_id, kind)
                );
CREATE TABLE subtitle_queue_hidden (
                    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL DEFAULT 'transcription',
                    PRIMARY KEY(video_id, kind)
                );
CREATE TABLE subtitle_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    spoken_language TEXT,
                    requested_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    error TEXT,
                    kind TEXT NOT NULL DEFAULT 'transcription',
                    UNIQUE(video_id, kind)
                );
CREATE TABLE transcripts (
                    video_id INTEGER PRIMARY KEY REFERENCES videos(id),
                    id TEXT NOT NULL UNIQUE,
                    spoken_language TEXT NOT NULL,
                    language_specified INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    model TEXT NOT NULL
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
CREATE TABLE translation_lines (line_id TEXT NOT NULL, text TEXT NOT NULL,
        video_id INTEGER NOT NULL REFERENCES videos(id), source TEXT NOT NULL,
        PRIMARY KEY(video_id, source, line_id));
CREATE TABLE translation_queue (id TEXT PRIMARY KEY,
        video_id INTEGER NOT NULL REFERENCES videos(id), transcript_id TEXT NOT NULL,
        requested_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', retry_at TEXT,
        error_kind TEXT, error_detail TEXT, source TEXT NOT NULL, spoken_language TEXT,
        UNIQUE(video_id, source));
CREATE TABLE translation_targets (queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
        line_id TEXT NOT NULL, text TEXT, PRIMARY KEY(queue_id, line_id));
CREATE TABLE translation_line_providers (line_id TEXT NOT NULL, provider TEXT NOT NULL,
        video_id INTEGER NOT NULL REFERENCES videos(id), source TEXT NOT NULL,
        PRIMARY KEY(video_id, source, line_id));
CREATE TABLE translation_omissions (transcript_id TEXT NOT NULL,
        video_id INTEGER NOT NULL REFERENCES videos(id), source TEXT NOT NULL,
        PRIMARY KEY(video_id, source));
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
CREATE INDEX translation_lines_source_line ON translation_lines(source, line_id);
CREATE INDEX translation_line_providers_source_line ON translation_line_providers(source, line_id);
CREATE INDEX translation_targets_line ON translation_targets(line_id);
CREATE TRIGGER translation_lines_transcript_insert
                BEFORE INSERT ON translation_lines WHEN new.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l JOIN transcripts t ON t.id=l.transcript_id
                    WHERE l.id=new.line_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript line'); END;
CREATE TRIGGER translation_lines_transcript_update
                BEFORE UPDATE ON translation_lines WHEN new.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l JOIN transcripts t ON t.id=l.transcript_id
                    WHERE l.id=new.line_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript line'); END;
CREATE TRIGGER translation_line_providers_transcript_insert
                BEFORE INSERT ON translation_line_providers WHEN new.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l JOIN transcripts t ON t.id=l.transcript_id
                    WHERE l.id=new.line_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript line'); END;
CREATE TRIGGER translation_line_providers_transcript_update
                BEFORE UPDATE ON translation_line_providers WHEN new.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l JOIN transcripts t ON t.id=l.transcript_id
                    WHERE l.id=new.line_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript line'); END;
CREATE TRIGGER translation_queue_transcript_insert
                BEFORE INSERT ON translation_queue WHEN new.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcripts t
                    WHERE t.id=new.transcript_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript generation'); END;
CREATE TRIGGER translation_queue_transcript_update
                BEFORE UPDATE ON translation_queue WHEN new.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcripts t
                    WHERE t.id=new.transcript_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript generation'); END;
CREATE TRIGGER translation_omissions_transcript_insert
                BEFORE INSERT ON translation_omissions WHEN new.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcripts t
                    WHERE t.id=new.transcript_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript generation'); END;
CREATE TRIGGER translation_omissions_transcript_update
                BEFORE UPDATE ON translation_omissions WHEN new.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcripts t
                    WHERE t.id=new.transcript_id AND t.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid transcript generation'); END;
CREATE TRIGGER translation_targets_transcript_insert
            BEFORE INSERT ON translation_targets
            WHEN EXISTS (SELECT 1 FROM translation_queue q WHERE q.id=new.queue_id AND q.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l
                    WHERE l.id=new.line_id AND l.transcript_id=q.transcript_id))
            BEGIN SELECT RAISE(ABORT, 'invalid transcript target'); END;
CREATE TRIGGER translation_targets_transcript_update
            BEFORE UPDATE ON translation_targets
            WHEN EXISTS (SELECT 1 FROM translation_queue q WHERE q.id=new.queue_id AND q.source='transcript'
                AND NOT EXISTS (SELECT 1 FROM transcript_lines l
                    WHERE l.id=new.line_id AND l.transcript_id=q.transcript_id))
            BEGIN SELECT RAISE(ABORT, 'invalid transcript target'); END;
CREATE TRIGGER translation_transcript_line_delete
        AFTER DELETE ON transcript_lines BEGIN
        DELETE FROM translation_lines WHERE source='transcript' AND line_id=old.id;
        DELETE FROM translation_line_providers WHERE source='transcript' AND line_id=old.id;
        DELETE FROM translation_targets WHERE line_id=old.id AND queue_id IN
            (SELECT id FROM translation_queue WHERE source='transcript'); END;
CREATE TRIGGER translation_transcript_delete
        AFTER DELETE ON transcripts BEGIN
        DELETE FROM translation_queue WHERE source='transcript' AND transcript_id=old.id;
        DELETE FROM translation_omissions WHERE source='transcript' AND transcript_id=old.id; END;
CREATE TRIGGER translation_transcript_line_identity
        BEFORE UPDATE OF id ON transcript_lines WHEN new.id != old.id AND (
            EXISTS (SELECT 1 FROM translation_lines WHERE source='transcript' AND line_id=old.id)
            OR EXISTS (SELECT 1 FROM translation_line_providers WHERE source='transcript' AND line_id=old.id)
            OR EXISTS (SELECT 1 FROM translation_targets g JOIN translation_queue q ON q.id=g.queue_id
                WHERE q.source='transcript' AND g.line_id=old.id))
        BEGIN SELECT RAISE(ABORT, 'referenced transcript line'); END;
CREATE TRIGGER translation_transcript_identity
        BEFORE UPDATE OF id ON transcripts WHEN new.id != old.id AND (
            EXISTS (SELECT 1 FROM translation_queue WHERE source='transcript' AND transcript_id=old.id)
            OR EXISTS (SELECT 1 FROM translation_omissions WHERE source='transcript' AND transcript_id=old.id))
        BEGIN SELECT RAISE(ABORT, 'referenced transcript generation'); END;
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
                AFTER INSERT ON transcript_lines  BEGIN INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('transcript', new.id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;
CREATE TRIGGER search_transcript_delete
                AFTER DELETE ON transcript_lines  BEGIN DELETE FROM search_subtitle_lines WHERE source='transcript' AND line_id=CAST(old.id AS TEXT); END;
CREATE TRIGGER search_transcript_update
                AFTER UPDATE OF text ON transcript_lines  BEGIN DELETE FROM search_subtitle_lines WHERE source='transcript' AND line_id=CAST(old.id AS TEXT);INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('transcript', new.id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;
CREATE TRIGGER search_translation_insert
                AFTER INSERT ON translation_lines WHEN new.source='transcript' BEGIN INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('translation', new.line_id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;
CREATE TRIGGER search_translation_delete
                AFTER DELETE ON translation_lines WHEN old.source='transcript' BEGIN DELETE FROM search_subtitle_lines WHERE source='translation' AND line_id=CAST(old.line_id AS TEXT); END;
CREATE TRIGGER search_translation_update
                AFTER UPDATE OF text ON translation_lines WHEN new.source='transcript' BEGIN DELETE FROM search_subtitle_lines WHERE source='translation' AND line_id=CAST(old.line_id AS TEXT);INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('translation', new.line_id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;
CREATE TRIGGER search_external_insert
                AFTER INSERT ON external_subtitle_lines  BEGIN INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('external', new.id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;
CREATE TRIGGER search_external_delete
                AFTER DELETE ON external_subtitle_lines  BEGIN DELETE FROM search_subtitle_lines WHERE source='external' AND line_id=CAST(old.id AS TEXT); END;
CREATE TRIGGER search_external_update
                AFTER UPDATE OF text ON external_subtitle_lines  BEGIN DELETE FROM search_subtitle_lines WHERE source='external' AND line_id=CAST(old.id AS TEXT);INSERT INTO search_subtitle_lines(source, line_id, text)
            VALUES('external', new.id, new.text)
            ON CONFLICT(source, line_id) DO UPDATE SET text=excluded.text, normalized=NULL; END;
CREATE INDEX videos_thumbnail_pending ON videos(id) WHERE substr(thumbnail,-8)!='.640.jpg' AND excluded=0;
CREATE TABLE onscreen_subtitle_regions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER NOT NULL REFERENCES videos(id),
        x REAL NOT NULL, y REAL NOT NULL, width REAL NOT NULL, height REAL NOT NULL,
        language TEXT NOT NULL,
        created_at TEXT NOT NULL);
CREATE INDEX onscreen_subtitle_regions_video ON onscreen_subtitle_regions(video_id);
CREATE TABLE onscreen_subtitles (
        region_id INTEGER PRIMARY KEY REFERENCES onscreen_subtitle_regions(id) ON DELETE CASCADE,
        id TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL);
CREATE TABLE onscreen_subtitle_lines (
        id TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL REFERENCES onscreen_subtitles(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        start REAL NOT NULL,
        end REAL NOT NULL,
        text TEXT NOT NULL,
        UNIQUE(generation_id, ordinal));
CREATE TABLE translation_glossary (video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE, source TEXT NOT NULL, target TEXT NOT NULL, ordinal INTEGER NOT NULL, PRIMARY KEY(video_id, source));
CREATE TABLE onscreen_translation_reviews (line_id TEXT PRIMARY KEY REFERENCES onscreen_subtitle_lines(id) ON DELETE CASCADE, translation_reviewed INTEGER NOT NULL DEFAULT 0);
CREATE TRIGGER translation_lines_onscreen_insert
                BEFORE INSERT ON translation_lines WHEN new.source='onscreen_subtitle' AND NOT EXISTS (
                    SELECT 1 FROM onscreen_subtitle_lines l JOIN onscreen_subtitles s ON s.id=l.generation_id
                    JOIN onscreen_subtitle_regions r ON r.id=s.region_id
                    WHERE l.id=new.line_id AND r.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid onscreen line'); END;
CREATE TRIGGER translation_lines_onscreen_update
                BEFORE UPDATE ON translation_lines WHEN new.source='onscreen_subtitle' AND NOT EXISTS (
                    SELECT 1 FROM onscreen_subtitle_lines l JOIN onscreen_subtitles s ON s.id=l.generation_id
                    JOIN onscreen_subtitle_regions r ON r.id=s.region_id
                    WHERE l.id=new.line_id AND r.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid onscreen line'); END;
CREATE TRIGGER translation_line_providers_onscreen_insert
                BEFORE INSERT ON translation_line_providers WHEN new.source='onscreen_subtitle' AND NOT EXISTS (
                    SELECT 1 FROM onscreen_subtitle_lines l JOIN onscreen_subtitles s ON s.id=l.generation_id
                    JOIN onscreen_subtitle_regions r ON r.id=s.region_id
                    WHERE l.id=new.line_id AND r.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid onscreen line'); END;
CREATE TRIGGER translation_line_providers_onscreen_update
                BEFORE UPDATE ON translation_line_providers WHEN new.source='onscreen_subtitle' AND NOT EXISTS (
                    SELECT 1 FROM onscreen_subtitle_lines l JOIN onscreen_subtitles s ON s.id=l.generation_id
                    JOIN onscreen_subtitle_regions r ON r.id=s.region_id
                    WHERE l.id=new.line_id AND r.video_id=new.video_id)
                BEGIN SELECT RAISE(ABORT, 'invalid onscreen line'); END;
CREATE TRIGGER translation_targets_onscreen_insert
            BEFORE INSERT ON translation_targets WHEN EXISTS (
                SELECT 1 FROM translation_queue q WHERE q.id=new.queue_id AND q.source='onscreen_subtitle'
                AND NOT EXISTS (SELECT 1 FROM onscreen_subtitle_lines l
                    JOIN onscreen_subtitles s ON s.id=l.generation_id
                    JOIN onscreen_subtitle_regions r ON r.id=s.region_id
                    WHERE l.id=new.line_id AND r.video_id=q.video_id))
            BEGIN SELECT RAISE(ABORT, 'invalid onscreen target'); END;
CREATE TRIGGER translation_targets_onscreen_update
            BEFORE UPDATE ON translation_targets WHEN EXISTS (
                SELECT 1 FROM translation_queue q WHERE q.id=new.queue_id AND q.source='onscreen_subtitle'
                AND NOT EXISTS (SELECT 1 FROM onscreen_subtitle_lines l
                    JOIN onscreen_subtitles s ON s.id=l.generation_id
                    JOIN onscreen_subtitle_regions r ON r.id=s.region_id
                    WHERE l.id=new.line_id AND r.video_id=q.video_id))
            BEGIN SELECT RAISE(ABORT, 'invalid onscreen target'); END;
CREATE TRIGGER translation_onscreen_line_delete
        AFTER DELETE ON onscreen_subtitle_lines BEGIN
        DELETE FROM translation_lines WHERE source='onscreen_subtitle' AND line_id=old.id;
        DELETE FROM translation_line_providers WHERE source='onscreen_subtitle' AND line_id=old.id;
        DELETE FROM translation_targets WHERE line_id=old.id AND queue_id IN
            (SELECT id FROM translation_queue WHERE source='onscreen_subtitle'); END;
PRAGMA user_version = 9;
