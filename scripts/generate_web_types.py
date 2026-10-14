"""웹 브리지 TypedDict에서 TypeScript 계약 생성. --check는 드리프트를 실패로 처리한다."""
import argparse
from pathlib import Path
import types
from typing import get_args, get_origin, get_type_hints, is_typeddict

from my_video_manager import web_library_data


def ts_type(annotation):
    if annotation in (str, int, float, bool, type(None)):
        return {str: 'string', int: 'number', float: 'number', bool: 'boolean', type(None): 'null'}[annotation]
    if get_origin(annotation) is list:
        return f'Array<{ts_type(get_args(annotation)[0])}>'
    if get_origin(annotation) is types.UnionType:
        return ' | '.join(ts_type(arg) for arg in get_args(annotation))
    return annotation.__name__


def render_types():
    blocks = ['// scripts/generate_web_types.py로 생성. Python TypedDict를 수정하세요.\n']
    for name, value in vars(web_library_data).items():
        if is_typeddict(value):
            fields = '\n'.join(f'  {key}: {ts_type(kind)}' for key, kind in get_type_hints(value).items())
            blocks.append(f'export interface {name} {{\n{fields}\n}}\n')
    return '\n'.join(blocks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / 'frontend/src/bridge-types.ts'
    text = render_types()
    if args.check:
        if path.read_text(encoding='utf-8') != text:
            raise SystemExit('브리지 타입이 다릅니다: python scripts/generate_web_types.py')
    else:
        path.write_text(text, encoding='utf-8')
