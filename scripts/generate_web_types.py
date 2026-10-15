"""웹 브리지 TypedDict/dataclass에서 TypeScript 계약 생성. --check는 드리프트를 실패로 처리한다."""
import argparse
from pathlib import Path
import types
from typing import get_args, get_origin, get_type_hints

from my_video_manager.web_contract import CONTRACTS
from my_video_manager.web_tokens import web_tokens
import json


def ts_type(annotation):
    if annotation in (str, int, float, bool, type(None)):
        return {str: 'string', int: 'number', float: 'number', bool: 'boolean', type(None): 'null'}[annotation]
    if get_origin(annotation) is list:
        return f'Array<{ts_type(get_args(annotation)[0])}>'
    if get_origin(annotation) is tuple:
        args = get_args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:
            return f'Array<{ts_type(args[0])}>'
        return '[' + ', '.join(ts_type(arg) for arg in args) + ']'
    if get_origin(annotation) is types.UnionType:
        return ' | '.join(ts_type(arg) for arg in get_args(annotation))
    return annotation.__name__


def render_contract(contract):
    blocks = []
    for value in contract.data_types:
        fields = '\n'.join(f'  {key}: {ts_type(kind)}' for key, kind in get_type_hints(value).items())
        blocks.append(f'export interface {value.__name__} {{\n{fields}\n}}\n')
    for alias in contract.aliases:
        blocks.append(f'export type {alias.name} = ' + ' | '.join(json.dumps(name) for name in alias.values))
    for constant in contract.constants:
        annotation = f': {constant.typescript_type}' if constant.typescript_type else ''
        suffix = '' if constant.typescript_type else ' as const'
        blocks.append(f'export const {constant.name}{annotation} = '
                      + json.dumps(constant.values, ensure_ascii=False) + suffix)
    fields = []
    for name, args in contract.slots.items():
        parameters = [f'{arg.name}: {arg.typescript_type}' for arg in args]
        fields.append(f'  {name}: (' + ', '.join(parameters + ['reply: Reply']) + ') => void')
    fields.extend(f'  {name}: Signal<{ts_type(kind)}>' for name, kind in contract.signals.items())
    blocks.append(f'export interface {contract.interface} {{\n' + '\n'.join(fields) + '\n}')
    # 실제 채널 객체를 넘기지 않는다. QObject 메서드와 signal.emit도 공개 표면에서 제외한다.
    fields = [f'    {name}: raw.{name}.bind(raw),' for name in contract.slots]
    fields.extend(f'    {name}: Object.freeze({{ connect: raw.{name}.connect.bind(raw.{name}), disconnect: raw.{name}.disconnect.bind(raw.{name}) }}),' for name in contract.signals)
    blocks.append(f'export function public{contract.interface}(raw: {contract.interface}): {contract.interface} {{\n  return Object.freeze({{\n' + '\n'.join(fields) + '\n  })\n}')
    return '\n'.join(blocks) + '\n'


def render_types(contracts=CONTRACTS):
    names = [contract.name for contract in contracts]
    exports = [name for contract in contracts for name in (
        contract.interface, f'public{contract.interface}',
        *(value.__name__ for value in contract.data_types),
        *(alias.name for alias in contract.aliases), *(constant.name for constant in contract.constants))]
    if len(set(names)) != len(names) or len(set(exports)) != len(exports):
        raise ValueError('브리지 등록 이름 또는 TypeScript 공개 이름이 중복됩니다.')
    blocks = ['// scripts/generate_web_types.py로 생성. web_contract.py의 페이지 계약을 수정하세요.\n',
              'export type Reply = (json: string) => void\nexport type Signal<T> = { connect: (handler: (value: T) => void) => void; disconnect: (handler: (value: T) => void) => void }']
    blocks.extend(render_contract(contract) for contract in contracts)
    blocks.append('export interface Bridges {\n' + ''.join(
        f'  readonly {contract.name}: {contract.interface}\n' for contract in contracts) + '}')
    blocks.append('export function publicBridges(raw: Bridges): Bridges {\n  return Object.freeze({\n'
                  + ''.join(f'    {contract.name}: public{contract.interface}(raw.{contract.name}),\n' for contract in contracts)
                  + '  })\n}')
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
