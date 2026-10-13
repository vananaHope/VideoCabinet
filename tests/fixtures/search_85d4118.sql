-- 최초 검색 빌드가 남긴 FTS와 앱 전용 함수 의존 트리거.
CREATE VIRTUAL TABLE subtitle_search USING fts5(
    normalized, text UNINDEXED, video_id UNINDEXED, source UNINDEXED,
    line_id UNINDEXED, start UNINDEXED, tokenize='trigram'
);
INSERT INTO subtitle_search VALUES('legacyweightshift', 'Legacy weight shift', 1, 'transcript', 'legacy-line', 12.5);
CREATE TRIGGER search_transcript_insert AFTER INSERT ON transcript_lines BEGIN
    INSERT INTO subtitle_search SELECT search_key(new.text), new.text, t.video_id,
        'transcript', new.id, new.start FROM transcripts t WHERE t.id=new.transcript_id;
END;
CREATE TRIGGER search_transcript_update AFTER UPDATE ON transcript_lines BEGIN
    DELETE FROM subtitle_search WHERE source='transcript' AND line_id=old.id;
    INSERT INTO subtitle_search SELECT search_key(new.text), new.text, t.video_id,
        'transcript', new.id, new.start FROM transcripts t WHERE t.id=new.transcript_id;
END;
CREATE TRIGGER search_transcript_delete AFTER DELETE ON transcript_lines BEGIN
    DELETE FROM subtitle_search WHERE source='transcript' AND line_id=old.id;
END;
