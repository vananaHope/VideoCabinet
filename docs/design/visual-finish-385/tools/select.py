"""#299 screens 이름 집합에 맞춰 새 촬영에서 같은 장면을 골라 복사한다.
usage: select.py SHOTS OLD_SCREENS OUT_SCREENS EXTRA_LIST
EXTRA_LIST: 한 줄에 '<영역>|<tag>|<원래 이름>' (새로 더할 장면)
출력: 맞춘 것·못 찾은 것 목록(stdout)
"""
import shutil, sys
from pathlib import Path
shots, old, out, extra = map(Path, sys.argv[1:5])
AREA = {
    'dialog': ['dialogs'],
    'dialog-random': ['library_random_tags', 'random_scope', 'library_random'],
    'dialog-tag': ['tag_dialog'],
    'folders-notice': ['scan_notice_copy', 'scan_notice'],
    'folders-settings': ['folders_settings'],
    'folders-watch': ['folder_watch'],
    'key-guide': ['keyguide_default', 'keyguide_long', 'keyguide_multi'],
    'library': ['loading', 'loading_long', 'loading_fail', 'loading_5000', 'views0', 'views5000', 'modified_copy', 'modified', 'key_gaps', 'dates', 'library_random'],
    'library-detail': ['external_subtitles', 'display_name'],
    'library-large': ['loading_long_large'],
    'library-small': ['loading_long_small'],
    'library-notice': ['library_place'],
    'library-tagpicker': ['tag_picker_copy', 'tag_picker'],
    'preparation': ['preparation2', 'preparation'],
    'queue': ['queue'],
    'recommend': ['recommend'],
    'reel-search': ['reel_search'],
    'settings': ['update', 'backup', 'app_icon', 'settings_recommend'],
    'statistics': ['stats0', 'stats8', 'stats50000', 'stats8_fail', 'stats8_pending', 'stats0_empty'],
}
src = {}
for size in ('1100', 'max'):
    missing = []
    (out / size).mkdir(parents=True, exist_ok=True)
    for f in sorted((old / size).glob('*.png')):
        area, name = f.name.split('--', 1)
        hit = next((shots / t / size / name for t in AREA[area] if (shots / t / size / name).exists()), None)
        if hit:
            shutil.copy(hit, out / size / f.name)
            src[(size, f.name)] = hit.parent.parent.name
        else:
            missing.append(f.name)
    for line in extra.read_text().split('\n'):
        if not line.strip():
            continue
        area, tag, name = line.split('|')
        p = shots / tag / size / name
        if p.exists():
            shutil.copy(p, out / size / f'{area}--{name}')
            src[(size, f'{area}--{name}')] = tag
        elif size == '1100':
            missing.append(f'(추가) {area}--{name}')
    print(f'[{size}] copied={len(list((out / size).glob("*.png")))} missing={len(missing)}')
    for m in missing:
        print('  MISSING', m)
(out.parent / 'sources.tsv').write_text(''.join(f'{s}\t{n}\t{t}\n' for (s, n), t in sorted(src.items())), encoding='utf-8')
