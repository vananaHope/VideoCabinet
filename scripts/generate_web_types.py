"""웹 브리지 TypedDict에서 TypeScript 계약 생성. --check는 드리프트를 실패로 처리한다."""
import argparse
from pathlib import Path
import types
from typing import get_args, get_origin, get_type_hints, is_typeddict

from my_video_manager import web_library_data
from my_video_manager.web_contract import ACTIONS, SCAN_LOCKED_ACTIONS, SIGNALS, SLOTS, TABS
from my_video_manager.web_tokens import web_tokens
import json


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
    blocks.append('export type Action = ' + ' | '.join(json.dumps(name) for name in ACTIONS))
    blocks.append('export type Tab = ' + ' | '.join(json.dumps(name) for name, _ in TABS))
    blocks.append('export const tabs = ' + json.dumps(TABS, ensure_ascii=False) + ' as const')
    blocks.append('export const actions = ' + json.dumps(list(ACTIONS.items())[:-2], ensure_ascii=False) + ' as const')
    blocks.append('export const scanLockedActions: readonly Action[] = ' + json.dumps(SCAN_LOCKED_ACTIONS))
    blocks.append('export type Reply = (json: string) => void\nexport type Signal<T> = { connect: (handler: (value: T) => void) => void; disconnect: (handler: (value: T) => void) => void }')
    fields = []
    for name, args in SLOTS.items():
        parameters = [f'{key}: ' + ('Action' if name == 'action' and key == 'name' else 'Tab' if name == 'navigate' else ts_type(kind)) for key, kind in args]
        fields.append(f'  {name}: (' + ', '.join(parameters + ['reply: Reply']) + ') => void')
    fields.extend(f'  {name}: Signal<{ts_type(kind)}>' for name, kind in SIGNALS.items())
    blocks.append('export interface Bridge {\n' + '\n'.join(fields) + '\n}')
    # 실제 채널 객체를 넘기지 않는다. QObject 메서드와 signal.emit도 공개 표면에서 제외한다.
    fields = [f'    {name}: raw.{name}.bind(raw),' for name in SLOTS]
    fields.extend(f'    {name}: Object.freeze({{ connect: raw.{name}.connect.bind(raw.{name}), disconnect: raw.{name}.disconnect.bind(raw.{name}) }}),' for name in SIGNALS)
    blocks.append('export function publicBridge(raw: Bridge): Bridge {\n  return Object.freeze({\n' + '\n'.join(fields) + '\n  })\n}')
    return '\n'.join(blocks) + '\n'


def render_tokens():
    tokens = web_tokens()
    variables = {**tokens['colors'], **tokens['layout']}
    return ('/* scripts/generate_web_types.py로 생성. web_tokens.json을 수정하세요. */\n:root {\n'
            + ''.join(f'  --{key}: {value};\n' for key, value in variables.items()) + '}\n@theme {\n'
            + ''.join(f'  --{key}: {value};\n' for key, value in tokens['typography'].items()) + '}\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'frontend/src'
    for filename, text in [('bridge-types.ts', render_types()), ('tokens.css', render_tokens())]:
        path = root / filename
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != text:
                raise SystemExit(f'{filename}이 다릅니다: python scripts/generate_web_types.py')
        else:
            path.write_text(text, encoding='utf-8')
