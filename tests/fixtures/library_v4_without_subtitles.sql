-- 자막 모듈이 아직 시작하지 않은 v4 라이브러리의 고정 DDL.
CREATE TABLE watched_folders (path TEXT PRIMARY KEY);
CREATE TABLE videos (
    id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL, duration REAL NOT NULL, format TEXT NOT NULL,
    thumbnail TEXT NOT NULL, registered_at TEXT NOT NULL,
    excluded INTEGER NOT NULL DEFAULT 0, width INTEGER, height INTEGER,
    resolution_checked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE locations (
    path TEXT PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id),
    size INTEGER, mtime_ns INTEGER);
CREATE TABLE library_file_checks (
    path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
    duration REAL, fingerprint TEXT);
CREATE INDEX videos_resolution_pending ON videos(id) WHERE resolution_checked=0;
CREATE TABLE translation_glossary (
    queue_id TEXT NOT NULL REFERENCES translation_queue(id) ON DELETE CASCADE,
    source TEXT NOT NULL, target TEXT NOT NULL, ordinal INTEGER NOT NULL,
    PRIMARY KEY(queue_id, source));
PRAGMA user_version=4;
