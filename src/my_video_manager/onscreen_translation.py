"""화면 자막을 공용 번역 엔진에 연결한다. 줄·영역 언어·세대와 사용자 수정 보호를 소유한다."""
from contextlib import nullcontext
import json

from .onscreen_subtitles import ensure_onscreen_reviewable, normalize_onscreen_text
from .review import ReviewConfirmationRequired, ReviewLine
from .subtitles import TranscriptLine, normalize_subtitle_text
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
            db.execute('INSERT INTO onscreen_translation_reviews(line_id, translation_reviewed) VALUES (?, 1) '
                       'ON CONFLICT(line_id) DO UPDATE SET translation_reviewed=1', (line_id,))
            db.execute('DELETE FROM translation_line_providers WHERE video_id=? AND source=? AND line_id=?',
                       (video_id, ONSCREEN, line_id))
            # 진행 중인 응답도 이 줄의 사용자 수정본과 방식 기록을 덮어쓸 수 없다.
            db.execute('DELETE FROM translation_targets WHERE line_id=? AND queue_id IN '
                       '(SELECT id FROM translation_queue WHERE video_id=? AND source=?)', (line_id, video_id, ONSCREEN))
            translations.finish_ready(db, video_id, source=ONSCREEN)

    def edit_original(self, line_id, text, translations, *, overwrite_reviewed=False):
        """화면 자막 원문 한 줄을 고쳐 원문 검수됨으로 남기고 그 줄의 화면 번역만 다시 요청한다.

        그 줄의 화면 번역을 직접 고쳐 두었으면 overwrite_reviewed 없이는 ReviewConfirmationRequired를 던지고
        아무것도 바꾸지 않는다. 확인하면 보호를 풀고 다시 번역한다.
        """
        text = normalize_onscreen_text(text)
        if not text:
            raise ValueError('자막 텍스트를 입력하세요.')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT l.text, r.video_id, p.translation_reviewed FROM onscreen_subtitle_lines l '
                             'JOIN onscreen_subtitles s ON s.id=l.generation_id '
                             'JOIN onscreen_subtitle_regions r ON r.id=s.region_id '
                             'LEFT JOIN onscreen_translation_reviews p ON p.line_id=l.id WHERE l.id=?',
                             (line_id,)).fetchone()
            if row is None:
                raise ValueError('화면 자막 줄이 바뀌었습니다. 목록을 새로 확인하세요.')
            video_id = row['video_id']
            ensure_onscreen_reviewable(db, video_id)
            if row['text'] == text:
                return
            # 읽기에 실패한 영역이 있으면 화면 번역을 요청할 수 없다. 고친 줄이 번역되지 못한 채 남지 않게 막는다.
            if not self.lines(video_id, connection=db).complete:
                raise ValueError('읽지 못한 화면 자막 영역이 있어 고친 줄을 다시 번역할 수 없습니다. '
                                 '자막 대기열에서 실패 항목을 다시 시도한 뒤 고치세요.')
            if row['translation_reviewed'] and not overwrite_reviewed:
                raise ReviewConfirmationRequired('직접 고친 번역이 덮어써집니다. 계속할까요?')
            db.execute('UPDATE onscreen_subtitle_lines SET text=? WHERE id=?', (text, line_id))
            db.execute('INSERT INTO onscreen_translation_reviews(line_id, original_reviewed) VALUES (?, 1) '
                       'ON CONFLICT(line_id) DO UPDATE SET original_reviewed=1, translation_reviewed=0', (line_id,))
            translations.request(video_id, [line_id], connection=db, preserve_state=True, source=ONSCREEN)

    def review_lines(self, region_id):
        """영역의 현재 세대 줄마다 원문, 화면 번역(확정 또는 진행 중 저장 묶음), 원문 검수됨, 직접 수정."""
        with self._connect() as db:
            rows = db.execute(
                'SELECT l.*, p.original_reviewed, p.translation_reviewed, COALESCE(tr.text, target.text) AS translated '
                'FROM onscreen_subtitle_regions r JOIN onscreen_subtitles s ON s.region_id=r.id '
                'JOIN onscreen_subtitle_lines l ON l.generation_id=s.id '
                'LEFT JOIN onscreen_translation_reviews p ON p.line_id=l.id '
                'LEFT JOIN translation_lines tr ON tr.video_id=r.video_id AND tr.source=? AND tr.line_id=l.id '
                'LEFT JOIN translation_queue q ON q.video_id=r.video_id AND q.source=? '
                'LEFT JOIN translation_targets target ON target.queue_id=q.id AND target.line_id=l.id '
                'WHERE r.id=? ORDER BY l.ordinal', (ONSCREEN, ONSCREEN, region_id)).fetchall()
        return tuple(ReviewLine(TranscriptLine(r['id'], r['start'], r['end'], r['text']), r['translated'],
                                bool(r['original_reviewed']), bool(r['translation_reviewed'])) for r in rows)

    def reviewed_line_count(self, region_id, *, connection=None):
        """영역의 현재 세대에서 검수로 고친 줄(원문 수정·화면 번역 직접 수정) 수. 세대가 아직 없으면 None이다."""
        with (nullcontext(connection) if connection is not None else self._connect()) as db:
            row = db.execute(
                'SELECT r.id, s.id AS generation, (SELECT COUNT(*) FROM onscreen_subtitle_lines l '
                'JOIN onscreen_translation_reviews p ON p.line_id=l.id '
                'WHERE l.generation_id=s.id AND (p.original_reviewed=1 OR p.translation_reviewed=1)) AS reviewed '
                'FROM onscreen_subtitle_regions r LEFT JOIN onscreen_subtitles s ON s.region_id=r.id WHERE r.id=?',
                (region_id,)).fetchone()
        if row is None:
            raise ValueError('화면 자막 영역이 바뀌었습니다. 영역 정하기를 다시 여세요.')
        return None if row['generation'] is None else row['reviewed']

    def reviewed_lines(self, video_id):
        with self._connect() as db:
            return frozenset(r[0] for r in db.execute(
                'SELECT p.line_id FROM onscreen_translation_reviews p JOIN onscreen_subtitle_lines l ON l.id=p.line_id '
                'JOIN onscreen_subtitles s ON s.id=l.generation_id JOIN onscreen_subtitle_regions r ON r.id=s.region_id '
                'WHERE r.video_id=? AND p.translation_reviewed=1', (video_id,)))
