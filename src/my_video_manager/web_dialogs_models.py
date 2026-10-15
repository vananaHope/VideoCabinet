"""웹 대화상자의 표시/명령 어댑터. 모든 저장 정책은 AppCore 공개 API를 따른다."""
from uuid import uuid4
from math import isfinite

from .highlight_editing import initial_time_input, resolve_time_input, time_input_maximum
from .review import ReviewConfirmationRequired
from .web_dialogs_data import row, values


TITLES = {
    'tags': '영상 태그', 'tag-manager': '모든 태그 관리', 'tag-rename': '태그 이름 변경',
    'series': '시리즈 편집', 'highlights': '현재 영상의 하이라이트',
    'highlight': '하이라이트 시각·메모 편집', 'subtitles': '원어 자막 만들기',
    'review': '자막 검수 · SRT 내보내기', 'line': '자막 줄 수정',
    'range': '구간 원어 자막 다시 생성', 'translation': '번역 방식 / 재시도',
    'video-rename': '제목 변경', 'video-exclude': '영상 제외',
}


class DialogModel:
    def __init__(self, owner, kind, **context):
        self.owner, self.core, self.kind, self.context = owner, owner.core, kind, context
        self.identifier = uuid4().hex
        self.values = values()
        self.confirmation = ''
        self.confirm_title = ''
        self.confirm_destructive = False
        self.pending = None
        self.keep_pending = None
        self.message = ''
        self.information = ''
        if kind == 'highlight':
            h, duration = context['highlight'], context['duration']
            self.values = values(start=initial_time_input(h.start, duration),
                                 end=initial_time_input(h.end if h.end is not None else h.start, duration),
                                 range=h.end is not None, text=h.note.text if h.note else '')
        elif kind == 'subtitles':
            transcript = self.core.transcript(context['video_id'])
            self.values['choice'] = transcript.spoken_language if transcript and transcript.language_specified else '자동 감지'
        elif kind == 'translation':
            self.translation = self.core.translation_settings()
            self.values.update(choice=self.translation['provider'], selections=self.translation['selections'],
                               fallback=self.translation['fallback'])
            self.network_busy = False
            self.waiting = [e.video_id for e in self.core.translation_queue() if e.state in ('failed', 'held')]
        elif kind == 'line':
            line = context['line']
            self.values['text'] = (line.translation or '') if context['translated'] else line.original.text
        elif kind == 'range':
            line = context.get('line')
            self.values.update(start=line.original.start if line else 0,
                               end=line.original.end if line else self.core.video(context['video_id']).duration)
        elif kind == 'tag-rename':
            self.values['name'] = context['tag'].name
        elif kind == 'series' and context.get('series_id') is not None:
            selected = next(s for s in self.core.series() if s.id == context['series_id'])
            self.values = values(choice=str(selected.id), name=selected.name,
                                 members=[str(v) for v in selected.video_ids])
        elif kind == 'video-rename':
            self.values['name'] = self.core.video(context['video_id']).title
        elif kind == 'video-exclude':
            video = self.core.video(context['video_id'])
            def exclude():
                self.core.exclude_video(video.id)
                self.owner.pop(accepted=True)
            self.confirm(f"'{video.title}'을 제외할까요?\n실제 파일과 기록은 남으며 제외 목록에서 되돌릴 수 있습니다.",
                         exclude, title='영상 제외', destructive=True)

    def snapshot(self):
        c, ctx, kind = self.core, self.context, self.kind
        task = c.subtitle_task(ctx['video_id']) if 'video_id' in ctx else None
        data = dict(task_kind=task.kind if task else '', task_label=task.label if task else '',
                    subtitle_label=task.subtitle_label if task else '', short_label=task.short_label if task else '',
                    keep_reviewed=self.keep_pending is not None, id=self.identifier, kind=kind, title=TITLES[kind], description='', rows=[], available=[],
                    choices=[], values=self.values.copy(), maximum=0.0, locked=False, warning='',
                    confirmation=self.confirmation, confirm_title=self.confirm_title, confirm_destructive=self.confirm_destructive, translation=None, network_busy=False, information=self.information)
        if kind == 'tags':
            highlight = ctx.get('highlight_id')
            tags = c.highlight_tags(highlight) if highlight is not None else c.video_tags(ctx['video_id'])
            data.update(title='하이라이트 태그' if highlight is not None else TITLES[kind],
                        description='Enter로 추가 · ↓/↑로 후보 선택 · Tab으로 버튼 이동 · 변경은 즉시 저장됩니다.',
                        rows=[row(t.id, t.name) for t in tags])
        elif kind == 'tag-manager':
            data.update(description='이름 변경과 삭제는 모든 영상·하이라이트에 적용됩니다.',
                        rows=[row(t.id, t.name) for t in c.tags()])
        elif kind == 'series':
            series = c.series()
            selected = next((s for s in series if str(s.id) == self.values['choice']), None)
            assigned = {vid for s in series if s != selected for vid in s.video_ids}
            data.update(description='왼쪽: 시리즈 순서 · 오른쪽: 넣을 영상. 다른 시리즈의 영상은 먼저 그 시리즈에서 빼 주세요. 저장 전에 시리즈를 바꾸면 편집이 취소됩니다.',
                        choices=[row('', '새 시리즈'), *[row(s.id, s.name) for s in series]],
                        available=[row(v.id, v.title, '파일 없음' if v.missing else '') for v in c.videos() if v.id not in assigned])
        elif kind == 'highlights':
            from .time_display import timestamp
            data.update(description='더블클릭 또는 Enter로 시각·메모 편집', rows=[
                row(h.id, timestamp(h.start) + (f' – {timestamp(h.end)}' if h.end is not None else ' (지점)'),
                    h.note.text if h.note else '메모 없음', ', '.join(t.name for t in c.highlight_tags(h.id)), h.start, h.end)
                for h in c.highlights(ctx['video_id'])])
        elif kind == 'highlight':
            data['maximum'] = time_input_maximum(ctx['duration'])
        elif kind == 'subtitles':
            transcript = c.transcript(ctx['video_id'])
            languages = list(dict.fromkeys(['자동 감지', 'ko', 'en', 'ja', 'zh', 'de', 'fr', 'es', self.values['choice']]))
            data.update(description='원어를 고르거나 언어 코드를 입력하세요 (예: en, ko, ja).',
                        choices=[row(v, v) for v in languages])
            if transcript:
                data['description'] += f" 현재 원어: {transcript.spoken_language or '알 수 없음'} ({'직접 지정' if transcript.language_specified else '자동 감지'})"
            data['information'] = c.subtitle_preparation_notice()
        elif kind == 'review':
            from .translation_models import TRANSLATION_CHOICES
            names = dict(TRANSLATION_CHOICES)
            provenance = c.translation_line_providers(ctx['video_id'])
            data.update(description='클릭 또는 Enter로 장면 이동 · 방향키로 줄 선택 · Tab으로 버튼 이동 · Esc로 닫기', rows=[
                row(line.original.id, line.original.text, line.translation if line.translation is not None else f'미{task.label}',
                    ' · '.join(label for flag, label in ((line.original_reviewed, '원어 검수됨'),
                                                       (line.translation_reviewed, '사용자가 고친 줄' if task.kind == 'refinement' else '직접 수정'),
                                                       (not line.translation_reviewed and provenance.get(line.original.id), names.get(not line.translation_reviewed and provenance.get(line.original.id), ''))) if flag),
                    line.original.start, line.original.end) for line in c.review_lines(ctx['video_id'])])
        elif kind == 'range':
            data['maximum'] = c.video(ctx['video_id']).duration
            try:
                start, end = c.subtitle_range_bounds(ctx['video_id'], self.values['start'], self.values['end'])
                data['description'] = f'실제로 받아쓸 범위: {start:.3f}–{end:.3f}초. 경계에 걸친 줄 전체를 포함하도록 넓혀 원어와 {task.subtitle_label}을 교체합니다.'
            except ValueError as error:
                data['warning'] = str(error)
        elif kind == 'line':
            data['title'] = f'{task.short_label} 줄 수정' if ctx['translated'] else '원어 줄 수정'
        elif kind == 'translation':
            data.update(choices=[row(p['id'], p['label']) for p in self.translation['providers']],
                        translation=self.translation, network_busy=self.network_busy,
                        description='한국어 번역 방식과 모델을 고르세요. 키·설정 변경은 확인할 때 저장됩니다.')
            if self.waiting:
                data['description'] += f' 확인하면 실패·보류 중인 번역 {len(self.waiting)}건을 저장한 묶음부터 재시도합니다. 선택한 방식의 사용량 한도 보류 시간이 남았으면 그 시각까지 기다립니다.'
        if kind in ('review', 'line', 'range'):
            data['locked'] = any(e.video_id == ctx['video_id'] and e.state in ('queued', 'transcribing') for e in c.subtitle_queue())
            if data['locked']:
                data['warning'] = '자막 재생성 대기·진행 중에는 줄 수정과 구간 재생성을 할 수 없습니다.'
        data['warning'] = data['warning'] or self.message
        return data

    @staticmethod
    def time_value(value):
        try:
            number = float(value)
        except (ValueError, TypeError):
            raise ValueError('시작과 끝 시각을 입력하세요.') from None
        if not isfinite(number):
            raise ValueError('올바른 시각을 입력하세요.')
        return round(number, 3)

    def confirm(self, message, callback, *, title='자막 검수', destructive=False):
        self.confirmation, self.pending = message, callback
        self.confirm_title, self.confirm_destructive = title, destructive

    def push(self, kind, **context):
        self.owner.push(kind, **context)

    def changed(self):
        callback = self.context.get('changed')
        if callback:
            callback(self.context['video_id'])

    def act(self, action, data):
        c, ctx, kind = self.core, self.context, self.kind
        if action == 'keep-reviewed' and self.keep_pending:
            callback, self.keep_pending, self.pending, self.confirmation = self.keep_pending, None, None, ''
            callback()
            return
        if action == 'confirm':
            self.keep_pending = None
            callback, self.pending, self.confirmation = self.pending, None, ''
            if callback is None:
                raise ValueError('확인할 작업이 없습니다.')
            callback()
            return
        if action == 'cancel-confirm':
            self.keep_pending = None
            self.pending, self.confirmation = None, ''
            if kind == 'video-exclude':
                self.owner.pop()
            return
        if self.pending:
            raise ValueError('확인 또는 취소를 먼저 선택하세요.')
        if action == 'close':
            self.owner.pop(accepted=bool(data.get('accepted', False)))
            return
        if kind == 'video-rename' and action == 'save':
            c.rename_video(ctx['video_id'], data['name'])
            self.owner.pop(accepted=True)
            return
        if kind == 'tags':
            highlight = ctx.get('highlight_id')
            identifier = highlight if highlight is not None else ctx['video_id']
            if action == 'add':
                (c.add_highlight_tag if highlight is not None else c.add_video_tag)(identifier, data['name'])
            elif action == 'remove':
                (c.remove_highlight_tag if highlight is not None else c.remove_video_tag)(identifier, int(data['selected']))
            elif action == 'manage':
                self.push('tag-manager')
            else:
                raise ValueError('지원하지 않는 태그 작업입니다.')
        elif kind == 'tag-manager':
            tag = next(t for t in c.tags() if str(t.id) == data['selected'])
            if action == 'rename':
                self.push('tag-rename', tag=tag)
            elif action == 'delete':
                self.confirm(f'‘{tag.name}’ 태그를 모든 영상·하이라이트에서 삭제할까요?', lambda: c.delete_tag(tag.id), title='태그 삭제', destructive=True)
            else:
                raise ValueError('지원하지 않는 태그 작업입니다.')
        elif kind == 'tag-rename' and action == 'save':
            c.rename_tag(ctx['tag'].id, data['name'])
            self.owner.pop(accepted=True)
        elif kind == 'series':
            if action == 'choose':
                selected = next((s for s in c.series() if str(s.id) == data['choice']), None)
                self.values = values(choice=str(selected.id) if selected else '', name=selected.name if selected else '',
                                     members=[str(v) for v in selected.video_ids] if selected else [])
                # 새 선택은 입력 초깃값도 바꾼다.
                self.identifier = uuid4().hex
            elif action == 'save':
                ids = tuple(int(v) for v in data['members'])
                if self.values['choice']:
                    c.update_series(int(self.values['choice']), name=data['name'], video_ids=ids)
                else:
                    c.create_series(data['name'], ids)
                self.owner.pop(accepted=True)
            else:
                raise ValueError('지원하지 않는 시리즈 작업입니다.')
        elif kind == 'highlights':
            h = next(h for h in c.highlights(ctx['video_id']) if str(h.id) == data['selected'])
            if action == 'edit':
                self.push('highlight', highlight=h, duration=ctx['duration'])
            elif action == 'tags':
                self.push('tags', highlight_id=h.id)
            elif action == 'delete':
                c.delete_highlight(h.id)
            else:
                raise ValueError('지원하지 않는 하이라이트 작업입니다.')
        elif kind == 'highlight' and action == 'save':
            h = ctx['highlight']
            start = resolve_time_input(h.start, self.values['start'], self.time_value(data['start']))
            end = resolve_time_input(h.end, self.values['end'], self.time_value(data['end'])) if data['range'] else None
            c.update_highlight(h.id, start=start, end=end, note=data['text'])
            self.owner.pop(accepted=True)
        elif kind == 'subtitles' and action == 'save':
            def request():
                c.request_subtitles(ctx['video_id'], None if data['choice'] == '자동 감지' else data['choice'])
                self.owner.window.statusBar().showMessage('자막 대기열에 추가했습니다. 재생 중에도 계속 처리합니다.')
                self.owner.window.subtitles.video_changed.emit(ctx['video_id'])
                self.owner.pop(accepted=True)
            if c.transcript(ctx['video_id']):
                self.confirm(c.subtitle_regeneration_warning(ctx['video_id']), request, title='원어 자막 다시 생성', destructive=True)
            else:
                request()
        elif kind == 'review':
            if action == 'refine':
                c.request_refinement(ctx['video_id'])
                self.changed()
                self.information = '다듬기를 요청했습니다.'
                return
            lines = c.review_lines(ctx['video_id'])
            line = next((line for line in lines if line.original.id == data.get('selected')), None)
            if action in ('jump', 'edit-original', 'edit-translation'):
                if line is None:
                    raise ValueError('자막 줄이 바뀌었습니다. 목록을 새로 확인하세요.')
                if action == 'jump':
                    ctx['jump'](ctx['video_id'], line.original.id)
                else:
                    self.push('line', **ctx, line=line, translated=action == 'edit-translation')
            elif action == 'range':
                self.push('range', **ctx, line=line)
            elif action == 'regenerate':
                def regenerate():
                    transcript = c.transcript(ctx['video_id'])
                    c.request_subtitles(ctx['video_id'], transcript.spoken_language if transcript and transcript.language_specified else None)
                self.confirm(c.subtitle_regeneration_warning(ctx['video_id']), regenerate, destructive=True)
            elif action in ('export-original', 'export-translation'):
                translated = action == 'export-translation'
                export = c.subtitle_export(ctx['video_id'], translated=translated)
                callback = lambda: self.owner.save_export(export)
                if translated and (export.missing_lines or export.pending_retranslation_lines):
                    self.confirm(export.warning, callback)
                else:
                    callback()
            else:
                raise ValueError('지원하지 않는 검수 작업입니다.')
        elif kind == 'line' and action == 'save':
            def edit(overwrite=False, keep=False):
                if ctx['translated']:
                    c.edit_translation_line(ctx['video_id'], ctx['line'].original.id, data['text'])
                else:
                    c.edit_transcript_line(ctx['video_id'], ctx['line'].original.id, data['text'], overwrite_reviewed=overwrite, keep_reviewed=keep)
                self.changed()
                self.owner.pop(accepted=True)
            try:
                edit()
            except ReviewConfirmationRequired as warning:
                self.confirm(str(warning), lambda: edit(True), destructive=True)
                if c.subtitle_task(ctx["video_id"]).kind == "refinement":
                    self.keep_pending = lambda: edit(keep=True)
        elif kind == 'range':
            if action == 'bounds':
                self.values.update(start=self.time_value(data['start']), end=self.time_value(data['end']))
            elif action == 'save':
                c.request_subtitle_range(ctx['video_id'], self.time_value(data['start']), self.time_value(data['end']))
                self.owner.pop(accepted=True)
            else:
                raise ValueError('지원하지 않는 구간 작업입니다.')
        elif kind == 'translation' and action in ('check-key', 'load-models'):
            self.owner.translation_request(self, action, data)
        elif kind == 'translation' and action == 'save':
            if self.network_busy:
                raise ValueError('키 확인 또는 목록 조회가 끝난 뒤 저장하세요.')
            notice = c.save_translation_settings(data['choice'], data.get('selections', self.values['selections']),
                data.get('fallback', self.values['fallback']), key_action=data.get('key_action', 'keep'), key=data.get('key', ''))
            for video_id in self.waiting:
                try:
                    c.request_translation(video_id)
                except ValueError:
                    pass  # Qt 경로와 같이 그 사이 원어가 재생성된 영상은 새 요청을 따른다.
            from .translation_models import provider
            self.owner.window.statusBar().showMessage(f"번역 방식: {provider(data['choice']).label} {notice}", 5000)
            self.owner.pop(accepted=True)
        else:
            raise ValueError('지원하지 않는 대화상자 작업입니다.')
