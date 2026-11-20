"""DESIGN.md frontmatter와 `.impeccable/design.json`이 토큰 원본(`web_tokens.json`)·DESIGN.md 본문과 같은지 본다(#385).

문서는 사람이 고치지만 값은 `web_tokens.json`을 옮겨 적은 것이라, 토큰을 바꾸고 문서를 잊으면 여기서 실패한다."""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOKENS = json.loads((ROOT / 'src/my_video_manager/web_tokens.json').read_text(encoding='utf-8'))
DESIGN = (ROOT / 'DESIGN.md').read_text(encoding='utf-8')
FRONTMATTER = yaml.safe_load(DESIGN.split('---\n')[1])
BODY = DESIGN.split('---\n', 2)[2]
IMPECCABLE = json.loads((ROOT / '.impeccable/design.json').read_text(encoding='utf-8'))


def rem(value):
    assert value.endswith('rem'), value
    return float(value[:-3])


def text(value):
    return f'{value:g}rem'


def roles():
    """역할 토큰을 문서에 적는 모양(크기는 rem 값, 굵기는 정수)으로 푼다."""
    font = ', '.join(name.strip().strip('"') for name in TOKENS['typography']['font-sans'].split(','))
    return {name: {'fontFamily': font, 'fontSize': TOKENS['typography'][role['size']], 'fontWeight': int(role['weight']),
                   'lineHeight': role['line-height'], 'letterSpacing': role['letter-spacing']}
            for name, role in TOKENS['typography']['roles'].items()}


def test_frontmatter_colors_typography_rounded_and_spacing_match_tokens():
    assert {k: v.lower() for k, v in FRONTMATTER['colors'].items()} == {k: v.lower() for k, v in TOKENS['colors'].items()}
    assert FRONTMATTER['typography'] == roles()
    # 둥글기 단계는 index.css의 @theme inline이 --radius에서 계산하는 식과 같다.
    radius = rem(TOKENS['layout']['radius'])
    steps = {'xs': radius - 0.5, 'sm': radius - 0.25, 'md': radius - 0.125, 'lg': radius, 'xl': radius + 0.25}
    assert FRONTMATTER['rounded'] == {**{k: text(v) for k, v in steps.items()}, 'full': '9999px'}
    unit = rem(TOKENS['layout']['spacing'])
    assert FRONTMATTER['spacing'] == {k: text(int(k) * unit) for k in FRONTMATTER['spacing']}


def test_frontmatter_component_references_resolve():
    for name, component in FRONTMATTER['components'].items():
        for key, value in component.items():
            if isinstance(value, str) and value.startswith('{'):
                group, token = value.strip('{}').split('.')
                assert token in FRONTMATTER[group], (name, key, value)


def test_impeccable_values_match_tokens():
    colors = {k: v.lower() for k, v in TOKENS['colors'].items()}
    assert set(IMPECCABLE['extensions']['colorMeta']) <= set(colors)
    meta = IMPECCABLE['extensions']['typographyMeta']
    for name, role in roles().items():
        assert {k: meta[name][k] for k in ('fontSize', 'fontWeight', 'lineHeight', 'letterSpacing')} == \
            {k: role[k] for k in ('fontSize', 'fontWeight', 'lineHeight', 'letterSpacing')}, name
    # 예시 CSS의 var(--토큰, 대체값)과 font 단축 속성은 토큰 값과 같아야 한다.
    sizes = {TOKENS['typography'][r['size']] for r in TOKENS['typography']['roles'].values()} | {TOKENS['typography']['text-sm']}
    for component in IMPECCABLE['components']:
        for token, fallback in re.findall(r'var\(--([a-z-]+), (#[0-9a-f]+)\)', component['css']):
            assert colors[token] == fallback, (component['name'], token)
        for weight, size in re.findall(r'font: (\d+) ([\d.]+rem)/', component['css']):
            assert weight in TOKENS['bundled-font']['weights'] and size in sizes, (component['name'], weight, size)


def named_rules(source):
    return dict(re.findall(r'^\*\*(The [^*]+ Rule)\.\*\* (.+)$', source, re.MULTILINE))


def bullets(heading):
    section = BODY.split(f'### {heading}\n', 1)[1].split('\n#', 1)[0]
    return [line[2:] for line in section.splitlines() if line.startswith('- ')]


def test_impeccable_narrative_follows_design_body():
    narrative = IMPECCABLE['narrative']
    assert {rule['name']: rule['body'] for rule in narrative['rules']} == named_rules(BODY)
    assert narrative['dos'] == bullets('Do:')
    assert narrative['donts'] == bullets("Don't:")
    assert narrative['keyCharacteristics'] == [line[2:] for line in BODY.split('**Key Characteristics:**\n', 1)[1].split('\n\n', 1)[0].splitlines()]
