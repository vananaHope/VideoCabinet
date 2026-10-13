-- 검색 도입 전 main d692c23의 영속 구조와 데이터. 파일 없음 영상의 기록이다.
PRAGMA user_version = 1;
CREATE TABLE watched_folders (path TEXT PRIMARY KEY);
CREATE TABLE videos (
    id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
    duration REAL NOT NULL, format TEXT NOT NULL, thumbnail TEXT NOT NULL,
    registered_at TEXT NOT NULL
);
CREATE TABLE locations (path TEXT PRIMARY KEY, video_id INTEGER NOT NULL REFERENCES videos(id));
CREATE TABLE transcripts (
    video_id INTEGER PRIMARY KEY REFERENCES videos(id), id TEXT NOT NULL UNIQUE,
    spoken_language TEXT NOT NULL, language_specified INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE transcript_lines (
    id TEXT PRIMARY KEY, transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL, text TEXT NOT NULL,
    UNIQUE(transcript_id, ordinal)
);
INSERT INTO videos VALUES(1, 'v1:4:legacy', '기존 영상', 100, 'matroska', 'thumbnails/old.jpg', '2026-10-14T00:00:00+00:00');
INSERT INTO transcripts VALUES(1, 'legacy-transcript', 'en', 0, '2026-10-14T00:00:00+00:00');
INSERT INTO transcript_lines VALUES('legacy-line', 'legacy-transcript', 0, 12.5, 15, 'Legacy weight shift');
