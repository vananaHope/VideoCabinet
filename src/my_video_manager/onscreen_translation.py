"""화면 자막을 공용 번역 엔진에 연결한다. 줄·영역 언어·세대와 사용자 수정 보호를 소유한다."""
from contextlib import nullcontext
import json

from .subtitles import normalize_subtitle_text
from .translation_source import ONSCREEN, OnScreenTranslationSourceLine, TranslationSourceLines


def onscreen_generation_token(regions):
    """빈 세대와 아직 읽지 않은 영역도 포함한다. UUID를 크기나 시각으로 비교하지 않는다."""
    return json.dumps(sorted(regions), separators=(',', ':'))


class OnScreenTranslationSource:
    def __init__(self, connect):
        self._connect = connect

    def lines(self, video_id, *, connection=None):
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            if not db.in_transaction:
                db.execute('BEGIN')
            regions = db.execute('SELECT r.id, s.id AS generation, r.language '
                                 'FROM onscreen_subtitle_regions r LEFT JOIN onscreen_subtitles s ON s.region_id=r.id '
                                 'WHERE r.video_id=? ORDER BY r.id', (video_id,)).fetchall()
            if not regions:
                return None
            lines = tuple(OnScreenTranslationSourceLine(r['id'], r['start'], r['end'], r['text'],
                                                        r['region_id'], r['language']) for r in db.execute(
                'SELECT l.*, r.id AS region_id, r.language FROM onscreen_subtitle_lines l '
                'JOIN onscreen_subtitles s ON s.id=l.generation_id '
                'JOIN onscreen_subtitle_regions r ON r.id=s.region_id '
                'WHERE r.video_id=? ORDER BY l.start, r.id, l.ordinal', (video_id,)))
            return TranslationSourceLines(onscreen_generation_token((r['id'], r['generation']) for r in regions),
                                          video_id, regions[0]['language'], lines,
                                          complete=all(r['generation'] is not None for r in regions))

    @staticmethod
    def protected_lines(db):
        return {r[0] for r in db.execute('SELECT line_id FROM onscreen_translation_reviews WHERE translation_reviewed=1')}

    def skip_reason(self, video_id):
        original = self.lines(video_id)
        return 'no_onscreen_text' if original and original.complete and not original.lines else None

    def edit(self, line_id, text, translations):
        text = normalize_subtitle_text(text)
        if not text:
            raise ValueError('자막 텍스트를 입력하세요.')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT r.video_id FROM onscreen_subtitle_lines l '
                             'JOIN onscreen_subtitles s ON s.id=l.generation_id '
                             'JOIN onscreen_subtitle_regions r ON r.id=s.region_id WHERE l.id=?', (line_id,)).fetchone()
            if row is None:
                raise ValueError('화면 자막 줄이 바뀌었습니다. 목록을 새로 확인하세요.')
            video_id = row[0]
            db.execute('INSERT INTO translation_lines VALUES (?, ?, ?, ?) '
                       'ON CONFLICT(video_id, source, line_id) DO UPDATE SET text=excluded.text',
                       (line_id, text, video_id, ONSCREEN))
            db.execute('INSERT OR REPLACE INTO onscreen_translation_reviews VALUES (?, 1)', (line_id,))
            db.execute('DELETE FROM translation_line_providers WHERE video_id=? AND source=? AND line_id=?',
                       (video_id, ONSCREEN, line_id))
            # 진행 중인 응답도 이 줄의 사용자 수정본과 방식 기록을 덮어쓸 수 없다.
            db.execute('DELETE FROM translation_targets WHERE line_id=? AND queue_id IN '
                       '(SELECT id FROM translation_queue WHERE video_id=? AND source=?)', (line_id, video_id, ONSCREEN))
            translations.finish_ready(db, video_id, source=ONSCREEN)

    def reviewed_lines(self, video_id):
        with self._connect() as db:
            return frozenset(r[0] for r in db.execute(
                'SELECT p.line_id FROM onscreen_translation_reviews p JOIN onscreen_subtitle_lines l ON l.id=p.line_id '
                'JOIN onscreen_subtitles s ON s.id=l.generation_id JOIN onscreen_subtitle_regions r ON r.id=s.region_id '
                'WHERE r.video_id=? AND p.translation_reviewed=1', (video_id,)))
