"""페이지별 계약 파일과 union 병합 등록부가 병렬 페이지 추가를 충돌 없이 합치는지 검증한다."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from my_video_manager.web_contract import CONTRACTS, TABS

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'src/my_video_manager'
REGISTRIES = (f'{PACKAGE}/web_contract.py', f'{PACKAGE}/web_tabs.py')


def test_each_contract_lives_in_its_own_page_file():
    for contract in CONTRACTS:
        module = importlib.import_module(f'my_video_manager.web_{contract.name}_contract')
        assert getattr(module, contract.name.upper()) is contract


def git(repo, *args):
    return subprocess.run(['git', '-c', 'user.name=test', '-c', 'user.email=test@example.com',
                           '-c', 'core.autocrlf=false', *args],
                          cwd=repo, capture_output=True, text=True, encoding='utf-8')


def add_page(repo, name):
    """새 페이지 PR이 하는 그대로 계약 파일 하나와 등록부 두 곳에 한 줄씩 더한다."""
    package = repo / PACKAGE
    (package / f'web_{name}_contract.py').write_text(
        'from .web_contract_types import BridgeContract\n\n'
        f"{name.upper()} = BridgeContract(name='{name}', interface='{name.title()}Bridge')\n", encoding='utf-8')
    registry = package / 'web_contract.py'
    lines = registry.read_text(encoding='utf-8').splitlines(keepends=True)
    last_import = max(index for index, line in enumerate(lines) if line.startswith('from .web_'))
    lines.insert(last_import + 1, f'from .web_{name}_contract import {name.upper()}\n')
    lines.insert(len(lines) - 1 - lines[::-1].index(')\n'), f'    {name.upper()},\n')
    registry.write_text(''.join(lines), encoding='utf-8')
    tabs = package / 'web_tabs.py'
    lines = tabs.read_text(encoding='utf-8').splitlines(keepends=True)
    lines.insert(len(lines) - 1 - lines[::-1].index(')\n'), f"    ('{name}', '{name}'),\n")
    tabs.write_text(''.join(lines), encoding='utf-8')
    assert git(repo, 'checkout', '-q', '-b', name, 'main').returncode == 0
    assert git(repo, 'add', f'{PACKAGE}/web_{name}_contract.py', *REGISTRIES).returncode == 0
    assert git(repo, 'commit', '-q', '-m', name).returncode == 0
    assert git(repo, 'checkout', '-q', 'main').returncode == 0


def test_parallel_new_pages_merge_without_conflict(tmp_path):
    if shutil.which('git') is None:
        pytest.skip('git이 없습니다.')
    repo = tmp_path / 'repo'
    shutil.copytree(ROOT / PACKAGE, repo / PACKAGE, ignore=shutil.ignore_patterns('__pycache__', 'web'))
    shutil.copy(ROOT / '.gitattributes', repo / '.gitattributes')
    assert git(repo, 'init', '-q', '-b', 'main').returncode == 0
    # 등록부만 추적해 병합 결과를 보고, 나머지 패키지는 import용으로만 둔다.
    assert git(repo, 'add', '.gitattributes', *REGISTRIES).returncode == 0
    assert git(repo, 'commit', '-q', '-m', 'base').returncode == 0
    add_page(repo, 'alpha')
    add_page(repo, 'beta')
    assert git(repo, 'checkout', '-q', 'alpha').returncode == 0
    merged = git(repo, 'merge', '--no-edit', 'beta')
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert git(repo, 'diff', '--name-only', '--diff-filter=U').stdout == ''
    script = ('import json; from my_video_manager import web_contract; '
              'print(json.dumps([web_contract.__file__, [c.name for c in web_contract.CONTRACTS], '
              '[t for t, _ in web_contract.TABS]]))')
    result = subprocess.run([sys.executable, '-c', script], cwd=repo / 'src',
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    module, names, tabs = json.loads(result.stdout)
    assert Path(module).is_relative_to(repo)
    assert names == [contract.name for contract in CONTRACTS] + ['alpha', 'beta']
    assert tabs == [tab for tab, _ in TABS] + ['alpha', 'beta']
