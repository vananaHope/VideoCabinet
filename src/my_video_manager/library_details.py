"""라이브러리 상세 표시용 일괄 읽기. 자막 본문을 메모리에 올리지 않는다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryDetails:
    has_transcript: bool = False
    spoken_language: str | None = None
    original_lines: int = 0
    translated_lines: int = 0
    subtitle_state: str | None = None
    translation_state: str | None = None
    highlight_count: int = 0


def read_library_details(connect) -> dict[int, LibraryDetails]:
    with connect() as db:
        db.execute("BEGIN")
        subtitles = {row["video_id"]: row for row in db.execute("""
            SELECT t.video_id,
                   CASE WHEN t.spoken_language = 'und' OR (COUNT(l.id) = 0 AND NOT t.language_specified)
                        THEN NULL ELSE t.spoken_language END AS spoken_language,
                   COUNT(l.id) AS original_lines,
                   COUNT(COALESCE(tr.text, target.text)) AS translated_lines
            FROM transcripts t LEFT JOIN transcript_lines l ON l.transcript_id = t.id
            LEFT JOIN translation_lines tr ON tr.line_id = l.id
            LEFT JOIN translation_targets target ON target.line_id = l.id GROUP BY t.video_id
        """)}
        highlights = dict(db.execute("SELECT video_id, COUNT(*) FROM highlights GROUP BY video_id"))
        return {
            row["id"]: LibraryDetails(
                row["id"] in subtitles,
                subtitles[row["id"]]["spoken_language"] if row["id"] in subtitles else None,
                subtitles[row["id"]]["original_lines"] if row["id"] in subtitles else 0,
                subtitles[row["id"]]["translated_lines"] if row["id"] in subtitles else 0,
                row["subtitle_state"], row["translation_state"], highlights.get(row["id"], 0),
            ) for row in db.execute("""
                SELECT v.id, s.state AS subtitle_state, t.state AS translation_state
                FROM videos v LEFT JOIN subtitle_queue s ON s.video_id = v.id
                LEFT JOIN translation_queue t ON t.video_id = v.id WHERE v.excluded = 0
            """)
        }
