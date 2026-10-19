"""라이브러리 보기 정책. 목록 갱신 때 만든 인덱스를 조건 변경마다 재사용한다."""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TypedDict


CHOICES = {
    'mode': (('all', '영상 전체'), ('folders', '폴더별')),
    'viewing': (('', '모든 시청 상태'), ('unwatched', '안 봄'), ('abandoned', '보다 만'),
                ('finished', '다 봄'), ('favorite', '즐겨 보는 영상')),
    'original': (('', '원어 자막 전체'), ('yes', '원어 자막 있음'), ('no', '원어 자막 없음')),
    'translated': (('', '번역·다듬은 자막 전체'), ('yes', '번역·다듬은 자막 있음'), ('no', '번역·다듬은 자막 없음')),
    'added_preset': (('', '추가일 전체'), ('today', '오늘'), ('7', '최근 7일'), ('30', '최근 30일'), ('custom', '직접 지정')),
    'modified_preset': (('', '수정한 날짜 전체'), ('today', '오늘'), ('7', '최근 7일'), ('30', '최근 30일'), ('custom', '직접 지정')),
    'viewed_preset': (('', '마지막 시청 전체'), ('today', '오늘'), ('7', '최근 7일'), ('30', '최근 30일'), ('custom', '직접 지정')),
    'sort': (('title', '제목'), ('added', '추가일'), ('modified', '수정한 날짜'), ('viewed', '마지막 시청'), ('duration', '길이'), ('count', '시청 횟수')),
    'card_size': (('small', '작게'), ('medium', '보통'), ('large', '크게')),
}


class LibraryViewOptions(TypedDict):
    query: str
    mode: str
    folder: str
    tags: list[int]
    viewing: str
    original: str
    translated: str
    external: bool
    highlights: bool
    missing: bool
    added_preset: str
    added_from: str
    added_to: str
    modified_preset: str
    modified_from: str
    modified_to: str
    viewed_preset: str
    viewed_from: str
    viewed_to: str
    sort: str
    descending: bool
    card_size: str
    collapsed_folders: list[str]


def default_options() -> LibraryViewOptions:
    return dict(query='', mode='all', folder='', tags=[], viewing='', original='', translated='',
                external=False, highlights=False, missing=False, added_preset='', added_from='', added_to='',
                modified_preset='', modified_from='', modified_to='',
                viewed_preset='', viewed_from='', viewed_to='', sort='title', descending=False, card_size='medium', collapsed_folders=[])


FILTER_DEFAULTS = {key: value for key, value in default_options().items()
                   if key not in ('mode', 'folder', 'sort', 'descending', 'card_size', 'collapsed_folders')}


def normalize_options(value) -> LibraryViewOptions:
    if not isinstance(value, dict):
        raise ValueError('라이브러리 보기 조건이 올바르지 않습니다.')
    result = default_options()
    if value.keys() - result.keys():
        raise ValueError('알 수 없는 라이브러리 조건입니다.')
    for key, item in value.items():
        if key == 'tags':
            if not isinstance(item, list) or any(type(t) is not int or t <= 0 for t in item):
                raise ValueError('태그 목록이 올바르지 않습니다.')
            item = sorted(set(item))
        elif key == 'collapsed_folders':
            if not isinstance(item, list) or any(not isinstance(t, str) for t in item):
                raise ValueError('접힌 폴더 목록이 올바르지 않습니다.')
            item = sorted(set(item))
        elif type(item) is not type(result[key]):
            raise ValueError('라이브러리 조건의 형식이 올바르지 않습니다.')
        if key in CHOICES and item not in dict(CHOICES[key]):
            raise ValueError('지원하지 않는 라이브러리 조건입니다.')
        if key.endswith(('_from', '_to')) and item:
            date.fromisoformat(item)
        result[key] = item
    for prefix in ('added', 'modified', 'viewed'):
        start, end = result[prefix + '_from'], result[prefix + '_to']
        if result[prefix + '_preset'] == 'custom' and start and end and start > end:
            raise ValueError('시작 날짜는 끝 날짜보다 늦을 수 없습니다.')
    return result


def matches_title_tags(title, video_tags, query, required_tags):
    return query in title and required_tags <= video_tags


class LibraryFolder(TypedDict):
    id: str
    parent: str
    name: str
    path: str
    count: int
    depth: int


class LibraryChip(TypedDict):
    key: str
    label: str
    reset: LibraryViewOptions


def filter_chips(options, tags) -> list[LibraryChip]:
    chips = []
    if options['query']:
        chips.append(dict(key='query', label='제목: ' + options['query']))
    for key in ('viewing', 'original', 'translated'):
        if options[key]:
            chips.append(dict(key=key, label=dict(CHOICES[key])[options[key]]))
    for key, label in (('external', '외부 자막 있음'), ('highlights', '하이라이트 있음'), ('missing', '파일 없음')):
        if options[key]:
            chips.append(dict(key=key, label=label))
    for prefix, label in (('added', '추가일'), ('modified', '수정한 날짜'), ('viewed', '마지막 시청')):
        preset = options[prefix + '_preset']
        if preset and (preset != 'custom' or options[prefix + '_from'] or options[prefix + '_to']):
            text = (f"{options[prefix + '_from'] or '처음'} ~ {options[prefix + '_to'] or '끝 없음'}"
                    if preset == 'custom' else dict(CHOICES[prefix + '_preset'])[preset])
            chips.append(dict(key=prefix + '_preset', label=f'{label}: {text}'))
    for tag_id in options['tags']:
        if tag_id in tags:
            chips.append(dict(key=f'tag:{tag_id}', label=tags[tag_id]))
    for chip in chips:
        key = chip['key']
        reset = dict(options)
        if key.startswith('tag:'):
            reset['tags'] = [tid for tid in options['tags'] if tid != int(key[4:])]
        else:
            reset[key] = FILTER_DEFAULTS[key]
            if key.endswith('_preset'):
                reset[key.replace('_preset', '_from')] = ''
                reset[key.replace('_preset', '_to')] = ''
        chip['reset'] = reset
    return chips


def date_range(preset, start, end, today):
    """프리셋이나 직접 지정 범위를 로컬 날짜 경계로 바꾼다. 양 끝 날짜를 포함한다."""
    if preset in ('today', '7', '30'):
        days = 1 if preset == 'today' else int(preset)
        return today - timedelta(days=days - 1), today
    if preset == 'custom':
        return (date.fromisoformat(start) if start else None,
                date.fromisoformat(end) if end else None)
    return None, None


@dataclass
class LibraryViewIndex:
    snapshot: object
    folders: list[LibraryFolder]
    members: dict[str, set[int]]
    original: set[int]
    translated: set[int]
    external: set[int]
    highlights: set[int]
    titles: dict[int, str]
    tags: dict[int, set[int]]

    def select(self, options, now) -> list[int]:
        options = normalize_options(options)
        query = options['query'].strip().casefold()
        required_tags = set(options['tags'])
        members = self.members.get(options['folder'], set()) if options['mode'] == 'folders' and options['folder'] else None
        ranges = {}
        today = now.astimezone().date()
        for prefix in ('added', 'modified', 'viewed'):
            ranges[prefix] = date_range(options[prefix + '_preset'], options[prefix + '_from'],
                                        options[prefix + '_to'], today)

        def matches(video):
            vid = video.id
            status = self.snapshot.statuses[vid]  # #96 공용 _ViewingState 계산 결과
            if members is not None and vid not in members:
                return False
            if not matches_title_tags(self.titles[vid], self.tags.get(vid, set()), query, required_tags):
                return False
            state = options['viewing']
            if state and not (not status.finished and not status.abandoned if state == 'unwatched' else getattr(status, state)):
                return False
            for key in ('original', 'translated'):
                if options[key] and ((vid in getattr(self, key)) != (options[key] == 'yes')):
                    return False
            if any(options[key] and vid not in getattr(self, key) for key in ('external', 'highlights')):
                return False
            if options['missing'] and not video.missing:
                return False
            for prefix, value in (('added', video.registered_at), ('modified', video.modified_at),
                                  ('viewed', status.last_viewed_at)):
                start, end = ranges[prefix]
                if start is not None or end is not None:
                    if value is None:
                        return False
                    day = value.astimezone().date()
                    if (start and day < start) or (end and day > end):
                        return False
            return True

        def sort_key(video):
            if options['sort'] == 'title':
                return self.titles[video.id]
            if options['sort'] == 'added':
                return video.registered_at.timestamp()
            if options['sort'] == 'modified':
                return video.modified_at.timestamp() if video.modified_at else 0
            if options['sort'] == 'viewed':
                value = self.snapshot.statuses[video.id].last_viewed_at
                return value.timestamp() if value else 0
            if options['sort'] == 'duration':
                return video.duration
            stats = self.snapshot.video_statistics.get(video.id)
            return stats.viewing_count if stats else 0

        videos = sorted((v for v in self.snapshot.videos if matches(v)), key=lambda v: v.id)
        videos.sort(key=sort_key, reverse=options['descending'])
        if options['sort'] == 'viewed':
            videos.sort(key=lambda v: self.snapshot.statuses[v.id].last_viewed_at is None)
        elif options['sort'] == 'modified':
            videos.sort(key=lambda v: v.modified_at is None)
        return [v.id for v in videos]


def build_index(snapshot, watched_folders, connect):
    """디스크와 자막 본문을 읽지 않는다. 각 존재 검사는 인덱스에서 첫 행만 찾는다."""
    with connect() as db:
        rows = db.execute('''SELECT v.id,
            EXISTS(SELECT 1 FROM transcripts t WHERE t.video_id=v.id),
            EXISTS(SELECT 1 FROM transcripts t JOIN transcript_lines l ON l.transcript_id=t.id
                   JOIN translation_lines tr ON tr.line_id=l.id WHERE t.video_id=v.id),
            EXISTS(SELECT 1 FROM external_subtitle_files f JOIN external_subtitles s ON s.file_id=f.id
                   JOIN external_subtitle_lines l ON l.subtitle_id=s.id WHERE f.video_id=v.id),
            EXISTS(SELECT 1 FROM highlights h WHERE h.video_id=v.id)
            FROM videos v WHERE v.excluded=0''').fetchall()
    presence = [{r[0] for r in rows if r[column]} for column in range(1, 5)]
    nodes, members = {}, {}
    roots = [f.path for f in watched_folders]
    for video in snapshot.videos:
        direct = False
        for location in video.locations:
            matching = [root for root in roots if location.path.is_relative_to(root)]
            direct = direct or not matching
            for root in matching:
                parent = ''
                parts = location.path.parent.relative_to(root).parts
                path = root
                for depth in range(len(parts) + 1):
                    if depth:
                        path /= parts[depth - 1]
                    key = f'{root}|{path}'
                    nodes[key] = dict(id=key, parent=parent, name=path.name or str(path), path=str(path), count=0, depth=depth)
                    members.setdefault(key, set()).add(video.id)
                    parent = key
        for key, label, include in (('direct', '직접 추가', direct), ('missing', '파일 없음', video.missing)):
            if include:
                nodes[key] = dict(id=key, parent='', name=label, path=label, count=0, depth=0)
                members.setdefault(key, set()).add(video.id)
    children = {}
    for node in nodes.values():
        node['count'] = len(members[node['id']])
        children.setdefault(node['parent'], []).append(node)
    folders = []
    def visit(parent):
        for node in sorted(children.get(parent, []), key=lambda n: (n['name'].casefold(), n['id'])):
            folders.append(node)
            visit(node['id'])
    visit('')
    return LibraryViewIndex(snapshot, folders, members, *presence,
                            {v.id: v.title.casefold() for v in snapshot.videos},
                            {vid: {t.id for t in tags} for vid, tags in snapshot.tags.items()})
