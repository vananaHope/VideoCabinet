"""웹 대화상자의 표시/명령 어댑터. 모든 저장 정책은 AppCore 공개 API를 따른다."""
from uuid import uuid4
from math import isfinite

from .highlight_editing import initial_time_input, resolve_time_input, time_input_maximum
from .onscreen_series import OnScreenSeriesChanged
from .onscreen_subtitles import (ONSCREEN_LANGUAGES, OcrLanguageUnavailable, OnScreenRegionChanged, RegionEdit,
                                 RegionOrigin, default_onscreen_language, onscreen_language_name)
from .review import ReviewConfirmationRequired
from .subtitle_queue_kind import ONSCREEN_SUBTITLE
from .translation_kind import ONSCREEN_TRANSLATION
from .translation_source import ONSCREEN, TRANSCRIPT
from .web_dialogs_data import row, values
from .web_library_data import tag_candidates_data, tag_usage_data


TITLES = {
    'tags': '영상 태그', 'tag-manager': '모든 태그 관리', 'tag-rename': '태그 이름 변경',
    'series': '시리즈 편집', 'highlights': '현재 영상의 하이라이트',
    'highlight': '하이라이트 시각·메모 편집', 'subtitles': '원어 자막 만들기',
    'review': '자막 검수 · SRT 내보내기', 'line': '자막 줄 수정',
    'range': '구간 원어 자막 다시 생성', 'translation': '번역 방식 / 재시도',
    'video-rename': '제목 변경', 'video-exclude': '영상 제외',
    'random-scope': '무작위 이어 재생 범위', 'onscreen-region': '화면 자막 영역 · 읽을 언어',
    'onscreen-region-delete': '화면 자막 영역 지우기',
}
RANDOM_SCOPE_CHOICES = (('all', '영상 전체'), ('list', '재생을 시작한 목록'), ('tags', '태그 고르기'))
# 검수 화면의 SRT 저장 작업 → (번역 자막인가, 번역 출처).
EXPORT_ACTIONS = {'export-original': (False, TRANSCRIPT), 'export-translation': (True, TRANSCRIPT),
                  'export-onscreen': (False, ONSCREEN), 'export-onscreen-translation': (True, ONSCREEN)}
# 저장된 줄이 있을 때만 검수 화면이 더 보여 주는 화면 자막 SRT 저장.
ONSCREEN_EXPORTS = (('export-onscreen', '화면 자막 SRT 저장'),
                    ('export-onscreen-translation', f'{ONSCREEN_TRANSLATION.short_label} SRT 저장'))


# 검수 화면의 자막 고르기에서 받아쓰기 자막(원어·번역)을 가리키는 값. 화면 자막은 영역 ID다.
TRANSCRIPT_VIEW = 'transcript'
ONSCREEN_LOCKED = '화면 자막 읽기 대기·진행 중에는 화면 자막 줄 수정과 구간 재생성을 할 수 없습니다.'
ONSCREEN_NO_TEXT = '이 영역에서 읽은 글자가 없습니다. 구간 다시 생성으로 다시 읽거나 영역과 읽을 언어를 확인하세요.'
# 화면 자막 영역의 "시리즈 전체에 적용" 선택지 아래 안내. 시리즈에서 온 화는 켜진 채, 그 밖은 꺼진 채 열린다.
SERIES_OPT_OUT = '끄면 이 화는 앞으로 시리즈 영역 변경을 따르지 않습니다.'
SERIES_OPT_IN = ('켜면 이 화의 영역 묶음이 시리즈 영역이 되어, 시리즈 영역을 받은 화와 영역이 없는 화에 적용됩니다. '
                 '직접 정한 다른 화는 바뀌지 않습니다.')
# 시리즈 영역 확인 창: 더하기(시리즈에서 온 화에 새 영역, 보통은 확인 없이 바로 바뀐다), 고치기(시리즈에서 온 영역), 지우기,
# 바꾸기(직접 정한 화의 묶음으로 기존 시리즈 영역을 바꿈). 종류는 코어가 잰 범위(impact.change)를 따른다.
SERIES_TITLES = {'add': '시리즈 화면 자막 영역 더하기', 'update': '시리즈 화면 자막 영역 고치기',
                 'delete': '시리즈 화면 자막 영역 지우기', 'replace': '시리즈 화면 자막 영역 바꾸기'}


def review_row(line, task, providers, original_label):
    """검수 줄 한 행. 받아쓰기 자막과 화면 자막이 같은 상태 규칙(원어·원문 검수됨, 직접 수정, 줄별 번역 방식)을 쓴다."""
    from .translation_models import TRANSLATION_CHOICES
    provider = not line.translation_reviewed and providers.get(line.original.id)
    status = ' · '.join(label for flag, label in (
        (line.original_reviewed, original_label),
        (line.translation_reviewed, '사용자가 고친 줄' if task.kind == 'refinement' else '직접 수정'),
        (provider, dict(TRANSLATION_CHOICES).get(provider, ''))) if flag)
    missing = '미번역' if task.kind == ONSCREEN_TRANSLATION.kind else f'미{task.label}'
    return row(line.original.id, line.original.text, line.translation if line.translation is not None else missing,
               status, line.original.start, line.original.end)


def region_place(rect):
    return f'가로 {rect.x:.0%}–{rect.x + rect.width:.0%}, 세로 {rect.y:.0%}–{rect.y + rect.height:.0%}'


def region_language(language):
    return f'{onscreen_language_name(language)}({language})'


def onscreen_region(core, video_id, region_id):
    region = next((r for r in core.onscreen_subtitle_regions(video_id) if r.id == region_id), None)
    if region is None:
        raise ValueError('화면 자막 영역이 바뀌었습니다. 영역 정하기를 다시 여세요.')
    return region


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
        # 대화상자 갱신 타이머가 0.5초마다 snapshot을 만든다. 태그 사용 수는 대화상자 작업 뒤에만 다시 센다.
        self.tag_usage = None
        # 범위 고르기의 범위별 후보 수와 태그별 후보. 창을 열 때 한 번 세고, 확인할 때 코어가 다시 센다.
        self.scope_candidates = None
        # 검수 화면이 지금 보는 자막: None이면 받아쓰기 자막(원어·번역), 아니면 그 화면 자막 영역의 ID.
        self.region_id = None
        # 화면 자막 영역 창: 영상이 속한 시리즈(없으면 None)와, 보인 시리즈 확인 창의 (종류, 범위 다시 재기, 본 범위, 확인).
        self.video_series = None
        self.series_change = None
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
            self.waiting = [(e.video_id, e.source) for e in self.core.translation_queue() if e.state in ('failed', 'held')]
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
        elif kind == 'random-scope':
            scope = self.core.random_continuous_scope
            if scope is not None:
                self.values.update(choice=scope.kind, members=[str(tag_id) for tag_id in scope.tag_ids])
        elif kind == 'onscreen-region':
            transcript = self.core.transcript(context['video_id'])
            self.spoken_language = transcript.spoken_language if transcript else None
            self.values['choice'] = default_onscreen_language(self.spoken_language) or ''
            self.editing = self.reviewed = None
            if context.get('region_id') is not None:
                # 고치기: 읽을 언어의 기본값은 그 영역의 지금 언어다. self.reviewed는 창이 보인 사라질 검수 수정 수다.
                self.editing = onscreen_region(self.core, context['video_id'], context['region_id'])
                self.values['choice'] = self.editing.language
                self.reviewed = self.core.onscreen_subtitle_region_reviewed_line_count(self.editing.id)
            # 시리즈에 속한 화에만 "시리즈 전체에 적용"이 있다. 시리즈에서 온 화면 켜진 채 연다.
            self.video_series = self.core.series_for_video(context['video_id'])
            self.from_series = any(region.origin == RegionOrigin.SERIES
                                   for region in self.core.onscreen_subtitle_regions(context['video_id']))
            self.values['series'] = self.video_series is not None and self.from_series
        elif kind == 'onscreen-region-delete':
            self.region = onscreen_region(self.core, context['video_id'], context['region_id'])
            self.reviewed = self.core.onscreen_subtitle_region_reviewed_line_count(self.region.id)
            self.video_series = self.core.series_for_video(context['video_id'])
            if self.region.origin == RegionOrigin.SERIES and self.video_series is not None:
                self.ask_series_delete()
            else:
                self.ask_region_delete()
        elif kind == 'video-exclude':
            video = self.core.video(context['video_id'])
            def exclude():
                self.core.exclude_video(video.id)
                self.owner.pop(accepted=True)
            self.confirm(f"'{video.title}'을 제외할까요?\n실제 파일과 기록은 남으며 제외 목록에서 되돌릴 수 있습니다.",
                         exclude, title='영상 제외', destructive=True)

    def ask_region_delete(self, notice=''):
        """지우기 확인 창. 확인할 때 창이 보인 수(self.reviewed)를 넘겨, 그 사이 바뀌었으면 지우지 않고 다시 묻는다."""
        region, reviewed = self.region, self.reviewed
        lost = ('아직 화면 자막을 만들기 전인 영역입니다.' if reviewed is None else
                f'이 영역의 화면 자막과 화면 번역 자막, 검수로 고친 줄 {reviewed:,}개의 수정이 사라집니다.')

        def delete():
            try:
                self.core.delete_onscreen_subtitle_region(region.id, expected_reviewed_line_count=reviewed)
            except OnScreenRegionChanged as changed:
                self.reviewed = changed.reviewed_line_count
                self.ask_region_delete(f'{changed}\n')
                return
            except ValueError as gone:
                # 그 사이 영역이 사라졌다. 지울 것이 없으니 창을 닫고 알린다.
                self.owner.window.statusBar().showMessage(str(gone))
                self.owner.pop()
                return
            self.owner.window.statusBar().showMessage('화면 자막 영역을 지웠습니다.')
            self.owner.pop(accepted=True)
        title = self.core.video(self.context['video_id']).title
        self.confirm(f"{notice}'{title}'에서 화면 자막 영역({region_place(region.rect)}, 읽을 언어 "
                     f"{region_language(region.language)})을 지울까요?\n{lost} 다른 영역은 그대로입니다.",
                     delete, title=TITLES[self.kind], destructive=True)

    def ask_series(self, measure, impact, save, notice=''):
        """시리즈 영역 확인 창. 확인하면 창이 보인 범위(impact)를 넘겨, 그 사이 바뀌었으면 바꾸지 않고 다시 묻는다.
        measure()는 지금 범위를 다시 잰다(창이 열린 동안 안내를 지금 상태로 바꾼다). 문구는 범위의 변경 종류를 따른다."""
        self.series_change = (measure, impact, save)
        self.confirm(notice + self.series_message(impact), lambda: save(impact),
                     title=SERIES_TITLES[impact.change], destructive=True)

    def series_changed(self, measure, changed, save):
        """확인 창이 본 범위가 달라졌다. 지금 범위가 확인이 필요 없는 변경(기존 시리즈 영역을 바꾸지 않음)이면 처음 저장과
        같이 바로 저장하고, 아니면 지금 범위로 다시 묻는다."""
        if changed.impact.replaces_existing:
            self.ask_series(measure, changed.impact, save, f'{changed}\n')
        else:
            save(changed.impact)

    def series_message(self, impact):
        title = self.core.video(self.context['video_id']).title
        name, others, lost, change = self.video_series.name, impact.other_videos, impact.reviewed_line_count, impact.change
        if change == 'replace':
            episodes = f'이 화와 다른 화 {others:,}개' if others else '이 화'
            return (f"'{title}'의 영역 묶음으로 '{name}' 시리즈 영역을 바꿉니다.\n{episodes}의 화면 자막 영역이 바뀝니다. "
                    f'지금 시리즈 영역을 받은 화는 그 영역과 화면 자막·화면 번역 자막을 잃고, 검수로 고친 줄 {lost:,}개의 '
                    '수정이 사라집니다. 직접 정한 화는 그대로입니다.')
        episodes = f'이 화와 시리즈 영역을 받은 다른 화 {others:,}개' if others else '이 화(시리즈 영역을 받은 다른 화는 없습니다)'
        if change == 'add':
            reading = f'이 화와 다른 화 {others:,}개' if others else '이 화'
            return (f"'{title}'에서 '{name}' 시리즈 영역에 이 영역을 더합니다.\n{reading}에서 이 영역을 새로 읽습니다. "
                    '사라지는 화면 자막이나 검수는 없습니다. 직접 정한 화와 다른 영역은 그대로입니다.')
        if change == 'update':
            return (f"'{title}'에서 '{name}' 시리즈 영역을 고칩니다.\n{episodes}에서 이 영역의 화면 자막과 화면 번역 자막을 "
                    f'다시 만들고, 검수로 고친 줄 {lost:,}개의 수정이 사라집니다. 직접 정한 화와 다른 영역은 그대로입니다.')
        region = self.region
        return (f"'{title}'에서 '{name}' 시리즈 영역({region_place(region.rect)}, 읽을 언어 "
                f'{region_language(region.language)})을 지울까요?\n{episodes}에서 이 영역과 그 화면 자막·화면 번역 자막이 '
                f'사라지고, 검수로 고친 줄 {lost:,}개의 수정이 사라집니다. 직접 정한 화와 다른 영역은 그대로입니다.')

    def ask_series_delete(self):
        region, video_id = self.region, self.context['video_id']

        def measure():
            return self.core.onscreen_subtitle_region_series_impact(video_id, region.id, delete=True)

        def delete(impact):
            try:
                self.core.delete_onscreen_subtitle_region(region.id, expected_series_impact=impact)
            except OnScreenSeriesChanged as changed:
                self.series_changed(measure, changed, delete)
                return
            except ValueError as gone:
                self.owner.window.statusBar().showMessage(str(gone))
                self.owner.pop()
                return
            self.owner.window.statusBar().showMessage('시리즈 화면 자막 영역을 지웠습니다.')
            self.owner.pop(accepted=True)
        self.ask_series(measure, measure(), delete)

    def save_to_series(self, language):
        """시리즈 전체에 적용 선택지를 켜고 저장한다. 기존 시리즈 영역을 고치거나 통째로 바꾸면 확인 창을 거친다."""
        c, ctx = self.core, self.context
        region_id = ctx.get('region_id')

        def measure():
            return c.onscreen_subtitle_region_series_impact(ctx['video_id'], region_id)

        def save(impact):
            try:
                if region_id is not None:
                    c.update_onscreen_subtitle_region(region_id, ctx['region'], language, mode=RegionEdit.REBUILD,
                                                      series=True, expected_series_impact=impact)
                else:
                    c.add_onscreen_subtitle_region(ctx['video_id'], ctx['region'], language, series=True,
                                                   expected_series_impact=impact)
            except OnScreenSeriesChanged as changed:
                self.series_changed(measure, changed, save)
                return
            except OcrLanguageUnavailable as missing:
                self.message = str(missing)
                return
            self.owner.window.statusBar().showMessage(
                '자막 대기열에 화면 자막 만들기를 추가했습니다. 시리즈의 다른 화는 자동 대상으로 뒤이어 처리합니다.')
            self.owner.pop(accepted=True)
        impact = measure()
        if impact.replaces_existing and c.onscreen_language_available(language):
            self.ask_series(measure, impact, save)
        else:
            save(impact)  # 잃는 것이 없거나(언어 팩이 없으면 아무것도 바꾸지 않고 안내한다) 바로 저장한다.

    def save_region(self, save, status='자막 대기열에 화면 자막 만들기를 추가했습니다. 재생 중에도 계속 처리합니다.'):
        """영역 하나를 더하거나 고친다. 창이 본 것과 달라졌거나 언어 팩이 없으면 바꾸지 않고 안내한 채 다시 확인받는다."""
        try:
            save()
        except OnScreenRegionChanged as changed:
            # 창이 보인 안내와 사라질 것이 달라졌다. 바꾸지 않고 새 안내를 보인 채 다시 확인받는다.
            self.reviewed, self.message = changed.reviewed_line_count, str(changed)
            return
        except OcrLanguageUnavailable as missing:
            # 경고 안내로 설치 방법을 보이고 대기열에는 넣지 않는다. 다른 언어를 고르거나 취소할 수 있다.
            self.message = str(missing)
            return
        self.owner.window.statusBar().showMessage(status)
        self.owner.pop(accepted=True)

    def refresh_region_warning(self):
        """창이 열린 동안 그 영역의 읽기가 끝나면(화면 자막이 생기면) 사라질 것의 안내를 지금 상태로 바꾼다."""
        if self.series_change is not None and self.pending:
            measure, impact, save = self.series_change
            try:
                current = measure()
            except ValueError:
                return  # 영역이나 소속이 사라졌다. 확인하면 코어가 알린다.
            if current != impact or current.change != impact.change:
                self.ask_series(measure, current, save)
            return
        if self.context.get('region_id') is None:
            return
        try:
            reviewed = self.core.onscreen_subtitle_region_reviewed_line_count(self.context['region_id'])
        except ValueError:
            return  # 영역이 사라졌다. 확인하면 코어가 알린다.
        if reviewed != self.reviewed:
            self.reviewed = reviewed
            if self.kind == 'onscreen-region-delete' and self.pending:
                self.ask_region_delete()

    @property
    def expired(self):
        """대화상자가 기대는 상태가 사라졌는지. 범위 고르기는 무작위 이어 재생이 끝나면(목록 복귀 등),
        화면 자막 영역은 그 영상의 재생이 끝나면 쓸모가 없다."""
        if self.kind in ('onscreen-region', 'onscreen-region-delete'):
            session = self.core.playback.session
            return session is None or session.video_id != self.context['video_id']
        return self.kind == 'random-scope' and not self.core.random_continuous_enabled

    def onscreen_views(self):
        """검수 화면에서 고를 수 있는 화면 자막: 읽기를 마친(세대가 있는) 영역마다 (영역 번호, 화면 자막).
        영역 번호는 읽기를 기다리거나 실패한 영역도 포함한 영상의 영역 순서다."""
        video_id = self.context['video_id']
        numbers = {region.id: number for number, region in enumerate(self.core.onscreen_subtitle_regions(video_id), 1)}
        return [(numbers[subtitle.region.id], subtitle) for subtitle in self.core.onscreen_subtitles(video_id)]

    def onscreen_locked(self):
        video_id = self.context['video_id']
        return any(e.video_id == video_id and e.state in ('queued', 'reading')
                   for e in self.core.subtitle_queue(kind=ONSCREEN_SUBTITLE))

    def usage(self):
        if self.tag_usage is None:
            self.tag_usage = tag_usage_data(self.core.tag_usage())
        return self.tag_usage

    def random_scopes(self):
        if self.scope_candidates is None:
            from .random_continuous_play import RandomPlayScope
            c = self.core
            self.scope_candidates = (
                c.random_scope_video_count(RandomPlayScope()),
                c.random_scope_video_count(RandomPlayScope('list', c.playback_video_ids)),
                tag_candidates_data(c.random_tag_candidates()))
        return self.scope_candidates

    def snapshot(self):
        c, ctx, kind = self.core, self.context, self.kind
        if kind in ('onscreen-region', 'onscreen-region-delete'):
            self.refresh_region_warning()
        views = self.onscreen_views() if kind == 'review' else []
        viewed = next((subtitle for _, subtitle in views if subtitle.region.id == self.region_id), None)
        if kind == 'review' and self.region_id is not None and viewed is None:
            # 보던 영역을 고치거나 지웠다(세대가 사라짐). 받아쓰기 자막으로 돌아간다.
            self.region_id, self.information = None, '보던 화면 자막 영역이 바뀌어 받아쓰기 자막을 보입니다.'
        # 줄 수정·구간 다시 생성 창은 검수 화면이 보던 화면 자막 영역을 문맥으로 받는다.
        region_id = self.region_id if kind == 'review' else ctx.get('region_id')
        source = TRANSCRIPT if region_id is None else ONSCREEN
        task = c.subtitle_task(ctx['video_id'], source=source) if 'video_id' in ctx else None
        data = dict(task_kind=task.kind if task else '', task_label=task.label if task else '',
                    subtitle_label=task.subtitle_label if task else '', short_label=task.short_label if task else '',
                    keep_reviewed=self.keep_pending is not None, id=self.identifier, kind=kind, title=TITLES[kind], description='', rows=[], tags=[], tag_candidates=[], available=[], exports=[],
                    choices=[], values=self.values.copy(), maximum=0.0, locked=False, warning='',
                    confirmation=self.confirmation, confirm_title=self.confirm_title, confirm_destructive=self.confirm_destructive, translation=None, network_busy=False, information=self.information,
                    series_label='', series_note='', series_information='', move_language='', move_information='')
        if kind == 'tags':
            highlight = ctx.get('highlight_id')
            tags = c.highlight_tags(highlight) if highlight is not None else c.video_tags(ctx['video_id'])
            data.update(title='하이라이트 태그' if highlight is not None else TITLES[kind],
                        description='목록에서 골라 붙이기 · 없는 이름은 입력 후 Enter로 새 태그 · 변경은 즉시 저장됩니다.',
                        rows=[row(t.id, t.name) for t in tags], tags=self.usage())
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
        elif kind == 'random-scope':
            every, listed, candidates = self.random_scopes()
            source = c.playback_video_ids
            # 후보 수는 태그 고르기의 후보 안내와 같은 단위(개)로 센다.
            details = {'all': f'후보 {every}개',
                       'list': f'{c.playback_source_name or "재생 목록"} {len(source)}편 · 후보 {listed}개',
                       'tags': '고른 태그 중 하나라도 붙은 영상'}
            empty = {'all': not every, 'list': not listed, 'tags': not candidates}
            data.update(description='지금 영상은 끝까지 재생하고, 고른 범위는 다음 영상부터 씁니다. 이미 나온 영상과 이전·다음 기록은 그대로 둡니다.',
                        choices=[row(key, title, details[key], '후보가 없어 고를 수 없습니다.' if empty[key] else '')
                                 for key, title in RANDOM_SCOPE_CHOICES],
                        tags=self.usage(), tag_candidates=candidates)
        elif kind == 'subtitles':
            transcript = c.transcript(ctx['video_id'])
            languages = list(dict.fromkeys(['자동 감지', 'ko', 'en', 'ja', 'zh', 'de', 'fr', 'es', self.values['choice']]))
            data.update(description='원어를 고르거나 언어 코드를 입력하세요 (예: en, ko, ja).',
                        choices=[row(v, v) for v in languages])
            if transcript:
                data['description'] += f" 현재 원어: {transcript.spoken_language or '알 수 없음'} ({'직접 지정' if transcript.language_specified else '자동 감지'})"
            data['information'] = c.subtitle_preparation_notice()
        elif kind == 'onscreen-region':
            region = ctx['region']
            spoken = self.spoken_language
            default = ('기본값은 영상의 원어입니다.' if default_onscreen_language(spoken)
                       else '영상의 원어를 아직 몰라 직접 고르세요.' if spoken is None
                       else '영상의 원어가 한국어라 직접 고르세요.' if spoken == 'ko'
                       else f'영상의 원어({spoken})는 읽을 언어 목록에 없어 직접 고르세요.')
            editing = self.editing
            if editing is not None:
                default = f'지금 읽을 언어는 {region_language(editing.language)}입니다.'
            data.update(description=f'영역({region_place(region)}) 안 글자를 읽을 언어를 고르세요. {default} '
                                    '한국어 글자는 번역할 필요가 없어 고를 수 없습니다.',
                        choices=[*([row('', '읽을 언어 고르기')] if not self.values['choice'] else []),
                                 *[row(code, f'{name} ({code})') for code, name in ONSCREEN_LANGUAGES]])
            if editing is not None:
                data['title'] = '화면 자막 영역 고치기 · 읽을 언어'
                title = c.video(ctx['video_id']).title
                data['information'] = (
                    f"'{title}'의 이 영역만 고칩니다. 다른 영역은 그대로입니다." if self.reviewed is None else
                    f"'{title}'의 이 영역만 화면 자막과 화면 번역 자막을 다시 만듭니다. 검수로 고친 줄 "
                    f'{self.reviewed:,}개의 수정이 사라집니다. 다른 영역은 그대로입니다.')
                if self.reviewed is not None:
                    data.update(move_language=editing.language, move_information=(
                        f"'{title}'의 이 영역 자리만 바꿉니다. 다시 읽지 않아 화면 자막·화면 번역 자막·검수 기록이 "
                        '그대로 남고 번역 띠는 새 자리에 보입니다. 다른 영역은 그대로입니다.'))
            if self.video_series is not None:
                data.update(series_label=f'시리즈 전체에 적용 · {self.video_series.name}',
                            series_note=SERIES_OPT_OUT if self.from_series else SERIES_OPT_IN)
                if editing is not None:
                    # 선택지를 켜면 정보 줄이 이 화만이 아니라 시리즈 범위를 말한다. 확인 창과 같은 문구·숫자다.
                    try:
                        impact = c.onscreen_subtitle_region_series_impact(ctx['video_id'], editing.id)
                    except ValueError:
                        pass  # 영역이나 소속이 사라졌다. 저장하면 코어가 알린다.
                    else:
                        data['series_information'] = self.series_message(impact).replace('\n', ' ')
        elif kind == 'review':
            providers = c.translation_line_providers(ctx['video_id'], source=source)
            lines = c.review_lines(ctx['video_id']) if region_id is None else c.onscreen_review_lines(region_id)
            data.update(description='클릭 또는 Enter로 장면 이동 · 방향키로 줄 선택 · Tab으로 버튼 이동 · Esc로 닫기',
                        rows=[review_row(line, task, providers, '원어 검수됨' if region_id is None else '원문 검수됨')
                              for line in lines])
            data['exports'] = [row(action, title) for action, title in ONSCREEN_EXPORTS
                               if c.onscreen_export_available(ctx['video_id'], translated=EXPORT_ACTIONS[action][0])]
            # 읽기를 마친 화면 자막 영역이 있을 때만 검수할 자막을 고른다. 없으면 지금 검수 화면과 같다.
            if views:
                transcript = c.subtitle_task(ctx['video_id'])
                data['choices'] = [row(TRANSCRIPT_VIEW, f'받아쓰기 자막 · 원어 · {transcript.subtitle_label}'), *[
                    row(subtitle.region.id, f'화면 자막 영역 {number} · {region_language(subtitle.region.language)} · '
                        + (f'{len(subtitle.lines):,}줄' if subtitle.lines else '읽은 글자 없음'))
                    for number, subtitle in views]]
            data['values']['choice'] = TRANSCRIPT_VIEW if region_id is None else str(region_id)
            if viewed is not None and viewed.no_text:
                data['information'] = self.information or ONSCREEN_NO_TEXT
        elif kind == 'range':
            data['maximum'] = c.video(ctx['video_id']).duration
            try:
                if region_id is None:
                    start, end = c.subtitle_range_bounds(ctx['video_id'], self.values['start'], self.values['end'])
                    data['description'] = f'실제로 받아쓸 범위: {start:.3f}–{end:.3f}초. 경계에 걸친 줄 전체를 포함하도록 넓혀 원어와 {task.subtitle_label}을 교체합니다.'
                else:
                    start, end = c.onscreen_subtitle_range_bounds(region_id, self.values['start'], self.values['end'])
                    data['description'] = (f'실제로 다시 읽을 범위: {start:.3f}–{end:.3f}초. 이 영역에서 경계에 걸친 줄 전체를 '
                                           f'포함하도록 넓혀 화면 자막과 {task.subtitle_label}을 교체합니다. 다른 영역은 그대로입니다.')
            except ValueError as error:
                data['warning'] = str(error)
            if region_id is not None:
                data['title'] = '구간 화면 자막 다시 생성'
        elif kind == 'line':
            data['title'] = (f'{task.short_label} 줄 수정' if ctx['translated']
                             else '원어 줄 수정' if region_id is None else '원문 줄 수정')
        elif kind == 'translation':
            data.update(choices=[row(p['id'], p['label']) for p in self.translation['providers']],
                        translation=self.translation, network_busy=self.network_busy,
                        description='한국어 번역 방식과 모델을 고르세요. 한국어 영상의 다듬기도 같은 방식을 씁니다. 키·설정 변경은 확인할 때 저장됩니다.')
            if self.waiting:
                data['description'] += f' 확인하면 실패·보류 중인 번역·다듬기·화면 번역 {len(self.waiting)}건을 저장한 묶음부터 재시도합니다. 선택한 방식의 사용량 한도 보류 시간이 남았으면 그 시각까지 기다립니다.'
        if kind in ('review', 'line', 'range') and region_id is not None:
            # 화면 자막 잠금은 그 영상의 화면 자막 읽기 대기·진행이다. 화면 번역 줄 수정도 함께 막는다.
            data['locked'] = self.onscreen_locked()
            if data['locked']:
                data['warning'] = ONSCREEN_LOCKED
        elif kind in ('review', 'line', 'range'):
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
            if kind in ('video-exclude', 'onscreen-region-delete'):
                self.owner.pop()
            return
        if self.pending:
            raise ValueError('확인 또는 취소를 먼저 선택하세요.')
        if action == 'close':
            self.owner.pop(accepted=bool(data.get('accepted', False)))
            return
        if kind == 'random-scope' and action == 'save':
            from .random_continuous_play import RandomPlayScope
            choice = data.get('choice')
            if choice == 'all':
                scope = RandomPlayScope()
            elif choice == 'list':
                scope = RandomPlayScope('list', c.playback_video_ids)
            elif choice == 'tags':
                members = data.get('members')
                if not isinstance(members, list) or not members:
                    raise ValueError('태그를 하나 이상 고르세요.')
                scope = RandomPlayScope('tags', tag_ids=tuple(int(tag_id) for tag_id in members))
            else:
                raise ValueError('범위를 고르세요.')
            # 창을 연 뒤 라이브러리가 바뀌었을 수 있어 확인할 때 다시 센다.
            if not c.random_scope_video_count(scope):
                self.scope_candidates = None
                raise ValueError('고른 범위에 재생할 수 있는 영상이 없습니다. 다른 범위를 고르세요.')
            c.set_random_continuous_scope(scope)
            self.owner.pop(accepted=True)
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
        elif kind == 'onscreen-region' and action == 'save':
            if not data.get('choice'):
                raise ValueError('읽을 언어를 고르세요.')
            if data.get('series') and self.video_series is not None:
                self.save_to_series(data['choice'])
                return
            if ctx.get('region_id') is None:
                self.save_region(lambda: c.add_onscreen_subtitle_region(ctx['video_id'], ctx['region'], data['choice']))
                return
            # 자리만 바꾸기와 더 보기의 처음부터 다시 만들기는 방식을 적어 보낸다. 방식이 없으면 그 창에 단추가
            # "화면 자막 만들기" 하나뿐이었고, 잃을 것은 정보 줄이 이미 알렸다.
            chosen = data.get('mode')
            mode, reviewed = RegionEdit(chosen or RegionEdit.REBUILD), self.reviewed
            def update():
                c.update_onscreen_subtitle_region(ctx['region_id'], ctx['region'], data['choice'], mode=mode,
                                                  expected_reviewed_line_count=reviewed)
            if mode == RegionEdit.MOVE:
                self.save_region(update, '화면 자막 영역의 자리만 바꿨습니다. 화면 자막과 화면 번역 자막은 그대로입니다.')
            elif chosen is not None and reviewed is not None and data['choice'] == self.editing.language:
                # 자리만 바꾸기를 두고 더 보기에서 처음부터 다시 만들기를 골랐다. 잃는 것을 확인 창으로 한 번 더 묻는다.
                title = c.video(ctx['video_id']).title
                self.confirm(f"'{title}'의 이 영역을 처음부터 다시 만들까요?\n화면 자막과 화면 번역 자막을 지우고 영상 전체를 "
                             f'다시 읽어 다시 번역합니다. 검수로 고친 줄 {reviewed:,}개의 수정이 사라집니다. 다른 영역은 그대로입니다.',
                             lambda: self.save_region(update), title='화면 자막 처음부터 다시 만들기', destructive=True)
            else:
                self.save_region(update)
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
            if action == 'view':
                choice = data.get('choice')
                region = next((s.region.id for _, s in self.onscreen_views() if str(s.region.id) == choice), None)
                if choice != TRANSCRIPT_VIEW and region is None:
                    raise ValueError('화면 자막 영역이 바뀌었습니다. 목록을 새로 확인하세요.')
                self.region_id, self.information = region, ''
                return
            region_id = self.region_id
            lines = c.review_lines(ctx['video_id']) if region_id is None else c.onscreen_review_lines(region_id)
            line = next((line for line in lines if line.original.id == data.get('selected')), None)
            if action in ('jump', 'edit-original', 'edit-translation'):
                if line is None:
                    raise ValueError('자막 줄이 바뀌었습니다. 목록을 새로 확인하세요.')
                if action == 'jump':
                    ctx['jump'](ctx['video_id'], line.original.id)
                else:
                    self.push('line', **ctx, line=line, translated=action == 'edit-translation', region_id=region_id)
            elif action == 'range':
                self.push('range', **ctx, line=line, region_id=region_id)
            elif action == 'regenerate':
                def regenerate():
                    transcript = c.transcript(ctx['video_id'])
                    c.request_subtitles(ctx['video_id'], transcript.spoken_language if transcript and transcript.language_specified else None)
                self.confirm(c.subtitle_regeneration_warning(ctx['video_id']), regenerate, destructive=True)
            elif action in EXPORT_ACTIONS:
                translated, source = EXPORT_ACTIONS[action]
                export = c.subtitle_export(ctx['video_id'], translated=translated, source=source)
                callback = lambda: self.owner.save_export(export)
                if translated and (export.missing_lines or export.pending_retranslation_lines):
                    self.confirm(export.warning, callback)
                else:
                    callback()
            else:
                raise ValueError('지원하지 않는 검수 작업입니다.')
        elif kind == 'line' and action == 'save':
            region_id = ctx.get('region_id')
            def edit(overwrite=False, keep=False):
                line_id = ctx['line'].original.id
                if region_id is not None:
                    # 코어는 화면 번역 줄 수정을 잠그지 않는다. 검수 화면은 화면 자막 읽기 중 세 동작을 모두 막는다.
                    if self.onscreen_locked():
                        raise ValueError(ONSCREEN_LOCKED)
                    if ctx['translated']:
                        c.edit_onscreen_translation_line(line_id, data['text'])
                    else:
                        c.edit_onscreen_subtitle_line(line_id, data['text'], overwrite_reviewed=overwrite)
                elif ctx['translated']:
                    c.edit_translation_line(ctx['video_id'], line_id, data['text'])
                else:
                    c.edit_transcript_line(ctx['video_id'], line_id, data['text'], overwrite_reviewed=overwrite, keep_reviewed=keep)
                self.changed()
                self.owner.pop(accepted=True)
            try:
                edit()
            except ReviewConfirmationRequired as warning:
                self.confirm(str(warning), lambda: edit(True), destructive=True)
                # 다듬기의 "수정본 유지" 갈래는 받아쓰기 자막에만 있다.
                if region_id is None and c.subtitle_task(ctx["video_id"]).kind == "refinement":
                    self.keep_pending = lambda: edit(keep=True)
        elif kind == 'range':
            if action == 'bounds':
                self.values.update(start=self.time_value(data['start']), end=self.time_value(data['end']))
            elif action == 'save':
                start, end = self.time_value(data['start']), self.time_value(data['end'])
                if ctx.get('region_id') is None:
                    c.request_subtitle_range(ctx['video_id'], start, end)
                else:
                    c.request_onscreen_subtitle_range(ctx['region_id'], start, end)
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
            for video_id, source in self.waiting:
                try:
                    c.request_translation(video_id, source=source)
                except ValueError:
                    pass  # Qt 경로와 같이 그 사이 원어가 재생성된 영상은 새 요청을 따른다.
            from .translation_models import provider
            self.owner.window.statusBar().showMessage(f"번역 방식: {provider(data['choice']).label} {notice}", 5000)
            self.owner.pop(accepted=True)
        else:
            raise ValueError('지원하지 않는 대화상자 작업입니다.')
