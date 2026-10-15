"""독립 계약 추가·순서 변경과 불변 공개 표면의 생성 결과를 검증한다."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import runpy

import pytest
from my_video_manager.web_contract import (
    Argument, BridgeContract, Constant, CONTRACTS, LIBRARY, SHELL, TypeAlias,
)


def generator():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/generate_web_types.py'))


@pytest.mark.parametrize('menu_action', [True, False])
def test_appending_action_keeps_explicit_menu_and_gem_membership(menu_action):
    action = replace(LIBRARY.aliases[0], values=(*LIBRARY.aliases[0].values, 'newAction'))
    menu, locked = LIBRARY.constants
    if menu_action:
        menu = replace(menu, values=(*menu.values, ('newAction', '새 작업')))
    library = replace(LIBRARY, aliases=(action,), constants=(menu, locked))
    generated = generator()['render_types']((SHELL, library))
    menu_line = next(line for line in generated.splitlines() if line.startswith('export const actions = '))
    actual = dict(json.loads(menu_line.removeprefix('export const actions = ').removesuffix(' as const')))
    assert actual == dict(menu.values)
    assert ('newAction' in actual) == menu_action
    union = next(line for line in generated.splitlines() if line.startswith('export type Action = '))
    assert '"newAction"' in union


def test_slot_types_come_from_argument_contract_without_method_name_assumptions():
    library = replace(LIBRARY, slots={**LIBRARY.slots,
        'chooseDestination': (Argument('destination', str, 'Tab'),),
        'runLibraryOperation': (Argument('operation', str, 'Action'),)})
    generated = generator()['render_types']((library, SHELL))
    assert 'chooseDestination: (destination: Tab, reply: Reply) => void' in generated
    assert 'runLibraryOperation: (operation: Action, reply: Reply) => void' in generated


@pytest.mark.parametrize('position', [0, len(CONTRACTS) // 2, len(CONTRACTS)])
def test_new_page_bundle_adds_interface_wrapper_and_constants_without_changing_existing_pages(position):
    example = BridgeContract('example', 'ExampleBridge',
        slots={'find': (Argument('scope', str, 'ExampleScope'),)}, signals={'resultsChanged': str},
        aliases=(TypeAlias('ExampleScope', ('title', 'subtitle')),),
        constants=(Constant('exampleScopes', ('title', 'subtitle')),))
    api = generator()
    contracts = list(reversed(CONTRACTS))
    contracts.insert(position, example)
    before = api['render_types']()
    after = api['render_types'](contracts)
    for existing in CONTRACTS:
        block = api['render_contract'](existing)
        assert block in before and block in after
    assert 'export interface ExampleBridge' in after
    assert 'find: (scope: ExampleScope, reply: Reply) => void' in after
    assert 'export function publicExampleBridge(raw: ExampleBridge): ExampleBridge' in after
    assert 'example: publicExampleBridge(raw.example)' in after
    assert 'export const exampleScopes = ["title", "subtitle"] as const' in after


def test_contract_copies_mutable_inputs_and_prevents_later_mutation():
    slots = {'ready': ()}
    contract = BridgeContract('example', 'ExampleBridge', slots=slots)
    slots['deleteLater'] = ()
    assert 'deleteLater' not in contract.slots
    with pytest.raises(TypeError):
        contract.slots['deleteLater'] = ()
    with pytest.raises(TypeError):
        contract.signals['changed'] = str
    with pytest.raises(FrozenInstanceError):
        contract.name = 'other'


@pytest.mark.parametrize('example', [
    BridgeContract('library', 'ExampleBridge'),
    BridgeContract('example', 'LibraryBridge'),
    BridgeContract('example', 'ExampleBridge', constants=(Constant('tabs', ()),)),
])
def test_duplicate_channel_or_export_names_fail_instead_of_overwriting(example):
    with pytest.raises(ValueError, match='중복'):
        generator()['render_types']((*CONTRACTS, example))


def test_dataclass_and_tuple_extension_preserves_existing_contract_output():
    from my_video_manager.web_contract import STATISTICS
    from my_video_manager.statistics import ViewingStatistics
    api = generator()
    assert api['ts_type'](tuple[int, ...]) == 'Array<number>'
    assert api['ts_type'](tuple[str, int]) == '[string, number]'
    block = api['render_contract'](STATISTICS)
    assert 'daily: Array<DailyViewingStatistics>' in block
    assert 'top_videos: Array<TopViewedVideo>' in block
    assert 'library: LibraryStatistics' in block
    assert 'watched_seconds_change_percent: number | null' in block
    assert ViewingStatistics in STATISTICS.data_types
    # 기존 생성물이 통계 추가와 무관하게 바이트 단위로 유지된다.
    checked_in = (Path(__file__).resolve().parents[1] / 'frontend/src/bridge-types.ts').read_text(encoding='utf-8')
    for contract in (SHELL, LIBRARY):
        assert api['render_contract'](contract) in checked_in
