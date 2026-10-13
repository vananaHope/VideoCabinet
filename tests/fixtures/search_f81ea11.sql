-- #8 병합 f81ea11에서 추가된 번역 저장 구조. search_d692c23.sql 다음에 적용한다.
CREATE TABLE translation_lines (
    line_id TEXT PRIMARY KEY REFERENCES transcript_lines(id) ON DELETE CASCADE, text TEXT NOT NULL
);
INSERT INTO translation_lines VALUES('legacy-line', '기존 번역 체중이동');
