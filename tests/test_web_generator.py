"""계약 확장이 생성 결과에 반영되는지 검증한다. M6의 위치 기반 분류 회귀를 막는다."""
import json
from pathlib import Path
import runpy

import pytest
from my_video_manager import web_contract


def generate():
    script = Path(__file__).resolve().parents[1] / 'scripts/generate_web_types.py'
    return runpy.run_path(str(script))['render_types']()


@pytest.mark.parametrize('group', ['MENU_ACTIONS', 'GEM_ACTIONS'])
def test_m6_appending_action_keeps_explicit_menu_and_gem_membership(monkeypatch, group):
    monkeypatch.setitem(getattr(web_contract, group), 'newAction', '새 작업')
    generated = generate()
    menu_line = next(line for line in generated.splitlines() if line.startswith('export const actions = '))
    menu = dict(json.loads(menu_line.removeprefix('export const actions = ').removesuffix(' as const')))
    assert menu == web_contract.MENU_ACTIONS
    assert set(menu).isdisjoint(web_contract.GEM_ACTIONS)
    assert ('newAction' in menu) == (group == 'MENU_ACTIONS')
    union = next(line for line in generated.splitlines() if line.startswith('export type Action = '))
    assert '"newAction"' in union


def test_slot_types_come_from_argument_contract_without_method_name_assumptions(monkeypatch):
    monkeypatch.setitem(web_contract.SLOTS, 'chooseDestination',
                        (web_contract.Argument('destination', str, 'Tab'),))
    monkeypatch.setitem(web_contract.SLOTS, 'runLibraryOperation',
                        (web_contract.Argument('operation', str, 'Action'),))
    generated = generate()
    assert 'chooseDestination: (destination: Tab, reply: Reply) => void' in generated
    assert 'runLibraryOperation: (operation: Action, reply: Reply) => void' in generated
