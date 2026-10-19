"""desktop_lock 안에서만 실행하는 실제 mpv·Windows 포커스 탐침."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.environ.get('MVM_REAL_WINDOW_TESTS') != '1',
                    reason='실창 검사: MVM_REAL_WINDOW_TESTS=1과 desktop_lock 필요')
def test_random_shortcut_real_mpv_and_tray_roundtrip():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / 'scripts/check_web_random_shortcut.py'),
                    '--output', str(root / '.local/issue-199-real')], cwd=root, check=True, timeout=120)
